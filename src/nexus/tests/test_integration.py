"""Integration tests for the Nexus Fleet Model (NX-SPEC-09).

End-to-end tests that exercise the full framework: bot startup, Nexus Bus
event round-trips, circuit breakers, crash-loop detection, orchestrator
routing, update pipeline canary/rollback, flywheel collection, sentinel
test cycles, repair loops, enforcement, and manifest validation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import yaml

from nexus.bot.base import FleetBot
from nexus.bot.tools import Tool
from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.flywheel.analyzer import AnalysisReport, WeeklyAnalysisEngine
from nexus.flywheel.collector import FailureEventCollector
from nexus.manifest import load_manifest
from nexus.manifest.schema import BotConfig, Defaults, FleetManifest
from nexus.orchestrator import OrchestratorRouter, SubTask, TaskDecomposer
from nexus.self_healing.circuit_breaker import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitOpenError,
)
from nexus.self_healing.crash_loop_detector import (
    CrashLoopDetector,
    CrashLoopStatus,
)
from nexus.testing.enforcement import TestEnforcer
from nexus.testing.recipe import RecipeRegistry, TestCase, TestRecipe
from nexus.testing.sentinel import Sentinel, TestCycleResult
from nexus.testing.conversation import ConversationTrajectory, ConversationTurn
from nexus.testing.judge import CriterionScore, JudgeResult
from nexus.testing.repair import FailureReport, RepairEngine
from nexus.updates import (
    ChangeSeverity,
    DeployResult,
    ManifestChange,
    RollbackResult,
    UpdatePipeline,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "fleet-manifest.yaml"


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


@pytest.fixture
def manifest() -> FleetManifest:
    return load_manifest(MANIFEST_PATH)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.call = AsyncMock(return_value={"content": "Test response"})
    return llm


def make_bot_config(
    bot_id: str = "test-bot",
    tier: int = 1,
    port: int = 8090,
    service_name: str = "nexus-test-bot",
) -> BotConfig:
    return BotConfig(
        tier=tier,
        model="writer/palmyra-x6",
        discord_token_env=f"DISCORD_TOKEN_{bot_id.upper()}",
        system_prompt_file=f"prompts/{bot_id}.md",
        tools=["run_shell"],
        health_check_interval=30,
        port=port,
        systemd_service_name=service_name,
    )


# ---------------------------------------------------------------------------
# 1. test_full_startup_sequence
# ---------------------------------------------------------------------------


class TestFullStartupSequence:
    """Verify all 10 phases of FleetBot.start() execute in order."""

    async def test_full_startup_sequence(self, bus: NexusBus) -> None:
        class TestBot(FleetBot):
            def get_system_prompt(self) -> str:
                return "You are a test bot."

            def get_tools(self) -> list[Tool]:
                return []

            async def handle_task(self, event: NexusEvent) -> None:
                pass

            async def handle_message(self, message: Any) -> None:
                pass

        config = make_bot_config()
        bot = TestBot("test-bot", config, bus)

        # Patch all self-healing modules
        cld_mock = MagicMock()
        cld_mock.check_and_remediate = AsyncMock(
            return_value=CrashLoopStatus.HEALTHY
        )
        cld_class = MagicMock(return_value=cld_mock)

        hm_mock = MagicMock()
        hm_mock.start = AsyncMock()
        report = MagicMock()
        report.status.value = "healthy"
        report.uptime_s = 0.0
        report.metrics = {}
        hm_mock.run_checks = AsyncMock(return_value=report)
        hm_class = MagicMock(return_value=hm_mock)

        breakers_mock = MagicMock()
        breakers_mock.call_llm = AsyncMock(return_value={"content": "ok"})
        breakers_mock.call_tool = AsyncMock(return_value="ok")
        breakers_class = MagicMock(return_value=breakers_mock)

        sb_mock = MagicMock()
        sb_mock.record_call = MagicMock(return_value=False)
        sb_class = MagicMock(return_value=sb_mock)

        cm_mock = MagicMock()
        cm_mock.save = AsyncMock()
        cm_mock.get_latest = AsyncMock(return_value=None)
        cm_class = MagicMock(return_value=cm_mock)

        re_mock = MagicMock()
        re_mock.handle_failure = AsyncMock()
        re_class = MagicMock(return_value=re_mock)

        sup_mock = MagicMock()
        sup_mock.start = AsyncMock()
        sup_mock.observe = AsyncMock(return_value=None)
        sup_class = MagicMock(return_value=sup_mock)

        ra_mock = MagicMock()
        ra_class = MagicMock(return_value=ra_mock)

        llm_mock = MagicMock()
        llm_mock.call = AsyncMock(return_value={"content": "ok"})
        llm_class = MagicMock(return_value=llm_mock)

        tr_mock = MagicMock()
        tr_mock.execute = AsyncMock(return_value="ok")
        tr_class = MagicMock(return_value=tr_mock)

        with (
            patch("nexus.bot.base.CrashLoopDetector", cld_class),
            patch("nexus.bot.base.HealthMonitor", hm_class),
            patch("nexus.bot.base.CircuitBreakerManager", breakers_class),
            patch("nexus.bot.base.SemanticBreaker", sb_class),
            patch("nexus.bot.base.CheckpointManager", cm_class),
            patch("nexus.bot.base.RecoveryEngine", re_class),
            patch("nexus.bot.base.RuntimeSupervisor", sup_class),
            patch("nexus.bot.base.RemediationActions", ra_class),
            patch("nexus.bot.base.LLMClient", llm_class),
            patch("nexus.bot.base.ToolRegistry", tr_class),
        ):
            await bot.start()

        # Phase 1: crash loop detector
        cld_mock.check_and_remediate.assert_called_once()

        # Phase 2: health monitor started
        hm_mock.start.assert_called_once()

        # Phase 3: circuit breaker created
        breakers_class.assert_called_once()

        # Phase 4: semantic breaker created
        sb_class.assert_called_once()

        # Phase 5: checkpoint get_latest called
        cm_mock.get_latest.assert_called_once()

        # Phase 6: recovery engine created
        re_class.assert_called_once()

        # Phase 7: supervisor started
        sup_mock.start.assert_called_once()

        # Phase 8: nexus subscriptions (3 subscriptions)
        assert bus._handlers is not None
        assert EventType.TASK_NEW in bus._handlers
        assert EventType.HEALTH_ALERT in bus._handlers
        assert EventType.UPDATE_DEPLOY in bus._handlers

        # Phase 9: health check run and published
        hm_mock.run_checks.assert_called_once()

        # Phase 10: agent loop ran (checkpoint saved)
        cm_mock.save.assert_called()


# ---------------------------------------------------------------------------
# 2. test_nexus_bus_event_round_trip
# ---------------------------------------------------------------------------


class TestNexusBusEventRoundTrip:
    """Publish a task.new event, verify delivery to consumer group and ack."""

    async def test_nexus_bus_event_round_trip(self, bus: NexusBus, redis_client) -> None:
        # Subscribe a handler for task.new
        received: list[NexusEvent] = []

        async def handler(event: NexusEvent) -> None:
            received.append(event)

        await bus.subscribe(EventType.TASK_NEW, handler)

        # Start consumer
        await bus.start_consumer("test-consumer")

        # Publish a task.new event
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="test-consumer",
            payload={
                "task_id": "task-001",
                "task_type": "test",
                "description": "Test task",
                "priority": "normal",
                "deadline": None,
            },
        )
        await bus.publish(event)

        # Wait for the consumer to process
        await asyncio.sleep(0.5)

        assert len(received) >= 1
        assert received[0].event_type == EventType.TASK_NEW
        assert received[0].payload["task_id"] == "task-001"

        # Verify the event was acked (no pending entries)
        pending = await redis_client.xpending("nexus:tasks", "nexus:consumers")
        assert pending["pending"] == 0


# ---------------------------------------------------------------------------
# 3. test_circuit_breaker_protects_llm
# ---------------------------------------------------------------------------


class TestCircuitBreakerProtectsLLM:
    """Simulate LLM failures, verify breaker opens, half-opens, closes."""

    async def test_circuit_breaker_protects_llm(self) -> None:
        breaker = CircuitBreaker(
            name="llm:test-model",
            failure_threshold=3,
            recovery_timeout=1,
            success_threshold=2,
        )

        # Initially CLOSED
        assert breaker.state == BreakerState.CLOSED

        # Simulate failures to open the breaker
        async def failing_call() -> Any:
            raise RuntimeError("LLM timeout")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_call)

        # Breaker should be OPEN
        assert breaker.state == BreakerState.OPEN

        # Calling through an OPEN breaker raises CircuitOpenError
        with pytest.raises(CircuitOpenError):
            await breaker.call(failing_call)

        # Wait for recovery timeout to elapse
        await asyncio.sleep(1.1)

        # Breaker should transition to HALF_OPEN on next call
        async def success_call() -> str:
            return "success"

        result = await breaker.call(success_call)
        assert result == "success"
        assert breaker.state == BreakerState.HALF_OPEN

        # Need success_threshold successes to close
        result2 = await breaker.call(success_call)
        assert result2 == "success"
        assert breaker.state == BreakerState.CLOSED


# ---------------------------------------------------------------------------
# 4. test_crash_loop_detector_stops_cycle
# ---------------------------------------------------------------------------


class TestCrashLoopDetectorStopsCycle:
    """Simulate 5 consecutive restarts, verify detector trips and masks."""

    async def test_crash_loop_detector_stops_cycle(
        self, bus: NexusBus, redis_client, tmp_path: Path
    ) -> None:
        detector = CrashLoopDetector(
            bot_id="test-bot",
            service_name="nexus-test-bot",
            max_consecutive_failures=5,
            window_seconds=300,
            nexus_bus=bus,
        )
        # Override marker path to temp dir
        detector._marker_path = tmp_path / "test-bot-crash-loop-marker"

        # Mock systemd restart count to return 5
        detector._get_systemd_restart_count = AsyncMock(return_value=5)

        # Mock mask_service to avoid actual systemctl call
        detector._mask_service = AsyncMock()

        result = await detector.check_and_remediate()

        assert result == CrashLoopStatus.CRASH_LOOP_DETECTED

        # Verify marker file was written
        assert detector._marker_path.exists()

        # Verify health.alert was published
        entries = await redis_client.xrange("nexus:health")
        alert_events = [
            e for e in entries
            if "health.alert" in str(e[1].get("event_type", ""))
        ]
        assert len(alert_events) >= 1
        payload = json.loads(alert_events[0][1]["payload"])
        assert payload["alert_type"] == "crash_loop"
        assert payload["severity"] == "critical"


# ---------------------------------------------------------------------------
# 5. test_orchestrator_routes_task
# ---------------------------------------------------------------------------


class TestOrchestratorRoutesTask:
    """Create a request, verify it decomposes and routes to the correct bot."""

    async def test_orchestrator_routes_task(
        self, bus: NexusBus, manifest: FleetManifest
    ) -> None:
        router = OrchestratorRouter(bus, manifest)

        # Patch decomposer to return a single infrastructure sub-task
        subtask = SubTask(
            subtask_id="st-1",
            target_bot="architect",
            description="Fix the server infrastructure",
            priority="high",
        )
        router._decomposer.decompose = AsyncMock(return_value=[subtask])
        router._ack.wait_for_ack = AsyncMock(return_value=True)

        assignments = await router.route_request(
            "Fix the server infrastructure", "human_operator"
        )

        assert len(assignments) == 1
        assert assignments[0].subtask.target_bot == "architect"

        # Verify task.new was published to the nexus:tasks stream
        entries = await bus._redis.xrange("nexus:tasks")
        task_events = [
            e for e in entries
            if "task.new" in str(e[1].get("event_type", ""))
        ]
        assert len(task_events) >= 1
        payload = json.loads(task_events[0][1]["payload"])
        assert payload["description"] == "Fix the server infrastructure"


# ---------------------------------------------------------------------------
# 6. test_update_pipeline_canary_first
# ---------------------------------------------------------------------------


def _make_manifest(version: str = "2.0") -> FleetManifest:
    bots = {
        "admiral": BotConfig(
            tier=0, model="writer/palmyra-x6",
            discord_token_env="TOKEN_A", system_prompt_file="prompts/admiral.md",
            tools=["run_shell"], health_check_interval=30,
            port=8001, systemd_service_name="svc-a",
        ),
        "cartographer": BotConfig(
            tier=2, model="writer/palmyra-x6",
            discord_token_env="TOKEN_C", system_prompt_file="prompts/cart.md",
            tools=["read_file"], health_check_interval=30,
            port=8006, systemd_service_name="svc-c",
        ),
        "proctor": BotConfig(
            tier=3, model="writer/palmyra-x6",
            discord_token_env="TOKEN_P", system_prompt_file="prompts/proc.md",
            tools=["run_tests"], health_check_interval=30,
            port=8007, systemd_service_name="svc-p",
        ),
    }
    return FleetManifest(
        version=version, last_updated="2026-08-21T05:15:00Z",
        defaults=Defaults(), bots=bots,
    )


class TestUpdatePipelineCanaryFirst:
    """Simulate a manifest change, verify canary deploys first, health gate passes."""

    async def test_update_pipeline_canary_first(
        self, bus: NexusBus, redis_client
    ) -> None:
        old_manifest = _make_manifest("2.0")
        new_bots = dict(old_manifest.bots)
        new_bots["cartographer"] = BotConfig(
            tier=2, model="writer/new-model",
            discord_token_env="TOKEN_C", system_prompt_file="prompts/cart.md",
            tools=["read_file"], health_check_interval=30,
            port=8006, systemd_service_name="svc-c",
        )
        new_bots["proctor"] = BotConfig(
            tier=3, model="writer/new-model",
            discord_token_env="TOKEN_P", system_prompt_file="prompts/proc.md",
            tools=["run_tests"], health_check_interval=30,
            port=8007, systemd_service_name="svc-p",
        )
        new_manifest = _make_manifest("2.1")
        new_manifest.bots = new_bots

        change = ManifestChange(
            change_id="change-001",
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            old_commit="abc123def456",
            new_commit="def789abc012",
            affected_bots=["cartographer", "proctor"],
            severity=ChangeSeverity.MODEL_CHANGE,
            summary="Model update",
            timestamp="2026-08-21T05:15:00Z",
        )

        pipeline = UpdatePipeline(
            nexus=bus, manifest=new_manifest,
            canary_bot_id="cartographer",
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
        # Canary should be first in deployed_bots
        assert result.deployed_bots[0] == "cartographer"
        assert "proctor" in result.deployed_bots

        # Verify update.deploy events were published in order
        entries = await redis_client.xrange("nexus:updates")
        deploy_events = [
            e for e in entries
            if "update.deploy" in str(e[1].get("event_type", ""))
        ]
        assert len(deploy_events) >= 2
        first_payload = json.loads(deploy_events[0][1]["payload"])
        assert first_payload["bot_id"] == "cartographer"


# ---------------------------------------------------------------------------
# 7. test_update_pipeline_rollback
# ---------------------------------------------------------------------------


class TestUpdatePipelineRollback:
    """Simulate a failed deploy, verify rollback restores previous version."""

    async def test_update_pipeline_rollback(
        self, bus: NexusBus, redis_client, tmp_path: Path
    ) -> None:
        old_manifest = _make_manifest("2.0")
        new_manifest = _make_manifest("2.1")

        change = ManifestChange(
            change_id="change-002",
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            old_commit="abc123def456",
            new_commit="def789abc012",
            affected_bots=["cartographer"],
            severity=ChangeSeverity.MODEL_CHANGE,
            summary="Model update",
            timestamp="2026-08-21T05:15:00Z",
        )

        pipeline = UpdatePipeline(
            nexus=bus, manifest=new_manifest,
            canary_bot_id="cartographer",
            health_check_wait=1, deploy_timeout=5,
        )

        # Snapshot the previous version
        with patch("nexus.updates.rollback._ROLLBACK_DIR", tmp_path):
            await pipeline._rollback_manager.snapshot_previous(
                "cartographer", "abc123def456", old_manifest
            )

            # Mock deploy to succeed (so we reach the health gate)
            from nexus.updates.deployer import BotDeployResult
            pipeline._deployer.deploy = AsyncMock(
                return_value=BotDeployResult(
                    bot_id="cartographer",
                    success=True,
                    service_active=True,
                    health_healthy=True,
                    duration_seconds=0.01,
                    rolled_back=False,
                )
            )
            pipeline._deployer._manifest = new_manifest

            # Health gate checks: liveness fails
            pipeline._deployer.wait_for_active = AsyncMock(return_value=True)
            pipeline._deployer.wait_for_healthy = AsyncMock(return_value=False)

            # Mock rollback to succeed and publish health.alert
            # Patch at the class level since CanaryDeployer creates its own RollbackManager
            async def mock_rollback(self_rb, bot_id: str, to_version: str) -> RollbackResult:
                alert_event = NexusEvent.create(
                    event_type=EventType.HEALTH_ALERT,
                    source="rollback-manager",
                    target="broadcast",
                    payload={
                        "bot_id": bot_id,
                        "alert_type": "rollback",
                        "severity": "warning",
                        "message": f"Bot '{bot_id}' rolled back to version '{to_version}'",
                        "details": {
                            "to_version": to_version,
                            "success": True,
                            "alert_channels": ["discord"],
                        },
                    },
                )
                await bus.publish(alert_event)
                return RollbackResult(
                    bot_id=bot_id,
                    to_version=to_version,
                    success=True,
                    restored_manifest=old_manifest,
                    service_active=True,
                    health_restored=True,
                )

            with patch("nexus.updates.rollback.RollbackManager.rollback", mock_rollback):
                result = await pipeline.deploy_update(change)

        assert result.success is False
        assert result.canary_passed is False
        assert "cartographer" in result.failed_bots
        assert result.rollback_count >= 1

        # Verify health.alert was published for rollback
        entries = await redis_client.xrange("nexus:health")
        alert_events = [
            e for e in entries
            if "health.alert" in str(e[1].get("event_type", ""))
        ]
        assert len(alert_events) >= 1
        payload = json.loads(alert_events[0][1]["payload"])
        assert payload["alert_type"] == "rollback"


# ---------------------------------------------------------------------------
# 8. test_flywheel_collects_failures
# ---------------------------------------------------------------------------


class TestFlywheelCollectsFailures:
    """Publish failure.logged events, verify collector stores them, analyzer produces report."""

    async def test_flywheel_collects_failures(
        self, bus: NexusBus, redis_client, mock_llm
    ) -> None:
        collector = FailureEventCollector(nexus=bus, redis_client=redis_client)
        analyzer = WeeklyAnalysisEngine(
            collector=collector, llm_client=mock_llm, nexus=bus
        )

        # Publish failure events
        for i in range(3):
            event = NexusEvent.create(
                event_type=EventType.FAILURE_LOGGED,
                source="admiral",
                target="broadcast",
                payload={
                    "bot_id": "admiral",
                    "failure_type": "rate_limit",
                    "dependency": "llm:writer/palmyra-x6",
                    "error_message": f"Rate limit exceeded (attempt {i})",
                    "stack_trace": None,
                    "context": {"attempt": i},
                    "outcome": "retried",
                },
            )
            await collector.handle_failure(event)

        # Publish a recovery event
        recovery_event = NexusEvent.create(
            event_type=EventType.RECOVERY_EXECUTED,
            source="admiral",
            target="broadcast",
            payload={
                "bot_id": "admiral",
                "failure_type": "rate_limit",
                "recovery_action": "exponential_backoff",
                "success": True,
                "details": {"outcome": "recovered", "detail": "Recovered"},
            },
        )
        await collector.handle_recovery(recovery_event)

        # Verify collector stored them
        failures = await collector.get_failures()
        assert len(failures) == 3
        assert all(f.bot_id == "admiral" for f in failures)

        recoveries = await collector.get_recoveries()
        assert len(recoveries) == 1

        # Run analysis
        report = await analyzer.run_weekly_analysis()
        assert isinstance(report, AnalysisReport)
        assert report.total_failures == 3
        assert report.total_recoveries == 1
        assert "admiral" in report.failure_rate_by_bot
        assert report.recovery_success_rate == pytest.approx(1.0)
        assert len(report.recommendations) > 0


# ---------------------------------------------------------------------------
# 9. test_sentinel_runs_test_cycle
# ---------------------------------------------------------------------------


class TestSentinelRunsTestCycle:
    """Mock Sentinel's run_full_cycle, verify it tests all bots and publishes summary."""

    async def test_sentinel_runs_test_cycle(
        self, bus: NexusBus, redis_client, mock_llm, tmp_path: Path
    ) -> None:
        # Create recipes dir with test recipes
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()

        for bot_id in ["cortex", "voss"]:
            cases = []
            for i in range(20):
                cases.append({
                    "test_id": f"{bot_id}-{i:03d}",
                    "category": "domain_knowledge",
                    "question": f"Question {i}?",
                    "follow_ups": [],
                    "expected_behavior": "Good response",
                    "acceptance_keywords": ["good"],
                    "rejection_keywords": ["bad"],
                    "rubric_id": "domain_knowledge_rubric",
                    "difficulty": "easy",
                    "source": "manual",
                    "created_at": "2026-08-21T05:00:00Z",
                    "tests_feature": None,
                    "min_score": 7.0,
                })
            recipe_data = {
                "bot_id": bot_id,
                "version": "1.0.0",
                "last_updated": "2026-08-21T05:00:00Z",
                "total_cases": 20,
                "coverage": {"domain_knowledge": [c["test_id"] for c in cases]},
                "cases": cases,
            }
            with open(recipes_dir / f"{bot_id}.yaml", "w") as f:
                yaml.dump(recipe_data, f)

        registry = RecipeRegistry(recipes_dir=recipes_dir)
        sentinel = Sentinel(bus, mock_llm, redis_client, registry=registry)

        # Mock runner and judge
        def make_trajectory(test_id: str, bot_id: str) -> ConversationTrajectory:
            traj = ConversationTrajectory(test_id=test_id, bot_id=bot_id)
            traj.add_turn(ConversationTurn(role="user", content="Question?"))
            traj.add_turn(ConversationTurn(role="assistant", content="Answer"))
            return traj

        def make_passing_result(test_id: str, bot_id: str) -> JudgeResult:
            return JudgeResult(
                test_id=test_id, bot_id=bot_id,
                rubric_id="domain_knowledge_rubric",
                criterion_scores=[CriterionScore(name="role_clarity", score=9.0)],
                composite_score=9.0, passed=True, summary="Good",
            )

        sentinel._runner.run_test = AsyncMock(
            side_effect=lambda bot_id, tc: make_trajectory(tc.test_id, bot_id)
        )
        sentinel._judge.evaluate = AsyncMock(
            side_effect=lambda traj, tc: make_passing_result(tc.test_id, traj.bot_id)
        )

        results = await sentinel.run_full_cycle()

        # Should have tested both bots
        assert "cortex" in results
        assert "voss" in results
        assert results["cortex"].total_tests == 20
        assert results["cortex"].passed == 20
        assert results["voss"].total_tests == 20
        assert results["voss"].passed == 20

        # Verify cycle summary was published
        entries = await redis_client.xrange("nexus:testing")
        cycle_events = [
            e for e in entries
            if "testing.cycle_complete" in str(e[1].get("event_type", ""))
        ]
        assert len(cycle_events) >= 1
        payload = json.loads(cycle_events[0][1]["payload"])
        assert payload["passed"] == 40
        assert payload["failed"] == 0


# ---------------------------------------------------------------------------
# 10. test_sentinel_repair_loop
# ---------------------------------------------------------------------------


class TestSentinelRepairLoop:
    """Simulate a test failure, verify repair engine attempts fix, re-tests, escalates."""

    async def test_sentinel_repair_loop(
        self, bus: NexusBus, redis_client, mock_llm, tmp_path: Path
    ) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()

        cases = []
        for i in range(20):
            cases.append({
                "test_id": f"testbot-{i:03d}",
                "category": "domain_knowledge",
                "question": f"Question {i}?",
                "follow_ups": [],
                "expected_behavior": "Good response",
                "acceptance_keywords": ["good"],
                "rejection_keywords": ["bad"],
                "rubric_id": "domain_knowledge_rubric",
                "difficulty": "easy",
                "source": "manual",
                "created_at": "2026-08-21T05:00:00Z",
                "tests_feature": None,
                "min_score": 7.0,
            })
        recipe_data = {
            "bot_id": "testbot",
            "version": "1.0.0",
            "last_updated": "2026-08-21T05:00:00Z",
            "total_cases": 20,
            "coverage": {"domain_knowledge": [c["test_id"] for c in cases]},
            "cases": cases,
        }
        with open(recipes_dir / "testbot.yaml", "w") as f:
            yaml.dump(recipe_data, f)

        registry = RecipeRegistry(recipes_dir=recipes_dir)
        sentinel = Sentinel(bus, mock_llm, redis_client, registry=registry)

        def make_trajectory(test_id: str, bot_id: str) -> ConversationTrajectory:
            traj = ConversationTrajectory(test_id=test_id, bot_id=bot_id)
            traj.add_turn(ConversationTurn(role="user", content="Question?"))
            traj.add_turn(ConversationTurn(role="assistant", content="Answer"))
            return traj

        def make_failing_result(test_id: str, bot_id: str) -> JudgeResult:
            return JudgeResult(
                test_id=test_id, bot_id=bot_id,
                rubric_id="domain_knowledge_rubric",
                criterion_scores=[CriterionScore(name="role_clarity", score=3.0)],
                composite_score=3.0, passed=False, summary="Poor",
                failure_reasons=["Low score"],
            )

        sentinel._runner.run_test = AsyncMock(
            side_effect=lambda bot_id, tc: make_trajectory(tc.test_id, bot_id)
        )
        sentinel._judge.evaluate = AsyncMock(
            side_effect=lambda traj, tc: make_failing_result(tc.test_id, traj.bot_id)
        )

        # Mock repair engine to escalate and publish failure.logged events
        repair_call_count = 0

        async def mock_repair(failure: JudgeResult, test_case: TestCase, traj: ConversationTrajectory) -> FailureReport:
            nonlocal repair_call_count
            repair_call_count += 1
            # Publish failure.logged event (as the real RepairEngine._escalate would)
            event = NexusEvent.create(
                event_type=EventType.FAILURE_LOGGED,
                source="sentinel",
                target="admiral",
                payload={
                    "bot_id": failure.bot_id,
                    "failure_type": "test_failure",
                    "error_message": f"Test {failure.test_id} failed after repair attempts",
                    "stack_trace": None,
                    "context": {"test_id": failure.test_id},
                },
            )
            await bus.publish(event)
            return FailureReport(
                failure_id=f"f-{failure.test_id}",
                test_id=failure.test_id,
                bot_id=failure.bot_id,
                category=test_case.category,
                composite_score=failure.composite_score,
                min_score=test_case.min_score,
                final_status="escalated",
                escalated_to="admiral",
            )

        sentinel._repair_engine.repair = AsyncMock(side_effect=mock_repair)

        result = await sentinel._test_bot("testbot")

        assert result.total_tests == 20
        assert result.failed == 20
        assert result.escalated == 20
        assert result.passed == 0

        # Verify repair engine was called
        sentinel._repair_engine.repair.assert_called()

        # Verify failure.logged events were published (escalation)
        entries = await redis_client.xrange("nexus:failures")
        failure_events = [
            e for e in entries
            if "failure.logged" in str(e[1].get("event_type", ""))
        ]
        assert len(failure_events) >= 1


# ---------------------------------------------------------------------------
# 11. test_enforcement_blocks_commit
# ---------------------------------------------------------------------------


class TestEnforcementBlocksCommit:
    """Stage bot code changes without test updates, verify enforcer blocks."""

    def test_enforcement_blocks_commit(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()

        # Create a recipe for the bot
        cases = []
        for i in range(20):
            cases.append({
                "test_id": f"cortex-{i:03d}",
                "category": "domain_knowledge",
                "question": f"Question {i}?",
                "rubric_id": "domain_knowledge_rubric",
                "min_score": 7.0,
            })
        recipe_data = {
            "bot_id": "cortex",
            "version": "1.0.0",
            "total_cases": 20,
            "coverage": {},
            "cases": cases,
        }
        with open(recipes_dir / "cortex.yaml", "w") as f:
            yaml.dump(recipe_data, f)

        registry = RecipeRegistry(recipes_dir=recipes_dir)
        enforcer = TestEnforcer(registry=registry)

        # Stage bot code changes without test updates
        staged_files = [
            "src/bots/cortex/__init__.py",
            "src/bots/cortex/bot.py",
        ]

        result = enforcer.check_commit(staged_files)

        assert result.passed is False
        assert "cortex" in result.violated_bots
        assert "test" in result.message.lower()

    def test_enforcement_allows_commit_with_tests(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()

        cases = []
        for i in range(20):
            cases.append({
                "test_id": f"cortex-{i:03d}",
                "category": "domain_knowledge",
                "question": f"Question {i}?",
                "rubric_id": "domain_knowledge_rubric",
                "min_score": 7.0,
            })
        recipe_data = {
            "bot_id": "cortex",
            "version": "1.0.0",
            "total_cases": 20,
            "coverage": {},
            "cases": cases,
        }
        with open(recipes_dir / "cortex.yaml", "w") as f:
            yaml.dump(recipe_data, f)

        registry = RecipeRegistry(recipes_dir=recipes_dir)
        enforcer = TestEnforcer(registry=registry)

        # Stage bot code changes WITH test updates
        staged_files = [
            "src/bots/cortex/__init__.py",
            "tests/recipes/cortex.yaml",
        ]

        result = enforcer.check_commit(staged_files)
        assert result.passed is True


# ---------------------------------------------------------------------------
# 12. test_fleet_manifest_loads_and_validates
# ---------------------------------------------------------------------------


class TestFleetManifestLoadsAndValidates:
    """Load the actual fleet-manifest.yaml, verify all bots, tiers, ports."""

    def test_fleet_manifest_loads_and_validates(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)

        # All 8 bots present
        expected_bots = {
            "admiral", "architect", "voss", "cortex",
            "quartermaster", "cartographer", "proctor", "sentinel",
        }
        assert set(manifest.bots.keys()) == expected_bots

        # Exactly one tier 0 (Admiral)
        tier_0 = [name for name, bot in manifest.bots.items() if bot.tier == 0]
        assert len(tier_0) == 1
        assert tier_0[0] == "admiral"

        # All ports unique
        ports = [bot.port for bot in manifest.bots.values()]
        assert len(ports) == len(set(ports))

        # All systemd service names unique
        service_names = [bot.systemd_service_name for bot in manifest.bots.values()]
        assert len(service_names) == len(set(service_names))

        # Tiers are valid
        valid_tiers = {0, 1, 2, 3}
        for name, bot in manifest.bots.items():
            assert bot.tier in valid_tiers, f"Bot {name} has invalid tier {bot.tier}"

        # Routing table present
        assert manifest.routing_table is not None
        assert "infrastructure" in manifest.routing_table
        assert manifest.routing_table["infrastructure"] == "architect"
        assert manifest.routing_table["multi_domain"] == "decompose"

        # Update config present
        assert manifest.updates.canary_bot == "cartographer"
        assert manifest.updates.deployment_strategy == "phased"
        assert len(manifest.updates.rollout_order) == 7

        # Nexus bus config present
        assert manifest.nexus_bus.type == "redis_streams"
        assert manifest.nexus_bus.stream_prefix == "nexus"

        # Self-healing config present
        assert manifest.self_healing.circuit_breakers.llm.failure_threshold == 5
        assert manifest.self_healing.crash_loop_detector.max_restarts == 5
        assert manifest.self_healing.health_monitor.enabled is True
