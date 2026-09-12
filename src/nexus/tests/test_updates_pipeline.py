"""Tests for the Update Propagation Pipeline (NX-SPEC-07).

Unit tests mock subprocess (systemctl) and use fakeredis for Redis.
Integration tests use real Redis with mocked systemd.
All tests are async with @pytest.mark.asyncio.
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import yaml

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import BotConfig, Defaults, FleetManifest
from nexus.updates import (
    BotDeployer,
    BotDeployResult,
    CanaryDeployer,
    CanaryResult,
    ChangeSeverity,
    DeployResult,
    ManifestChange,
    RollbackManager,
    RollbackResult,
    UpdatePipeline,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bot_config(
    bot_id: str = "cartographer",
    tier: int = 2,
    model: str | None = None,
    tools: list[str] | None = None,
    port: int = 8006,
    service_name: str = "schubert-cartographer",
    prompt_file: str = "prompts/cartographer.md",
) -> BotConfig:
    return BotConfig(
        tier=tier,
        model=model,
        discord_token_env=f"DISCORD_TOKEN_{bot_id.upper()}",
        system_prompt_file=prompt_file,
        tools=tools or ["read_file", "write_file"],
        health_check_interval=30,
        port=port,
        systemd_service_name=service_name,
    )


def make_manifest(
    version: str = "2.0",
    bots: dict[str, BotConfig] | None = None,
) -> FleetManifest:
    if bots is None:
        bots = {
            "admiral": make_bot_config(
                "admiral", tier=0, port=8001, service_name="schubert-bot",
                prompt_file="prompts/admiral.md",
                tools=["run_shell", "fleet_delegate"],
            ),
            "cartographer": make_bot_config("cartographer", tier=2),
            "proctor": make_bot_config(
                "proctor", tier=3, port=8007, service_name="schubert-proctor",
                prompt_file="prompts/proctor.md",
            ),
        }
    return FleetManifest(
        version=version,
        last_updated="2026-08-21T05:15:00Z",
        defaults=Defaults(),
        bots=bots,
    )


def make_change(
    old_manifest: FleetManifest | None = None,
    new_manifest: FleetManifest | None = None,
    affected_bots: list[str] | None = None,
    severity: str = ChangeSeverity.CONFIG_TWEAK,
) -> ManifestChange:
    old = old_manifest or make_manifest("2.0")
    new = new_manifest or make_manifest("2.1")
    if affected_bots is None:
        affected_bots = ["cartographer"]
    return ManifestChange(
        change_id="change-001",
        old_manifest=old,
        new_manifest=new,
        old_commit="abc123def456",
        new_commit="def789abc012",
        affected_bots=affected_bots,
        severity=severity,
        summary="Test manifest change",
        timestamp="2026-08-21T05:15:00Z",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def bus(redis_client):
    bus = NexusBus(redis_url="redis://localhost:6379/0")
    bus._redis = redis_client
    yield bus
    await bus.stop_consumer()


def make_subprocess_mock(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a mock subprocess result."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(
        stdout.encode() if isinstance(stdout, str) else stdout,
        stderr.encode() if isinstance(stderr, str) else stderr,
    ))
    return proc


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------

class TestManifestDiff:
    """test_manifest_diff_identifies_affected_bots"""

    def test_manifest_diff_identifies_affected_bots(self) -> None:
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
            "proctor": make_bot_config("proctor", tier=3, port=8007, service_name="svc-p"),
        }
        new_bots = dict(old_bots)
        # Change cartographer's model
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006, model="custom/new-model"
        )
        # Change proctor's tools
        new_bots["proctor"] = make_bot_config(
            "proctor", tier=3, port=8007, service_name="svc-p",
            tools=["run_tests", "git_operations"],
        )

        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)

        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new

        affected = pipeline._diff_manifests(old, new)
        assert set(affected) == {"cartographer", "proctor"}
        assert "admiral" not in affected

    def test_manifest_diff_no_changes(self) -> None:
        manifest = make_manifest("2.0")
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = manifest
        affected = pipeline._diff_manifests(manifest, manifest)
        assert affected == []

    def test_manifest_diff_added_bot(self) -> None:
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
        }
        new_bots = dict(old_bots)
        new_bots["proctor"] = make_bot_config("proctor", tier=3, port=8007, service_name="svc-p")

        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new
        affected = pipeline._diff_manifests(old, new)
        assert "proctor" in affected


class TestSeverityClassification:
    """test_severity_classification"""

    def test_config_tweak_severity(self) -> None:
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
        }
        new_bots = dict(old_bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006, service_name="svc-c2",
        )
        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new
        severity = pipeline._classify_severity(old, new, "cartographer")
        assert severity == ChangeSeverity.CONFIG_TWEAK

    def test_system_prompt_severity(self) -> None:
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
        }
        new_bots = dict(old_bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006,
            prompt_file="prompts/new_prompt.md",
        )
        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new
        severity = pipeline._classify_severity(old, new, "cartographer")
        assert severity == ChangeSeverity.SYSTEM_PROMPT

    def test_tool_change_severity(self) -> None:
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
        }
        new_bots = dict(old_bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006,
            tools=["read_file", "wiki_publish"],
        )
        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new
        severity = pipeline._classify_severity(old, new, "cartographer")
        assert severity == ChangeSeverity.TOOL_CHANGE

    def test_model_change_severity(self) -> None:
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
        }
        new_bots = dict(old_bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006, model="writer/new-model",
        )
        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new
        severity = pipeline._classify_severity(old, new, "cartographer")
        assert severity == ChangeSeverity.MODEL_CHANGE

    def test_major_severity_for_new_bot(self) -> None:
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
        }
        new_bots = dict(old_bots)
        new_bots["cartographer"] = make_bot_config("cartographer", tier=2, port=8006)
        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new
        severity = pipeline._classify_severity(old, new, "cartographer")
        assert severity == ChangeSeverity.MAJOR

    def test_max_severity_across_changes(self) -> None:
        """When multiple attributes change, severity is the max."""
        old_bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
        }
        new_bots = dict(old_bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006,
            model="writer/new-model",
            tools=["read_file", "wiki_publish"],
            prompt_file="prompts/new.md",
        )
        old = make_manifest("2.0", bots=old_bots)
        new = make_manifest("2.1", bots=new_bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = new
        severity = pipeline._classify_severity(old, new, "cartographer")
        assert severity == ChangeSeverity.MODEL_CHANGE


class TestRolloutOrder:
    """test_rollout_order_is_risk_ascending"""

    def test_rollout_order_canary_first_admiral_last(self) -> None:
        bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
            "proctor": make_bot_config("proctor", tier=3, port=8007, service_name="svc-p"),
            "architect": make_bot_config("architect", tier=1, port=8002, service_name="svc-arch"),
        }
        manifest = make_manifest("2.0", bots=bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = manifest
        pipeline._canary_bot_id = "cartographer"

        affected = ["admiral", "cartographer", "proctor", "architect"]
        order = pipeline._rollout_order(affected, ChangeSeverity.CONFIG_TWEAK)

        assert order[0] == "cartographer"
        assert order[-1] == "admiral"
        mid = order[1:-1]
        tiers = [manifest.bots[b].tier for b in mid]
        assert tiers == sorted(tiers)

    def test_rollout_order_excludes_unaffected(self) -> None:
        bots = {
            "admiral": make_bot_config("admiral", tier=0, port=8001, service_name="svc-a"),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
            "proctor": make_bot_config("proctor", tier=3, port=8007, service_name="svc-p"),
        }
        manifest = make_manifest("2.0", bots=bots)
        pipeline = UpdatePipeline.__new__(UpdatePipeline)
        pipeline._manifest = manifest
        pipeline._canary_bot_id = "cartographer"

        affected = ["cartographer", "proctor"]
        order = pipeline._rollout_order(affected, ChangeSeverity.CONFIG_TWEAK)
        assert "admiral" not in order
        assert order[0] == "cartographer"


class TestCanaryDeployHealthy:
    """test_canary_deploy_healthy_proceeds"""

    @pytest.mark.asyncio
    async def test_canary_deploy_healthy_proceeds(self, bus: NexusBus) -> None:
        old_manifest = make_manifest("2.0")
        new_bots = dict(old_manifest.bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006, model="writer/new-model"
        )
        new_manifest = make_manifest("2.1", bots=new_bots)

        change = make_change(
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            affected_bots=["cartographer"],
            severity=ChangeSeverity.MODEL_CHANGE,
        )

        pipeline = UpdatePipeline(
            nexus=bus, manifest=new_manifest, canary_bot_id="cartographer",
            health_check_wait=1, deploy_timeout=5,
        )

        pipeline._deployer.restart_service = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_active = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_healthy = AsyncMock(return_value=True)
        pipeline._deployer._manifest = new_manifest
        pipeline._rollback_manager.snapshot_previous = AsyncMock(return_value=None)

        result = await pipeline.canary_deploy("cartographer", change)

        assert result.healthy is True
        assert result.rolled_back is False
        assert result.bot_id == "cartographer"
        assert result.change_id == "change-001"


class TestCanaryDeployUnhealthy:
    """test_canary_deploy_unhealthy_aborts"""

    @pytest.mark.asyncio
    async def test_canary_deploy_unhealthy_aborts(self, bus: NexusBus) -> None:
        old_manifest = make_manifest("2.0")
        new_bots = dict(old_manifest.bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006, model="writer/new-model"
        )
        new_manifest = make_manifest("2.1", bots=new_bots)

        change = make_change(
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            affected_bots=["cartographer"],
            severity=ChangeSeverity.MODEL_CHANGE,
        )

        pipeline = UpdatePipeline(
            nexus=bus, manifest=new_manifest, canary_bot_id="cartographer",
            health_check_wait=1, deploy_timeout=5,
        )

        pipeline._deployer.restart_service = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_active = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_healthy = AsyncMock(return_value=False)
        pipeline._deployer._manifest = new_manifest
        pipeline._rollback_manager.snapshot_previous = AsyncMock(return_value=None)
        pipeline._rollback_manager.rollback = AsyncMock(
            return_value=RollbackResult(
                bot_id="cartographer", to_version="abc123def456",
                success=True, restored_manifest=old_manifest,
                service_active=True, health_restored=True,
            )
        )

        result = await pipeline.canary_deploy("cartographer", change)

        assert result.healthy is False
        assert result.rolled_back is True


class TestRollbackRestoresPrevious:
    """test_rollback_restores_previous_version"""

    @pytest.mark.asyncio
    async def test_rollback_restores_previous_version(
        self, bus: NexusBus, tmp_path: Path
    ) -> None:
        old_manifest = make_manifest("2.0")

        deployer = BotDeployer(nexus=bus)
        rollback_mgr = RollbackManager(deployer=deployer, nexus=bus)

        with patch(
            "nexus.updates.rollback._ROLLBACK_DIR", tmp_path
        ):
            await rollback_mgr.snapshot_previous(
                "cartographer", "abc123def456", old_manifest
            )

            snapshot_path = tmp_path / "cartographer" / "abc123def456.yaml"
            assert snapshot_path.exists()

            deployer.restart_service = AsyncMock(return_value=True)
            deployer.wait_for_active = AsyncMock(return_value=True)
            deployer.wait_for_healthy = AsyncMock(return_value=True)

            result = await rollback_mgr.rollback("cartographer", "abc123def456")

        assert result.success is True
        assert result.bot_id == "cartographer"
        assert result.to_version == "abc123def456"
        assert result.restored_manifest is not None
        assert result.restored_manifest.version == "2.0"
        assert result.service_active is True
        assert result.health_restored is True


class TestDeployTimeoutTriggersRollback:
    """test_deploy_timeout_triggers_rollback"""

    @pytest.mark.asyncio
    async def test_deploy_timeout_triggers_rollback(self, bus: NexusBus) -> None:
        old_manifest = make_manifest("2.0")
        new_manifest = make_manifest("2.1")

        deployer = BotDeployer(nexus=bus, timeout=5)

        deployer.restart_service = AsyncMock(return_value=True)
        deployer.wait_for_active = AsyncMock(return_value=True)
        deployer.wait_for_healthy = AsyncMock(return_value=False)
        deployer._manifest = new_manifest

        result = await deployer.deploy(
            bot_id="cartographer",
            new_manifest=new_manifest,
            old_commit="abc123def456",
            old_manifest=old_manifest,
        )

        assert result.success is False
        assert result.rolled_back is True
        assert result.health_healthy is False
        assert "did not become healthy" in (result.error or "")


class TestDeployerRunsAsZ121532:
    """test_deployer_runs_as_z121532"""

    @pytest.mark.asyncio
    async def test_deployer_runs_as_z121532(self, bus: NexusBus) -> None:
        manifest = make_manifest("2.0")
        deployer = BotDeployer(nexus=bus)
        deployer._manifest = manifest

        call_args_list: list[list[str]] = []

        async def mock_create_subprocess_exec(*args, **kwargs):
            call_args_list.append(list(args))
            proc = make_subprocess_mock(stdout="active", returncode=0)
            return proc

        with patch(
            "nexus.updates.deployer.asyncio.create_subprocess_exec",
            side_effect=mock_create_subprocess_exec,
        ):
            await deployer.restart_service("cartographer")
            await deployer.wait_for_active("cartographer", timeout=5)
            await deployer.wait_for_healthy("cartographer", timeout=5)

        for args in call_args_list:
            assert args[0] == "sudo"
            assert args[1] == "-u"
            assert args[2] == "z121532"


class TestHealthGateRequiresAllGreen:
    """test_health_gate_requires_all_checks_green"""

    @pytest.mark.asyncio
    async def test_single_tripped_breaker_fails_gate(self, bus: NexusBus) -> None:
        old_manifest = make_manifest("2.0")
        new_manifest = make_manifest("2.1")

        deployer = BotDeployer(nexus=bus)
        canary = CanaryDeployer(deployer=deployer, nexus=bus, health_wait=1)

        change = make_change(
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            affected_bots=["cartographer"],
        )

        # Mock deploy to succeed so we reach the health gate
        deployer.deploy = AsyncMock(
            return_value=BotDeployResult(
                bot_id="cartographer",
                success=True,
                service_active=True,
                health_healthy=True,
                duration_seconds=0.01,
                rolled_back=False,
            )
        )
        deployer._manifest = new_manifest

        # Mock health gate checks: liveness fails
        async def fail_for_liveness(bot_id: str, timeout: int) -> bool:
            return False

        async def succeed_for_active(bot_id: str, timeout: int) -> bool:
            return True

        deployer.wait_for_healthy = fail_for_liveness
        deployer.wait_for_active = succeed_for_active

        result = await canary.deploy("cartographer", change)

        assert result.healthy is False
        assert "liveness_endpoint" in result.health_checks
        assert result.health_checks["liveness_endpoint"] is False


# ---------------------------------------------------------------------------
# Integration Tests (real Redis via fakeredis, mocked systemd)
# ---------------------------------------------------------------------------

class TestPipelinePublishesUpdateDeploy:
    """test_pipeline_publishes_update_deploy_event"""

    @pytest.mark.asyncio
    async def test_pipeline_publishes_update_deploy_event(
        self, bus: NexusBus, redis_client
    ) -> None:
        old_manifest = make_manifest("2.0")
        new_bots = dict(old_manifest.bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006, model="writer/new-model"
        )
        new_manifest = make_manifest("2.1", bots=new_bots)

        change = make_change(
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            affected_bots=["cartographer"],
            severity=ChangeSeverity.MODEL_CHANGE,
        )

        pipeline = UpdatePipeline(
            nexus=bus, manifest=new_manifest, canary_bot_id="cartographer",
            health_check_wait=1, deploy_timeout=5,
        )

        pipeline._deployer.restart_service = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_active = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_healthy = AsyncMock(return_value=True)
        pipeline._deployer._manifest = new_manifest
        pipeline._rollback_manager.snapshot_previous = AsyncMock(return_value=None)

        result = await pipeline.deploy_update(change)

        assert result.success is True

        # Verify update.deploy event was published to nexus:updates stream
        entries = await redis_client.xrange("nexus:updates")
        deploy_events = [
            e for e in entries
            if "update.deploy" in str(e[1].get("event_type", ""))
        ]
        assert len(deploy_events) >= 1

        # Verify the event payload
        import json
        payload = json.loads(deploy_events[0][1]["payload"])
        assert payload["bot_id"] == "cartographer"
        assert payload["version"] == "2.1"
        assert payload["update_id"] == "change-001"


class TestRollbackPublishesHealthAlert:
    """test_rollback_publishes_health_alert"""

    @pytest.mark.asyncio
    async def test_rollback_publishes_health_alert(
        self, bus: NexusBus, redis_client, tmp_path: Path
    ) -> None:
        old_manifest = make_manifest("2.0")

        deployer = BotDeployer(nexus=bus)
        rollback_mgr = RollbackManager(deployer=deployer, nexus=bus)

        with patch(
            "nexus.updates.rollback._ROLLBACK_DIR", tmp_path
        ):
            await rollback_mgr.snapshot_previous(
                "cartographer", "abc123def456", old_manifest
            )

            deployer.restart_service = AsyncMock(return_value=True)
            deployer.wait_for_active = AsyncMock(return_value=True)
            deployer.wait_for_healthy = AsyncMock(return_value=True)

            result = await rollback_mgr.rollback("cartographer", "abc123def456")

        assert result.success is True

        # Verify health.alert event was published
        entries = await redis_client.xrange("nexus:health")
        alert_events = [
            e for e in entries
            if "health.alert" in str(e[1].get("event_type", ""))
        ]
        assert len(alert_events) >= 1

        import json
        payload = json.loads(alert_events[0][1]["payload"])
        assert payload["bot_id"] == "cartographer"
        assert payload["alert_type"] == "rollback"
        assert "discord" in payload["details"]["alert_channels"]


class TestFullRolloutEndToEnd:
    """test_full_rollout_end_to_end"""

    @pytest.mark.asyncio
    async def test_full_rollout_end_to_end(
        self, bus: NexusBus, redis_client
    ) -> None:
        bots = {
            "admiral": make_bot_config(
                "admiral", tier=0, port=8001, service_name="svc-a",
                prompt_file="prompts/admiral.md", tools=["run_shell"],
            ),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
            "proctor": make_bot_config(
                "proctor", tier=3, port=8007, service_name="svc-p",
                prompt_file="prompts/proctor.md",
            ),
        }
        old_manifest = make_manifest("2.0", bots=dict(bots))
        new_bots = dict(bots)
        new_bots["cartographer"] = make_bot_config(
            "cartographer", tier=2, port=8006, model="writer/new-model"
        )
        new_bots["proctor"] = make_bot_config(
            "proctor", tier=3, port=8007, service_name="svc-p",
            prompt_file="prompts/proctor.md", model="writer/new-model",
        )
        new_manifest = make_manifest("2.1", bots=new_bots)

        change = make_change(
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            affected_bots=["cartographer", "proctor"],
            severity=ChangeSeverity.MODEL_CHANGE,
        )

        pipeline = UpdatePipeline(
            nexus=bus, manifest=new_manifest, canary_bot_id="cartographer",
            health_check_wait=1, deploy_timeout=5,
        )

        pipeline._deployer.restart_service = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_active = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_healthy = AsyncMock(return_value=True)
        pipeline._deployer._manifest = new_manifest
        pipeline._rollback_manager.snapshot_previous = AsyncMock(return_value=None)

        result = await pipeline.deploy_update(change)

        assert result.success is True
        assert result.canary_passed is True
        assert "cartographer" in result.deployed_bots
        assert "proctor" in result.deployed_bots
        assert len(result.failed_bots) == 0
        assert result.rollback_count == 0

        # Verify update.deploy events were published for both bots
        entries = await redis_client.xrange("nexus:updates")
        deploy_events = [
            e for e in entries
            if "update.deploy" in str(e[1].get("event_type", ""))
        ]
        assert len(deploy_events) >= 2


class TestFailedMidRollout:
    """test_failed_mid_rollout_leaves_prior_bots_on_new_version"""

    @pytest.mark.asyncio
    async def test_failed_mid_rollout_leaves_prior_bots_on_new_version(
        self, bus: NexusBus, redis_client
    ) -> None:
        bots = {
            "admiral": make_bot_config(
                "admiral", tier=0, port=8001, service_name="svc-a",
                prompt_file="prompts/admiral.md", tools=["run_shell"],
            ),
            "cartographer": make_bot_config("cartographer", tier=2, port=8006),
            "proctor": make_bot_config(
                "proctor", tier=3, port=8007, service_name="svc-p",
                prompt_file="prompts/proctor.md",
            ),
            "architect": make_bot_config(
                "architect", tier=1, port=8002, service_name="svc-arch",
                prompt_file="prompts/architect.md",
            ),
        }
        old_manifest = make_manifest("2.0", bots=dict(bots))
        new_bots = dict(bots)
        for bid in ["cartographer", "proctor", "architect"]:
            old_bc = bots[bid]
            new_bots[bid] = make_bot_config(
                bid, tier=old_bc.tier, port=old_bc.port,
                service_name=old_bc.systemd_service_name,
                prompt_file=old_bc.system_prompt_file,
                tools=old_bc.tools, model="writer/new-model",
            )
        new_manifest = make_manifest("2.1", bots=new_bots)

        change = make_change(
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            affected_bots=["cartographer", "proctor", "architect"],
            severity=ChangeSeverity.MODEL_CHANGE,
        )

        pipeline = UpdatePipeline(
            nexus=bus, manifest=new_manifest, canary_bot_id="cartographer",
            health_check_wait=1, deploy_timeout=5,
        )

        # Track which bots have been deployed - bot-aware mock
        # Rollout order: cartographer (canary), architect (tier 1), proctor (tier 3)
        # proctor is the third bot and should fail
        async def mock_restart(bot_id: str) -> bool:
            if bot_id == "proctor":
                return False
            return True

        pipeline._deployer.restart_service = mock_restart
        pipeline._deployer.wait_for_active = AsyncMock(return_value=True)
        pipeline._deployer.wait_for_healthy = AsyncMock(return_value=True)
        pipeline._deployer._manifest = new_manifest
        pipeline._rollback_manager.snapshot_previous = AsyncMock(return_value=None)
        pipeline._rollback_manager.rollback = AsyncMock(
            return_value=RollbackResult(
                bot_id="proctor", to_version="abc123def456",
                success=True, restored_manifest=old_manifest,
                service_active=True, health_restored=True,
            )
        )

        result = await pipeline.deploy_update(change)

        assert result.success is False
        assert "cartographer" in result.deployed_bots
        # architect is deployed second (tier 1) and should succeed
        assert "architect" in result.deployed_bots
        # proctor is deployed third (tier 3) and fails
        assert "proctor" in result.failed_bots
        assert result.rollback_count >= 1
