"""Checkpoint — saves and restores conversation state via Redis.

Allows bots to snapshot their conversation state so that after a crash or
restart they can resume from the last known good state instead of starting
from scratch.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConversationState:
    """Snapshot of a bot's conversation state at a point in time."""

    bot_id: str
    channel_id: int
    messages: list[dict[str, Any]]
    last_tool_call: dict[str, Any] | None
    agent_loop_iteration: int
    timestamp: str


class CheckpointStorage:
    """Abstract storage interface for conversation checkpoints."""

    async def save(self, key: str, state: ConversationState) -> None:
        raise NotImplementedError

    async def load(self, key: str) -> ConversationState | None:
        raise NotImplementedError

    async def get_latest_key(self, bot_id: str) -> str | None:
        raise NotImplementedError


class RedisCheckpointStorage(CheckpointStorage):
    """Redis-backed checkpoint storage."""

    def __init__(
        self, redis_client: Any, key_prefix: str = "nexus:checkpoint"
    ) -> None:
        self._redis = redis_client
        self._key_prefix = key_prefix

    async def save(self, key: str, state: ConversationState) -> None:
        full_key = f"{self._key_prefix}:{key}"
        data = json.dumps(asdict(state))
        await self._redis.set(full_key, data)
        # Track the key in a sorted set by timestamp for get_latest_key
        await self._redis.zadd(
            f"{self._key_prefix}:index:{state.bot_id}",
            {key: datetime.fromisoformat(state.timestamp).timestamp()},
        )
        logger.debug("Checkpoint saved: %s", full_key)

    async def load(self, key: str) -> ConversationState | None:
        full_key = f"{self._key_prefix}:{key}"
        data = await self._redis.get(full_key)
        if data is None:
            return None
        return self._deserialize(data)

    async def get_latest_key(self, bot_id: str) -> str | None:
        index_key = f"{self._key_prefix}:index:{bot_id}"
        result = await self._redis.zrevrange(index_key, 0, 0)
        if not result:
            return None
        # zrevrange returns list of (member, score) or just member depending on withscores
        if isinstance(result[0], (list, tuple)):
            return result[0][0]
        return result[0]

    def _deserialize(self, data: str | bytes) -> ConversationState:
        if isinstance(data, bytes):
            data = data.decode()
        d = json.loads(data)
        return ConversationState(**d)


class CheckpointManager:
    """Manages conversation state checkpoints for a single bot."""

    def __init__(
        self,
        bot_id: str,
        storage: str = "redis",
        redis_client: Any | None = None,
        key_prefix: str = "nexus:checkpoint",
    ) -> None:
        self._bot_id = bot_id
        self._key_prefix = key_prefix

        if storage == "redis":
            if redis_client is None:
                raise ValueError("redis_client is required for redis storage")
            self._storage: CheckpointStorage = RedisCheckpointStorage(
                redis_client, key_prefix
            )
        else:
            raise ValueError(f"Unknown storage type: {storage}")

    async def save(self, state: ConversationState) -> str:
        """Save a conversation state checkpoint. Returns the checkpoint key."""
        key = f"{state.bot_id}:{state.channel_id}:{state.timestamp}"
        await self._storage.save(key, state)
        logger.info("Checkpoint saved for bot '%s' (key=%s)", state.bot_id, key)
        return key

    async def get_latest(self) -> ConversationState | None:
        """Get the most recent checkpoint for this bot, or None if no checkpoints exist."""
        key = await self._storage.get_latest_key(self._bot_id)
        if key is None:
            return None
        return await self._storage.load(key)

    async def restore(self, key: str) -> ConversationState:
        """Restore a conversation state by key. Raises KeyError if not found."""
        state = await self._storage.load(key)
        if state is None:
            raise KeyError(f"Checkpoint not found: {key}")
        logger.info("Checkpoint restored for bot '%s' (key=%s)", state.bot_id, key)
        return state
