"""
Multi-Agent Configuration
=========================
Defines agent profiles, expertise domains, and coordination settings.
"""

from dataclasses import dataclass
from typing import List, Dict
from enum import Enum


class AgentRole(Enum):
    """Agent role types in the fleet."""
    COORDINATOR = "coordinator"  # Admiral - coordinates and delegates
    DEVELOPER = "developer"      # Architect - code and infrastructure
    OPERATIONS = "operations"    # Quartermaster - services and deployment
    DOCUMENTATION = "documentation"  # Cartographer - knowledge management
    MEDICAL = "medical"          # Dr. Voss - health monitoring and diagnostics
    SCIENCE = "science"          # Dr. Cortex - AI research and optimization


@dataclass
class AgentProfile:
    """Profile defining an agent's capabilities and behavior."""
    name: str
    role: AgentRole
    expertise_keywords: List[str]
    response_threshold: float = 0.5  # Minimum score to respond
    urgent_threshold: float = 0.8    # Score for immediate response
    cooldown_seconds: int = 10       # Minimum time between responses
    
    
# Agent profiles for the Schubert fleet
AGENT_PROFILES: Dict[str, AgentProfile] = {
    "architect": AgentProfile(
        name="architect",
        role=AgentRole.DEVELOPER,
        expertise_keywords=[
            "code", "bug", "error", "patch", "deploy", "git", "commit",
            "architecture", "design", "debug", "fix", "develop", "build",
            "optimize", "refactor", "test", "ci", "cd", "function", "class",
            "method", "variable", "import", "python", "javascript", "typescript",
            "api", "endpoint", "database", "query", "schema", "migration",
            "lint", "format", "syntax", "compile", "runtime", "exception"
        ],
        response_threshold=0.5,
        urgent_threshold=0.8,
        cooldown_seconds=10,
    ),
    "admiral": AgentProfile(
        name="admiral",
        role=AgentRole.COORDINATOR,
        expertise_keywords=[
            "status", "help", "memory", "remember", "project", "session",
            "mcp", "tools", "fleet", "coordinate", "delegate", "overview",
            "summary", "context", "history", "what", "who", "when", "where"
        ],
        response_threshold=0.4,  # Lower threshold for coordinator
        urgent_threshold=0.7,
        cooldown_seconds=5,
    ),
    "quartermaster": AgentProfile(
        name="quartermaster",
        role=AgentRole.OPERATIONS,
        expertise_keywords=[
            "docker", "container", "service", "systemd", "restart",
            "infrastructure", "deployment", "caddy", "cloudflare", "tunnel",
            "dns", "network", "port", "process", "resource", "disk", "cpu",
            "memory", "load", "performance", "monitoring", "logs", "health"
        ],
        response_threshold=0.5,
        urgent_threshold=0.8,
        cooldown_seconds=10,
    ),
    "cartographer": AgentProfile(
        name="cartographer",
        role=AgentRole.DOCUMENTATION,
        expertise_keywords=[
            "documentation", "wiki", "outline", "document", "write",
            "report", "audit", "knowledge", "update log", "changelog",
            "describe", "explain", "summary", "overview", "notes", "record"
        ],
        response_threshold=0.5,
        urgent_threshold=0.8,
        cooldown_seconds=10,
    ),
        "dr_voss": AgentProfile(
            name="dr_voss",
            role=AgentRole.MEDICAL,
            expertise_keywords=[
                "health", "diagnostic", "check", "monitor", "issue", "problem",
                "warning", "alert", "failure", "down", "unhealthy", "error",
                "exception", "crash", "hang", "slow", "latency", "timeout",
                "medical", "doctor", "voss", "diagnosis", "symptom", "triage"
            ],
            response_threshold=0.5,
            urgent_threshold=0.8,
            cooldown_seconds=10,
        ),
        "proctor": AgentProfile(
            name="proctor",
            role=AgentRole.DOCUMENTATION,  # Observer role - doesn't actively respond
            expertise_keywords=[
                "performance", "optimization", "metrics", "analysis", "statistics",
                "response time", "latency", "error rate", "monitoring", "observer",
                "proctor", "delegate", "architect delegation", "bottleneck"
            ],
            response_threshold=0.9,  # Very high threshold - rarely responds in multi-agent
            urgent_threshold=0.95,
            cooldown_seconds=60,  # Longer cooldown - observer role
        ),
        "cortex": AgentProfile(
            name="cortex",
            role=AgentRole.SCIENCE,
            expertise_keywords=[
                "ai", "research", "optimization", "model", "benchmark", "prompt",
                "llm", "transformer", "rag", "embedding", "fine-tune", "training",
                "paper", "arxiv", "best practice", "latest", "trend", "improve",
                "performance", "efficiency", "cortex", "science", "recommend",
                "upgrade", "enhance", "analysis", "review", "evaluate", "compare"
            ],
            response_threshold=0.5,
            urgent_threshold=0.8,
            cooldown_seconds=10,
        ),
    }


def get_agent_profile(agent_name: str) -> AgentProfile:
    """Get the profile for an agent by name."""
    return AGENT_PROFILES.get(agent_name.lower())


# Multi-agent channel configuration
@dataclass
class ChannelConfig:
    """Configuration for a multi-agent enabled channel."""
    channel_id: int
    enabled_agents: List[str]
    coordinator_agent: str = "admiral"
    require_mention: bool = False
    max_concurrent_responses: int = 1
    

# Default channel configurations (can be overridden by database)
DEFAULT_CHANNEL_CONFIGS: Dict[int, ChannelConfig] = {}


def register_channel(
    channel_id: int,
    enabled_agents: List[str],
    coordinator: str = "admiral",
    require_mention: bool = False,
) -> ChannelConfig:
    """Register a channel for multi-agent coordination."""
    config = ChannelConfig(
        channel_id=channel_id,
        enabled_agents=enabled_agents,
        coordinator_agent=coordinator,
        require_mention=require_mention,
    )
    DEFAULT_CHANNEL_CONFIGS[channel_id] = config
    return config


def get_channel_config(channel_id: int) -> ChannelConfig:
    """Get configuration for a channel."""
    return DEFAULT_CHANNEL_CONFIGS.get(channel_id)


def is_multi_agent_channel(channel_id: int) -> bool:
    """Check if a channel has multi-agent coordination enabled."""
    return channel_id in DEFAULT_CHANNEL_CONFIGS
