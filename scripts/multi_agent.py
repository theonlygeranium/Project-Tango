"""
Multi-Agent Conversation Support Framework
===========================================

Enables multiple Discord bots to participate in shared channels with coordinated
turn-taking, context sharing, and intelligent routing.

Architecture:
- Multi-agent channels are registered with participating agents
- Message routing uses @mentions, keywords, and expertise matching
- Optional coordinator (usually Admiral) manages turn-taking
- Shared context prevents duplicate responses
- Graceful handling of offline agents

Usage:
    from multi_agent import MultiAgentManager, is_multi_agent_channel
    
    manager = MultiAgentManager(agent_name="architect")
    
    @bot.event
    async def on_message(message):
        if is_multi_agent_channel(message.channel.id):
            should_respond = await manager.should_respond(message)
            if not should_respond:
                return
        # Process message normally...
"""

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Set
from enum import Enum


class ParticipationMode(Enum):
    """Modes for multi-agent participation."""
    COLLABORATIVE = "collaborative"  # All agents can respond when relevant
    ROUND_ROBIN = "round_robin"      # Agents take turns
    COORDINATOR = "coordinator"       # One agent manages turn-taking


@dataclass
class MultiAgentChannel:
    """Configuration for a multi-agent channel."""
    channel_id: int
    agents: List[str]  # List of agent names: admiral, architect, quartermaster, etc.
    mode: ParticipationMode
    coordinator: Optional[str] = None  # Agent name that coordinates (usually "admiral")
    require_mention: bool = False  # If True, agents only respond when mentioned
    

# Multi-agent channel registry
MULTI_AGENT_CHANNELS: Dict[int, MultiAgentChannel] = {}


def register_multi_agent_channels():
    """Load multi-agent channel configuration from environment or config file."""
    global MULTI_AGENT_CHANNELS
    
    # Try to load from JSON config file first
    config_path = "/opt/Project-Tango/data/multi_agent_channels.json"
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
                for channel_id_str, channel_config in config.items():
                    channel_id = int(channel_id_str)
                    MULTI_AGENT_CHANNELS[channel_id] = MultiAgentChannel(
                        channel_id=channel_id,
                        agents=channel_config.get("agents", []),
                        mode=ParticipationMode(channel_config.get("mode", "collaborative")),
                        coordinator=channel_config.get("coordinator"),
                        require_mention=channel_config.get("require_mention", False),
                    )
        except Exception as e:
            print(f"Error loading multi-agent config: {e}")
    
    # Fallback to hardcoded config for Phase 1 MVP
    # This will be replaced by database-driven config in Phase 2
    senior_staff_channel = os.environ.get("SENIOR_STAFF_CHANNEL_ID")
    if senior_staff_channel and not MULTI_AGENT_CHANNELS:
        MULTI_AGENT_CHANNELS[int(senior_staff_channel)] = MultiAgentChannel(
            channel_id=int(senior_staff_channel),
            agents=["admiral", "architect", "quartermaster", "cartographer", "dr_voss", "cortex"],
            mode=ParticipationMode.COLLABORATIVE,
            coordinator="admiral",
            require_mention=False,
        )


def is_multi_agent_channel(channel_id: int) -> bool:
    """Check if a channel is registered for multi-agent conversations."""
    return channel_id in MULTI_AGENT_CHANNELS


def get_channel_config(channel_id: int) -> Optional[MultiAgentChannel]:
    """Get the configuration for a multi-agent channel."""
    return MULTI_AGENT_CHANNELS.get(channel_id)


class MultiAgentManager:
    """Manages multi-agent conversation participation for a single agent."""
    
    def __init__(self, agent_name: str):
        """
        Initialize the multi-agent manager.
        
        Args:
            agent_name: Name of this agent (admiral, architect, quartermaster, etc.)
        """
        self.agent_name = agent_name.lower()
        self.last_response_time: Dict[int, float] = {}  # channel_id -> timestamp
        self.response_backoff_seconds = 10  # Minimum seconds between responses
        
    async def should_respond(
        self,
        message,
        bot_user_id: int,
        admin_user_id: int,
    ) -> bool:
        """
        Determine if this agent should respond to a message in a multi-agent channel.
        
        Args:
            message: Discord message object
            bot_user_id: This bot's Discord user ID
            admin_user_id: Admin user ID
            
        Returns:
            True if this agent should respond, False otherwise
        """
        # Ignore own messages
        if message.author.id == bot_user_id:
            return False
        
        channel_id = message.channel.id
        config = get_channel_config(channel_id)
        
        if not config:
            # Not a multi-agent channel, use normal logic
            return True
        
        # Check if this agent is registered for this channel
        if self.agent_name not in config.agents:
            return False
        
        content = message.content.lower()
        
        # Check if message is addressed to a DIFFERENT agent
        # If so, don't respond (unless explicitly @mentioned)
        if self._is_addressed_to_other(content):
            # Only respond if directly @mentioned
            if f"<@{bot_user_id}>" in message.content or f"<@!{bot_user_id}>" in message.content:
                return True
            return False
        
        # Priority 1: Direct @mention always triggers response
        if f"<@{bot_user_id}>" in message.content or f"<@!{bot_user_id}>" in message.content:
            return True
        
        # Priority 2: Message from admin (not another bot)
        if message.author.id == admin_user_id and not message.author.bot:
            # Check if we're specifically addressed
            if self._is_addressed(content):
                return True
            # In coordinator mode, coordinator always responds to admin
            if config.coordinator == self.agent_name:
                return True
            # Check expertise match
            if self._matches_expertise(content):
                return True
            # In require_mention mode, don't respond without mention
            if config.require_mention:
                return False
            return True  # Respond to admin by default
        
        # Priority 3: Message from coordinator (delegation/hand-off)
        if config.coordinator and message.author.bot:
            # Check for delegation phrases like "Architect, please..."
            if self._is_delegated_to(content):
                return True
        
        # Priority 4: Check backoff timer to prevent spam
        now = time.time()
        last_response = self.last_response_time.get(channel_id, 0)
        if now - last_response < self.response_backoff_seconds:
            return False
        
        # Priority 5: Expertise-based routing
        if self._matches_expertise(content):
            return True
        
        # Default: don't respond in multi-agent channels unless explicitly triggered
        return False
    
    def mark_responded(self, channel_id: int):
        """Mark that this agent has responded in the channel."""
        self.last_response_time[channel_id] = time.time()
    
    def _is_addressed(self, content: str) -> bool:
        """Check if the message is addressed to this agent."""
        # Patterns like "architect:" or "architect," or "hey architect"
        patterns = [
            f"{self.agent_name}:",
            f"{self.agent_name},",
            f"hey {self.agent_name}",
            f"hi {self.agent_name}",
            f"@{self.agent_name}",
        ]
        return any(pattern in content for pattern in patterns)
    
    def _is_addressed_to_other(self, content: str) -> bool:
        """Check if the message is addressed to a DIFFERENT agent."""
        all_agent_names = [
            "admiral", "admiral schubert", "schubert",
            "architect", "the architect",
            "quartermaster", "the quartermaster",
            "cartographer", "the cartographer",
            "dr_voss", "dr voss", "dr. voss", "voss",
            "proctor", "the proctor",
            "cortex", "dr. cortex", "dr cortex",
        ]
        # Remove this agent's own names
        own_names = {self.agent_name}
        if self.agent_name == "admiral":
            own_names = {"admiral", "admiral schubert", "schubert"}
        elif self.agent_name == "architect":
            own_names = {"architect", "the architect"}
        elif self.agent_name == "cortex":
            own_names = {"cortex", "dr. cortex", "dr cortex"}
        elif self.agent_name == "dr_voss":
            own_names = {"dr_voss", "dr voss", "dr. voss", "voss"}
        elif self.agent_name == "quartermaster":
            own_names = {"quartermaster", "the quartermaster"}
        elif self.agent_name == "cartographer":
            own_names = {"cartographer", "the cartographer"}
        elif self.agent_name == "proctor":
            own_names = {"proctor", "the proctor"}
        
        other_agents = [a for a in all_agent_names if a not in own_names]
        
        for other_agent in other_agents:
            if content.startswith(f"{other_agent}:") or content.startswith(f"{other_agent},"):
                return True
        return False
    
    def _is_delegated_to(self, content: str) -> bool:
        """Check if the coordinator is delegating to this agent."""
        # Patterns like "architect, please" or "architect: handle this"
        patterns = [
            f"{self.agent_name}, please",
            f"{self.agent_name}: ",
            f"{self.agent_name} can you",
            f"{self.agent_name} please",
            f"delegating to {self.agent_name}",
            f"handing off to {self.agent_name}",
        ]
        return any(pattern in content for pattern in patterns)
    
    def _matches_expertise(self, content: str) -> bool:
        """Check if the message content matches this agent's expertise."""
        expertise_keywords = {
            "admiral": [
                "status", "help", "memory", "remember", "project", "session",
                "mcp", "tools", "fleet", "coordinate", "delegate"
            ],
            "architect": [
                "code", "bug", "error", "patch", "deploy", "git", "commit",
                "architecture", "design", "debug", "fix", "develop", "build",
                "optimize", "refactor", "test", "ci", "cd"
            ],
            "quartermaster": [
                "docker", "container", "service", "systemd", "restart",
                "infrastructure", "deployment", "caddy", "cloudflare", "tunnel",
                "dns", "network", "port", "process", "resource", "disk", "cpu"
            ],
            "cartographer": [
                "documentation", "wiki", "outline", "document", "write",
                "report", "audit", "knowledge", "update log", "changelog",
                "describe", "explain", "summary", "overview"
            ],
            "dr_voss": [
                "health", "diagnostic", "check", "monitor", "issue", "problem",
                "warning", "alert", "failure", "down", "unhealthy", "error",
                "medical", "doctor", "voss", "diagnosis"
            ],
        }
        
        agent_keywords = expertise_keywords.get(self.agent_name, [])
        return any(keyword in content for keyword in agent_keywords)


class SharedContext:
    """Manages shared conversation context for multi-agent channels."""
    
    def __init__(self, redis_client=None, postgres_conn=None):
        """
        Initialize shared context manager.
        
        Args:
            redis_client: Optional Redis client for fast context caching
            postgres_conn: Optional Postgres connection for persistent storage
        """
        self.redis = redis_client
        self.postgres = postgres_conn
        self._local_cache: Dict[int, List[Dict]] = {}  # channel_id -> messages
        
    def add_message(
        self,
        channel_id: int,
        message_id: int,
        author_name: str,
        content: str,
        timestamp: float,
        is_bot: bool = False,
    ):
        """Add a message to the shared context."""
        msg_data = {
            "message_id": message_id,
            "author_name": author_name,
            "content": content,
            "timestamp": timestamp,
            "is_bot": is_bot,
        }
        
        # Add to local cache
        if channel_id not in self._local_cache:
            self._local_cache[channel_id] = []
        self._local_cache[channel_id].append(msg_data)
        
        # Keep only last 50 messages per channel
        if len(self._local_cache[channel_id]) > 50:
            self._local_cache[channel_id] = self._local_cache[channel_id][-50:]
        
        # TODO: Add Redis/Postgres persistence in Phase 2
        
    def get_recent_context(self, channel_id: int, limit: int = 10) -> List[Dict]:
        """Get recent messages from the channel for context."""
        messages = self._local_cache.get(channel_id, [])
        return messages[-limit:] if messages else []
    
    def format_context_for_llm(self, channel_id: int, limit: int = 10) -> str:
        """Format recent context as a string for LLM injection."""
        messages = self.get_recent_context(channel_id, limit)
        if not messages:
            return ""
        
        lines = ["## Recent conversation context:"]
        for msg in messages:
            author = msg["author_name"]
            content = msg["content"][:500]  # Truncate long messages
            lines.append(f"- **{author}**: {content}")
        
        return "\n".join(lines)


# Global shared context instance
_shared_context: Optional[SharedContext] = None


def get_shared_context() -> SharedContext:
    """Get or create the global shared context instance."""
    global _shared_context
    if _shared_context is None:
        _shared_context = SharedContext()
    return _shared_context


# Initialize on import
register_multi_agent_channels()
