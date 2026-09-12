"""Unit tests for the Nexus Fleet Manifest loader and schema."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from nexus.manifest import (
    BotConfig,
    CircuitBreakerConfig,
    Defaults,
    FleetManifest,
    HealthGateConfig,
    HealthMonitorConfig,
    LlmBreakerConfig,
    NexusBusConfig,
    RecoveryConfig,
    RollbackConfig,
    SelfHealingConfig,
    ToolBreakerConfig,
    UpdatesConfig,
    load_manifest,
)
from nexus.manifest.schema import (
    CheckpointConfig,
    CrashLoopDetectorConfig,
    SemanticBreakerConfig,
    SupervisorConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "fleet-manifest.yaml"


# ── Valid manifest loading ────────────────────────────────────────────

class TestLoadValidManifest:
    def test_load_valid_manifest(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        assert manifest.version == "2.0"
        assert manifest.last_updated == "2026-08-21T05:15:00Z"

        # Defaults
        assert manifest.defaults.model == "writer/palmyra-x6"
        assert manifest.defaults.litellm_base_url == "http://localhost:4000"
        assert manifest.defaults.redis_url == "redis://localhost:6379/0"

        # All 8 bots present
        expected_bots = {
            "admiral", "architect", "voss", "cortex",
            "quartermaster", "cartographer", "proctor", "sentinel",
        }
        assert set(manifest.bots.keys()) == expected_bots

        # Admiral is tier 0
        assert manifest.bots["admiral"].tier == 0
        assert manifest.bots["admiral"].port == 8001
        assert manifest.bots["admiral"].systemd_service_name == "schubert-bot"

        # Architect tools
        assert "deploy_code" in manifest.bots["architect"].tools
        assert manifest.bots["architect"].port == 8002

        # Sentinel tools
        assert "generate_tests" in manifest.bots["sentinel"].tools
        assert "repair_code" in manifest.bots["sentinel"].tools

    def test_routing_table(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        assert manifest.routing_table is not None
        assert manifest.routing_table["infrastructure"] == "architect"
        assert manifest.routing_table["diagnostics"] == "voss"
        assert manifest.routing_table["analysis"] == "cortex"
        assert manifest.routing_table["resources"] == "quartermaster"
        assert manifest.routing_table["documentation"] == "cartographer"
        assert manifest.routing_table["compliance"] == "proctor"
        assert manifest.routing_table["multi_domain"] == "decompose"

    def test_nexus_bus_config(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        bus = manifest.nexus_bus
        assert bus.type == "redis_streams"
        assert bus.stream_prefix == "nexus"
        assert bus.consumer_group == "nexus-fleet"
        assert bus.consumer_name_prefix == "nexus-consumer"
        assert "task.*" in bus.event_namespaces
        assert "health.*" in bus.event_namespaces
        assert "update.*" in bus.event_namespaces
        assert "flywheel.*" in bus.event_namespaces
        assert "system.*" in bus.event_namespaces
        assert bus.max_stream_length == 10000
        assert bus.block_ms == 5000

    def test_self_healing_config(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        sh = manifest.self_healing

        # Circuit breakers
        assert sh.circuit_breakers.llm.failure_threshold == 5
        assert sh.circuit_breakers.llm.recovery_timeout == 30
        assert sh.circuit_breakers.llm.half_open_max_calls == 1
        assert sh.circuit_breakers.tools.failure_threshold == 3
        assert sh.circuit_breakers.tools.recovery_timeout == 60
        assert sh.circuit_breakers.tools.half_open_max_calls == 1

        # Health monitor
        assert sh.health_monitor.enabled is True
        assert sh.health_monitor.report_interval == 30
        assert sh.health_monitor.stale_threshold == 90

        # Semantic breaker
        assert sh.semantic_breaker.enabled is True
        assert sh.semantic_breaker.window == 3
        assert sh.semantic_breaker.repeat_threshold == 3

        # Crash loop detector
        assert sh.crash_loop_detector.enabled is True
        assert sh.crash_loop_detector.restart_window == 300
        assert sh.crash_loop_detector.max_restarts == 5
        assert sh.crash_loop_detector.action == "stop"

        # Checkpoint
        assert sh.checkpoint.enabled is True
        assert sh.checkpoint.backend == "redis"
        assert sh.checkpoint.key_prefix == "nexus:checkpoint"
        assert sh.checkpoint.save_on == "tool_success"

        # Supervisor
        assert sh.supervisor.enabled is True
        assert sh.supervisor.poll_interval == 10
        assert sh.supervisor.watchdog_timeout == 120

        # Recovery
        assert sh.recovery.retry_attempts == 3
        assert sh.recovery.backoff_base == 1
        assert sh.recovery.backoff_max == 30
        assert sh.recovery.jitter_max == 2
        assert sh.recovery.escalation_target == "admiral"

    def test_updates_config(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        upd = manifest.updates
        assert upd.canary_bot == "cartographer"
        assert upd.deployment_strategy == "phased"
        assert upd.rollout_order == [
            "cartographer", "proctor", "quartermaster",
            "voss", "cortex", "architect", "admiral",
        ]

        # Health gate
        assert upd.health_gate.wait_seconds == 60
        assert "systemd_active" in upd.health_gate.checks
        assert "liveness_endpoint" in upd.health_gate.checks
        assert "llm_test_request" in upd.health_gate.checks
        assert "no_new_errors" in upd.health_gate.checks
        assert "sentinel_tests_passed" in upd.health_gate.checks
        assert upd.health_gate.rollback_on_failure is True

        # Rollback
        assert upd.rollback.automatic is True
        assert upd.rollback.max_retries == 2
        assert "discord" in upd.rollback.alert_channels


# ── Validation: unique ports ──────────────────────────────────────────

class TestUniquePorts:
    def test_unique_ports(self) -> None:
        yaml_text = textwrap.dedent("""\
            version: "2.0"
            last_updated: "2026-08-21T05:15:00Z"
            defaults:
              model: "writer/palmyra-x6"
              litellm_base_url: "http://localhost:4000"
              redis_url: "redis://localhost:6379/0"
            bots:
              admiral:
                tier: 0
                discord_token_env: "TOKEN_A"
                system_prompt_file: "prompts/a.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9001
                systemd_service_name: "svc-a"
              architect:
                tier: 1
                discord_token_env: "TOKEN_B"
                system_prompt_file: "prompts/b.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9001
                systemd_service_name: "svc-b"
            """)
        tmp = Path("/tmp/test_dup_port.yaml")
        tmp.write_text(yaml_text, encoding="utf-8")
        with pytest.raises(ValueError, match="Duplicate port"):
            load_manifest(tmp)
        tmp.unlink()


# ── Validation: unique service names ──────────────────────────────────

class TestUniqueServiceNames:
    def test_unique_service_names(self) -> None:
        yaml_text = textwrap.dedent("""\
            version: "2.0"
            last_updated: "2026-08-21T05:15:00Z"
            defaults:
              model: "writer/palmyra-x6"
              litellm_base_url: "http://localhost:4000"
              redis_url: "redis://localhost:6379/0"
            bots:
              admiral:
                tier: 0
                discord_token_env: "TOKEN_A"
                system_prompt_file: "prompts/a.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9001
                systemd_service_name: "svc-dup"
              architect:
                tier: 1
                discord_token_env: "TOKEN_B"
                system_prompt_file: "prompts/b.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9002
                systemd_service_name: "svc-dup"
            """)
        tmp = Path("/tmp/test_dup_svc.yaml")
        tmp.write_text(yaml_text, encoding="utf-8")
        with pytest.raises(ValueError, match="Duplicate systemd_service_name"):
            load_manifest(tmp)
        tmp.unlink()


# ── Validation: exactly one tier 0 ─────────────────────────────────────

class TestExactlyOneTier0:
    def test_zero_tier_0_raises(self) -> None:
        yaml_text = textwrap.dedent("""\
            version: "2.0"
            last_updated: "2026-08-21T05:15:00Z"
            defaults:
              model: "writer/palmyra-x6"
              litellm_base_url: "http://localhost:4000"
              redis_url: "redis://localhost:6379/0"
            bots:
              admiral:
                tier: 1
                discord_token_env: "TOKEN_A"
                system_prompt_file: "prompts/a.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9001
                systemd_service_name: "svc-a"
              architect:
                tier: 1
                discord_token_env: "TOKEN_B"
                system_prompt_file: "prompts/b.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9002
                systemd_service_name: "svc-b"
            """)
        tmp = Path("/tmp/test_zero_tier0.yaml")
        tmp.write_text(yaml_text, encoding="utf-8")
        with pytest.raises(ValueError, match="tier 0"):
            load_manifest(tmp)
        tmp.unlink()

    def test_multiple_tier_0_raises(self) -> None:
        yaml_text = textwrap.dedent("""\
            version: "2.0"
            last_updated: "2026-08-21T05:15:00Z"
            defaults:
              model: "writer/palmyra-x6"
              litellm_base_url: "http://localhost:4000"
              redis_url: "redis://localhost:6379/0"
            bots:
              admiral:
                tier: 0
                discord_token_env: "TOKEN_A"
                system_prompt_file: "prompts/a.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9001
                systemd_service_name: "svc-a"
              architect:
                tier: 0
                discord_token_env: "TOKEN_B"
                system_prompt_file: "prompts/b.md"
                tools: [run_shell]
                health_check_interval: 30
                port: 9002
                systemd_service_name: "svc-b"
            """)
        tmp = Path("/tmp/test_multi_tier0.yaml")
        tmp.write_text(yaml_text, encoding="utf-8")
        with pytest.raises(ValueError, match="tier 0"):
            load_manifest(tmp)
        tmp.unlink()


# ── Bot config defaults ───────────────────────────────────────────────

class TestBotConfigDefaults:
    def test_bot_config_defaults(self) -> None:
        """model inherits from defaults when not specified (None)."""
        bot = BotConfig(
            tier=1,
            model=None,
            discord_token_env="TOKEN",
            system_prompt_file="prompts/test.md",
            tools=["run_shell"],
            health_check_interval=30,
            port=9999,
            systemd_service_name="svc-test",
        )
        assert bot.model is None
        assert bot.tier == 1
        assert bot.circuit_breaker_config is None

    def test_bot_config_with_model(self) -> None:
        bot = BotConfig(
            tier=2,
            model="custom/model",
            discord_token_env="TOKEN",
            system_prompt_file="prompts/test.md",
            tools=["read_file"],
            health_check_interval=45,
            port=8888,
            systemd_service_name="svc-custom",
        )
        assert bot.model == "custom/model"


# ── Circuit breaker defaults ──────────────────────────────────────────

class TestCircuitBreakerDefaults:
    def test_circuit_breaker_defaults(self) -> None:
        cb = CircuitBreakerConfig()
        assert cb.llm.failure_threshold == 5
        assert cb.llm.recovery_timeout == 30
        assert cb.llm.half_open_max_calls == 1
        assert cb.tools.failure_threshold == 3
        assert cb.tools.recovery_timeout == 60
        assert cb.tools.half_open_max_calls == 1

    def test_llm_breaker_custom(self) -> None:
        llm = LlmBreakerConfig(failure_threshold=10, recovery_timeout=60, half_open_max_calls=3)
        assert llm.failure_threshold == 10
        assert llm.recovery_timeout == 60
        assert llm.half_open_max_calls == 3

    def test_tool_breaker_custom(self) -> None:
        tools = ToolBreakerConfig(failure_threshold=7, recovery_timeout=120)
        assert tools.failure_threshold == 7
        assert tools.recovery_timeout == 120

    def test_llm_breaker_min_values(self) -> None:
        with pytest.raises(Exception):
            LlmBreakerConfig(failure_threshold=0)

    def test_tool_breaker_min_values(self) -> None:
        with pytest.raises(Exception):
            ToolBreakerConfig(recovery_timeout=0)


# ── Invalid manifest ──────────────────────────────────────────────────

class TestInvalidManifest:
    def test_invalid_manifest_raises(self) -> None:
        malformed_yaml = textwrap.dedent("""\
            version: "2.0"
            last_updated: "2026-08-21T05:15:00Z"
            defaults:
              model: "writer/palmyra-x6"
              litellm_base_url: "http://localhost:4000"
              redis_url: "redis://localhost:6379/0"
            bots:
              admiral:
                tier: 0
                # missing required fields
            """)
        tmp = Path("/tmp/test_invalid.yaml")
        tmp.write_text(malformed_yaml, encoding="utf-8")
        with pytest.raises(ValueError):
            load_manifest(tmp)
        tmp.unlink()

    def test_malformed_yaml_raises(self) -> None:
        bad_yaml = "version: 2.0\n  \tbad: [unterminated"
        tmp = Path("/tmp/test_bad_yaml.yaml")
        tmp.write_text(bad_yaml, encoding="utf-8")
        with pytest.raises(ValueError):
            load_manifest(tmp)
        tmp.unlink()

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_manifest("/tmp/nonexistent_manifest.yaml")


# ── Schema model defaults ─────────────────────────────────────────────

class TestSchemaDefaults:
    def test_defaults_model(self) -> None:
        d = Defaults()
        assert d.model == "writer/palmyra-x6"
        assert d.litellm_base_url == "http://localhost:4000"
        assert d.redis_url == "redis://localhost:6379/0"

    def test_nexus_bus_defaults(self) -> None:
        bus = NexusBusConfig()
        assert bus.type == "redis_streams"
        assert bus.stream_prefix == "nexus"
        assert bus.consumer_group == "nexus-fleet"
        assert bus.consumer_name_prefix == "nexus-consumer"
        assert bus.event_namespaces == []
        assert bus.max_stream_length == 10000
        assert bus.block_ms == 5000

    def test_self_healing_defaults(self) -> None:
        sh = SelfHealingConfig()
        assert sh.circuit_breakers.llm.failure_threshold == 5
        assert sh.health_monitor.enabled is True
        assert sh.semantic_breaker.enabled is True
        assert sh.crash_loop_detector.enabled is True
        assert sh.checkpoint.enabled is True
        assert sh.supervisor.enabled is True
        assert sh.recovery.escalation_target == "admiral"

    def test_updates_defaults(self) -> None:
        upd = UpdatesConfig()
        assert upd.canary_bot == "cartographer"
        assert upd.deployment_strategy == "phased"
        assert upd.rollout_order == []
        assert upd.health_gate.wait_seconds == 60
        assert upd.health_gate.rollback_on_failure is True
        assert upd.rollback.automatic is True
        assert upd.rollback.max_retries == 2
