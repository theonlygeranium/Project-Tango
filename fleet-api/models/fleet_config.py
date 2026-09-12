from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .bot_config import BotConfig


class FleetProtocol(BaseModel):
    max_chain_depth: int = 3
    delegation_timeout: int = 300
    edit_interval: float = 1.2
    first_send_threshold: int = 30
    max_length: int = 2000


class ConversationConfig(BaseModel):
    response_lock_timeout: int = 30
    answered_ttl: int = 3600
    message_retention: int = 50
    redis_message_ttl: int = 86400
    heartbeat_ttl: int = 60


class ContextBuilderConfig(BaseModel):
    max_context_file_chars: int = 8000
    max_total_context_chars: int = 20000
    max_project_prompt_chars: int = 4000


class SchedulerConfig(BaseModel):
    health_check_interval: int = 300
    service_check_interval: int = 120
    disk_alert_interval: int = 600
    memory_decay_interval: int = 3600
    disk_warning_threshold: int = 80
    disk_critical_threshold: int = 90
    mem_warning_threshold: int = 85
    cpu_warning_threshold: int = 90
    alert_dedup_cooldown: int = 1800
    service_recovered_cooldown: int = 600
    monitored_services: list[str] = Field(default_factory=list)


class MemoryStats(BaseModel):
    memories: int = 0
    entities: int = 0
    facts: int = 0


class FleetConfig(BaseModel):
    version: int = 1
    last_modified: str
    modified_by: str = "operator"
    fleet_protocol: FleetProtocol = Field(default_factory=FleetProtocol)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    context_builder: ContextBuilderConfig = Field(default_factory=ContextBuilderConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    memory_stats: MemoryStats = Field(default_factory=MemoryStats)
    bots: dict[str, BotConfig] = Field(default_factory=dict)