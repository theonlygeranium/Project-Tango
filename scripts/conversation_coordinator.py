"""
Conversation Coordinator
========================
Manages multi-agent turn-taking, response coordination, and message tracking.
Uses Redis for distributed state and coordination locks.
"""

import asyncio
import json
import time
from typing import Optional, Dict, List, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta


@dataclass
class AgentMessage:
    """Represents a message in a multi-agent conversation."""
    message_id: int
    channel_id: int
    author_id: int
    author_name: str
    content: str
    timestamp: float
    is_bot: bool
    agent_name: Optional[str] = None  # For bot messages


@dataclass
class ResponseLock:
    """Lock held by an agent responding to a message."""
    message_id: int
    agent_name: str
    locked_at: float
    expires_at: float


class MultiAgentChannelManager:
    """
    Manages multi-agent channel registration and configuration.
    Can be backed by database or Redis.
    """
    
    def __init__(self, db_connection_string: Optional[str] = None):
        """
        Initialize the channel manager.
        
        Args:
            db_connection_string: Optional database connection for persistence
        """
        self._channels: Set[int] = set()
        self._db = db_connection_string
        
    def register_channel(self, channel_id: int, agents: List[str]):
        """Register a channel for multi-agent coordination."""
        self._channels.add(channel_id)
        # TODO: Persist to database if available
        
    def unregister_channel(self, channel_id: int):
        """Remove a channel from multi-agent coordination."""
        self._channels.discard(channel_id)
        
    def is_multi_agent_channel(self, channel_id: str | int) -> bool:
        """Check if a channel is registered for multi-agent mode."""
        channel_id = int(channel_id) if isinstance(channel_id, str) else channel_id
        return channel_id in self._channels
    
    def get_channel_agents(self, channel_id: int) -> List[str]:
        """Get list of agents enabled for a channel."""
        # TODO: Load from database
        # For now, return default fleet
        if channel_id in self._channels:
            return ["admiral", "architect", "quartermaster", "cartographer"]
        return []


class ConversationCoordinator:
    """
    Coordinates multi-agent conversations with turn-taking and response locks.
    Uses Redis for distributed coordination across bot instances.
    """
    
    def __init__(self, redis_client, agent_name: str):
        """
        Initialize the conversation coordinator.
        
        Args:
            redis_client: Redis client for distributed coordination (can be None for local-only)
            agent_name: Name of this agent (e.g., "architect")
        """
        self.redis = redis_client
        self.agent_name = agent_name
        self._local_messages: Dict[int, List[AgentMessage]] = {}  # channel_id -> messages
        self._local_locks: Dict[int, ResponseLock] = {}  # message_id -> lock
        self._last_heartbeat = time.time()
        self._cooldown_tracker: Dict[int, float] = {}  # channel_id -> last_response_time
        
    async def register_message(
        self,
        message_id: int,
        channel_id: int,
        author_id: int,
        author_name: str,
        content: str,
        is_bot: bool = False,
        agent_name: Optional[str] = None,
    ):
        """Register a message in the conversation history."""
        msg = AgentMessage(
            message_id=message_id,
            channel_id=channel_id,
            author_id=author_id,
            author_name=author_name,
            content=content,
            timestamp=time.time(),
            is_bot=is_bot,
            agent_name=agent_name,
        )
        
        # Store locally
        if channel_id not in self._local_messages:
            self._local_messages[channel_id] = []
        self._local_messages[channel_id].append(msg)
        
        # Keep only last 50 messages per channel
        if len(self._local_messages[channel_id]) > 50:
            self._local_messages[channel_id] = self._local_messages[channel_id][-50:]
        
        # Store in Redis if available
        if self.redis:
            await self._redis_store_message(msg)
    
    async def _redis_store_message(self, msg: AgentMessage):
        """Store message in Redis for cross-agent visibility."""
        try:
            key = f"multiagent:messages:{msg.channel_id}"
            value = json.dumps(asdict(msg))
            # Store with 24h TTL
            await self.redis.zadd(key, {value: msg.timestamp})
            await self.redis.expire(key, 86400)  # 24 hours
        except Exception as e:
            # Non-critical - continue without Redis
            pass
    
    async def acquire_response_lock(
        self,
        message_id: int,
        timeout_seconds: float = 30.0
    ) -> bool:
        """
        Try to acquire exclusive lock to respond to a message.
        
        Args:
            message_id: The message ID to lock
            timeout_seconds: How long the lock is valid
            
        Returns:
            True if lock acquired, False if another agent has it
        """
        now = time.time()
        expires = now + timeout_seconds
        
        # Check Redis first if available
        if self.redis:
            try:
                lock_key = f"multiagent:lock:{message_id}"
                # Try to set the lock atomically
                acquired = await self.redis.set(
                    lock_key,
                    self.agent_name,
                    ex=int(timeout_seconds),
                    nx=True  # Only set if not exists
                )
                return bool(acquired)
            except Exception as e:
                # Fall back to local lock
                pass
        
        # Local lock (single-instance fallback)
        if message_id in self._local_locks:
            lock = self._local_locks[message_id]
            # Check if expired
            if lock.expires_at < now:
                # Expired, can acquire
                self._local_locks[message_id] = ResponseLock(
                    message_id=message_id,
                    agent_name=self.agent_name,
                    locked_at=now,
                    expires_at=expires,
                )
                return True
            else:
                # Still locked by another agent
                return False
        else:
            # No lock exists, acquire it
            self._local_locks[message_id] = ResponseLock(
                message_id=message_id,
                agent_name=self.agent_name,
                locked_at=now,
                expires_at=expires,
            )
            return True
    
    async def release_response_lock(self, message_id: int):
        """Release the response lock for a message."""
        if self.redis:
            try:
                lock_key = f"multiagent:lock:{message_id}"
                # Only delete if we own it
                await self.redis.delete(lock_key)
            except Exception:
                pass
        
        # Clear local lock
        self._local_locks.pop(message_id, None)
    
    async def mark_message_answered(self, message_id: int):
        """Mark a message as answered so other agents don't respond."""
        if self.redis:
            try:
                answered_key = f"multiagent:answered:{message_id}"
                await self.redis.set(answered_key, self.agent_name, ex=3600)  # 1 hour TTL
            except Exception:
                pass
    
    async def is_message_answered(self, message_id: int) -> bool:
        """Check if a message has been answered by any agent."""
        if self.redis:
            try:
                answered_key = f"multiagent:answered:{message_id}"
                result = await self.redis.exists(answered_key)
                return bool(result)
            except Exception:
                pass
        return False
    
    def check_cooldown(self, channel_id: int, cooldown_seconds: float = 10.0) -> bool:
        """
        Check if agent is in cooldown period for a channel.
        
        Args:
            channel_id: The channel to check
            cooldown_seconds: Minimum seconds between responses
            
        Returns:
            True if cooldown satisfied (can respond), False if still in cooldown
        """
        now = time.time()
        last_response = self._cooldown_tracker.get(channel_id, 0)
        
        if now - last_response >= cooldown_seconds:
            return True
        return False
    
    def mark_responded(self, channel_id: int):
        """Mark that this agent has responded in a channel."""
        self._cooldown_tracker[channel_id] = time.time()
    
    async def get_recent_context(
        self,
        channel_id: int,
        limit: int = 10
    ) -> List[AgentMessage]:
        """Get recent messages for context."""
        # Try Redis first
        if self.redis:
            try:
                key = f"multiagent:messages:{channel_id}"
                # Get last N messages
                raw_messages = await self.redis.zrevrange(key, 0, limit - 1)
                messages = []
                for raw in raw_messages:
                    try:
                        data = json.loads(raw)
                        messages.append(AgentMessage(**data))
                    except Exception:
                        continue
                if messages:
                    return list(reversed(messages))  # Chronological order
            except Exception:
                pass
        
        # Fall back to local
        msgs = self._local_messages.get(channel_id, [])
        return msgs[-limit:] if msgs else []
    
    async def heartbeat(self):
        """Send heartbeat to indicate agent is alive."""
        self._last_heartbeat = time.time()
        
        if self.redis:
            try:
                heartbeat_key = f"multiagent:heartbeat:{self.agent_name}"
                await self.redis.set(heartbeat_key, int(self._last_heartbeat), ex=60)
            except Exception:
                pass
    
    async def is_agent_online(self, agent_name: str) -> bool:
        """Check if another agent is online."""
        if self.redis:
            try:
                heartbeat_key = f"multiagent:heartbeat:{agent_name}"
                result = await self.redis.exists(heartbeat_key)
                return bool(result)
            except Exception:
                pass
        
        # Assume online if we can't check
        return True
