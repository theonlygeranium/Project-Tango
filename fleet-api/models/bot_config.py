from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class LlmConfig(BaseModel):
    model: str
    coding_model: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 3072
    llm_timeout: int = 120
    max_iterations: int = 10
    agent_timeout: int = 300
    tool_output_limit: int = 4000
    shell_timeout: int = 120
    session_window: Any = "per-project"
    rate_limit_per_min: Optional[int] = None


class PromptConfig(BaseModel):
    system_prompt: str = ""
    voice_prompt_addition: bool = False
    coding_prompt_addition: bool = False
    poll_prompt_addition: bool = False
    meetscribe_prompt_addition: bool = False


class ToolDef(BaseModel):
    id: str
    name: str
    source: str
    enabled: bool = True


class PatternRule(BaseModel):
    pattern: str
    reason: str
    enabled: bool = True
    danger: bool = False


class BlockedPath(BaseModel):
    path: str
    enabled: bool = True


class GuardrailsConfig(BaseModel):
    hard_blocked_patterns: list[PatternRule] = Field(default_factory=list)
    confirm_patterns: list[PatternRule] = Field(default_factory=list)
    blocked_write_paths: list[BlockedPath] = Field(default_factory=list)
    critical_services: list[str] = Field(default_factory=list)
    never_touch_services: list[str] = Field(default_factory=list)
    restart_confirm_timeout: Optional[int] = None


class MemoryConfig(BaseModel):
    cosine_threshold: float = 0.3
    max_memory_injection_tokens: int = 1200
    decay_rate: str = "1%/day"
    decay_floor: float = 0.1
    max_recall_results: int = 5
    max_search_results: int = 10
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    llm_entity_extraction: bool = True
    memory_storage_threshold: int = 100


class VoiceConfig(BaseModel):
    enabled: bool = True
    stt_engine: str = "Deepgram nova-3"
    tts_engine: str = "ElevenLabs eleven_flash_v2_5"
    voice_id: str = ""
    vad_speech_rms_threshold: int = 100
    vad_silence_frames_limit: int = 15
    vad_min_speech_frames: int = 10
    tts_stability: float = 0.5
    tts_similarity_boost: float = 0.75
    tts_text_truncation: int = 500
    voice_response_truncation: int = 1900
    stt_timeout: int = 30
    tts_timeout: int = 30
    min_pcm_length: int = 1000


class McpServerConfig(BaseModel):
    id: str
    name: str
    url: str
    enabled: bool = True
    timeout: int = 90


class McpConfig(BaseModel):
    servers: list[McpServerConfig] = Field(default_factory=list)
    request_timeout: int = 90
    tool_cache_ttl: int = 1800
    tool_cache_refresh_on_error: bool = True
    per_project_tool_filtering: bool = True


class MultiAgentConfig(BaseModel):
    response_threshold: float = 0.5
    urgent_threshold: float = 0.8
    cooldown_seconds: int = 10
    fleet_delegation_role: str = "receive_only"


class SelfHealingConfig(BaseModel):
    health_check_interval: int = 300
    escalation_cooldown: int = 300
    max_remediation_retries: int = 3
    intensive_monitor_interval: int = 10
    intensive_monitor_duration: int = 300
    error_threshold: int = 3


class SelfImprovementConfig(BaseModel):
    enabled: bool = True
    assessment_interval: int = 21600
    max_updates_per_day: int = 3
    max_file_size: int = 204800
    max_changes_per_update: int = 5
    rollback_wait_time: int = 30
    reversal_lock_duration: int = 86400


class BotMeta(BaseModel):
    id: str
    name: str
    role: str
    roleLabel: str
    avatar: str
    status: str = "online"
    scriptLines: int = 0
    featureTags: list[str] = Field(default_factory=list)


class IdentityConfig(BaseModel):
    name: str
    discord_id: str
    channel_id: str
    service: str
    script: str
    tier: str


class BotConfig(BaseModel):
    meta: BotMeta
    llm: LlmConfig
    prompt: PromptConfig
    tools: list[ToolDef] = Field(default_factory=list)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    scheduler_enabled: bool = False
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    voice: Optional[VoiceConfig] = None
    mcp: McpConfig = Field(default_factory=McpConfig)
    multi_agent: MultiAgentConfig = Field(default_factory=MultiAgentConfig)
    self_healing: Optional[SelfHealingConfig] = None
    self_improvement: Optional[SelfImprovementConfig] = None
    identity: IdentityConfig