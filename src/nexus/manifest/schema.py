"""Pydantic v2 models for the Nexus Fleet Manifest schema."""

from __future__ import annotations

import logging
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


# ── Defaults ──────────────────────────────────────────────────────────

class Defaults(BaseModel):
    model: str = "writer/palmyra-x6"
    litellm_base_url: str = "http://localhost:4000"
    redis_url: str = "redis://localhost:6379/0"


# ── Circuit Breaker ───────────────────────────────────────────────────

class LlmBreakerConfig(BaseModel):
    failure_threshold: int = Field(default=5, ge=1)
    recovery_timeout: int = Field(default=30, ge=1)
    half_open_max_calls: int = Field(default=1, ge=1)


class ToolBreakerConfig(BaseModel):
    failure_threshold: int = Field(default=3, ge=1)
    recovery_timeout: int = Field(default=60, ge=1)
    half_open_max_calls: int = Field(default=1, ge=1)


class CircuitBreakerConfig(BaseModel):
    llm: LlmBreakerConfig = Field(default_factory=LlmBreakerConfig)
    tools: ToolBreakerConfig = Field(default_factory=ToolBreakerConfig)


# ── Self-Healing ──────────────────────────────────────────────────────

class HealthMonitorConfig(BaseModel):
    enabled: bool = True
    report_interval: int = 30
    stale_threshold: int = 90


class SemanticBreakerConfig(BaseModel):
    enabled: bool = True
    window: int = 3
    repeat_threshold: int = 3


class CrashLoopDetectorConfig(BaseModel):
    enabled: bool = True
    restart_window: int = 300
    max_restarts: int = 5
    action: str = "stop"


class CheckpointConfig(BaseModel):
    enabled: bool = True
    backend: str = "redis"
    key_prefix: str = "nexus:checkpoint"
    save_on: str = "tool_success"


class SupervisorConfig(BaseModel):
    enabled: bool = True
    poll_interval: int = 10
    watchdog_timeout: int = 120


class RecoveryConfig(BaseModel):
    retry_attempts: int = 3
    backoff_base: int = 1
    backoff_max: int = 30
    jitter_max: int = 2
    escalation_target: str = "admiral"


class SelfHealingConfig(BaseModel):
    circuit_breakers: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    health_monitor: HealthMonitorConfig = Field(default_factory=HealthMonitorConfig)
    semantic_breaker: SemanticBreakerConfig = Field(default_factory=SemanticBreakerConfig)
    crash_loop_detector: CrashLoopDetectorConfig = Field(default_factory=CrashLoopDetectorConfig)
    checkpoint: CheckpointConfig = Field(default_factory=CheckpointConfig)
    supervisor: SupervisorConfig = Field(default_factory=SupervisorConfig)
    recovery: RecoveryConfig = Field(default_factory=RecoveryConfig)


# ── Nexus Bus ─────────────────────────────────────────────────────────

class NexusBusConfig(BaseModel):
    type: str = "redis_streams"
    stream_prefix: str = "nexus"
    consumer_group: str = "nexus-fleet"
    consumer_name_prefix: str = "nexus-consumer"
    event_namespaces: list[str] = Field(default_factory=list)
    max_stream_length: int = 10000
    block_ms: int = 5000


# ── Updates ───────────────────────────────────────────────────────────

class HealthGateConfig(BaseModel):
    wait_seconds: int = 60
    checks: list[str] = Field(default_factory=list)
    rollback_on_failure: bool = True


class RollbackConfig(BaseModel):
    automatic: bool = True
    max_retries: int = 2
    alert_channels: list[str] = Field(default_factory=list)


class UpdatesConfig(BaseModel):
    canary_bot: str = "cartographer"
    deployment_strategy: str = "phased"
    rollout_order: list[str] = Field(default_factory=list)
    health_gate: HealthGateConfig = Field(default_factory=HealthGateConfig)
    rollback: RollbackConfig = Field(default_factory=RollbackConfig)


# ── Bot Config ────────────────────────────────────────────────────────

class BotConfig(BaseModel):
    tier: int
    model: str | None = None
    discord_token_env: str
    system_prompt_file: str
    tools: list[str]
    health_check_interval: int
    port: int
    systemd_service_name: str
    circuit_breaker_config: dict | None = None


# ── Fleet Manifest ────────────────────────────────────────────────────

class FleetManifest(BaseModel):
    version: str
    last_updated: str
    defaults: Defaults
    bots: dict[str, BotConfig]
    nexus_bus: NexusBusConfig = Field(default_factory=NexusBusConfig)
    self_healing: SelfHealingConfig = Field(default_factory=SelfHealingConfig)
    updates: UpdatesConfig = Field(default_factory=UpdatesConfig)
    routing_table: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_fleet_constraints(self) -> FleetManifest:
        # All ports must be unique
        ports = [bot.port for bot in self.bots.values()]
        if len(ports) != len(set(ports)):
            seen: set[int] = set()
            dupes: list[int] = []
            for p in ports:
                if p in seen:
                    dupes.append(p)
                seen.add(p)
            raise ValueError(f"Duplicate port(s) found across bots: {dupes}")

        # Exactly one bot must have tier 0 (the Admiral)
        tier_0_bots = [name for name, bot in self.bots.items() if bot.tier == 0]
        if len(tier_0_bots) != 1:
            raise ValueError(
                f"Exactly one bot must have tier 0 (the Admiral), "
                f"found {len(tier_0_bots)}: {tier_0_bots}"
            )

        # All systemd_service_name values must be unique
        service_names = [bot.systemd_service_name for bot in self.bots.values()]
        if len(service_names) != len(set(service_names)):
            seen_svc: set[str] = set()
            dupes_svc: list[str] = []
            for s in service_names:
                if s in seen_svc:
                    dupes_svc.append(s)
                seen_svc.add(s)
            raise ValueError(
                f"Duplicate systemd_service_name(s) found across bots: {dupes_svc}"
            )

        return self
