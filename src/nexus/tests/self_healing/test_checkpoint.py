"""Tests for CheckpointManager and RedisCheckpointStorage."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from nexus.self_healing.checkpoint import (
    CheckpointManager,
    ConversationState,
    RedisCheckpointStorage,
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
def sample_state():
    return ConversationState(
        bot_id="test-bot",
        channel_id=123456,
        messages=[{"role": "user", "content": "hello"}],
        last_tool_call={"name": "search", "args": {"q": "test"}},
        agent_loop_iteration=3,
        timestamp="2026-08-20T10:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# RedisCheckpointStorage tests
# ---------------------------------------------------------------------------

class TestRedisCheckpointStorage:
    """Tests for RedisCheckpointStorage."""

    async def test_save_and_load_round_trip(self, redis_client, sample_state) -> None:
        storage = RedisCheckpointStorage(redis_client)
        key = "test-bot:123456:2026-08-20T10:00:00+00:00"

        await storage.save(key, sample_state)
        loaded = await storage.load(key)

        assert loaded is not None
        assert loaded.bot_id == sample_state.bot_id
        assert loaded.channel_id == sample_state.channel_id
        assert loaded.messages == sample_state.messages
        assert loaded.last_tool_call == sample_state.last_tool_call
        assert loaded.agent_loop_iteration == sample_state.agent_loop_iteration
        assert loaded.timestamp == sample_state.timestamp

    async def test_load_returns_none_for_missing_key(self, redis_client) -> None:
        storage = RedisCheckpointStorage(redis_client)
        result = await storage.load("nonexistent")
        assert result is None

    async def test_get_latest_key(self, redis_client, sample_state) -> None:
        storage = RedisCheckpointStorage(redis_client)

        # Save two checkpoints with different timestamps
        state1 = ConversationState(
            bot_id="test-bot",
            channel_id=123,
            messages=[],
            last_tool_call=None,
            agent_loop_iteration=1,
            timestamp="2026-08-20T10:00:00+00:00",
        )
        state2 = ConversationState(
            bot_id="test-bot",
            channel_id=123,
            messages=[],
            last_tool_call=None,
            agent_loop_iteration=2,
            timestamp="2026-08-20T11:00:00+00:00",
        )

        await storage.save("key1", state1)
        await storage.save("key2", state2)

        latest = await storage.get_latest_key("test-bot")
        assert latest == "key2"


# ---------------------------------------------------------------------------
# CheckpointManager tests
# ---------------------------------------------------------------------------

class TestCheckpointManager:
    """Tests for CheckpointManager."""

    async def test_save_and_restore(self, redis_client, sample_state) -> None:
        manager = CheckpointManager("test-bot", redis_client=redis_client)

        key = await manager.save(sample_state)
        assert key

        restored = await manager.restore(key)
        assert restored.bot_id == sample_state.bot_id
        assert restored.channel_id == sample_state.channel_id
        assert restored.messages == sample_state.messages

    async def test_get_latest_returns_none_when_empty(self, redis_client) -> None:
        manager = CheckpointManager("test-bot", redis_client=redis_client)

        result = await manager.get_latest()
        assert result is None

    async def test_get_latest_returns_most_recent(self, redis_client) -> None:
        manager = CheckpointManager("test-bot", redis_client=redis_client)

        state1 = ConversationState(
            bot_id="test-bot",
            channel_id=123,
            messages=[],
            last_tool_call=None,
            agent_loop_iteration=1,
            timestamp="2026-08-20T10:00:00+00:00",
        )
        state2 = ConversationState(
            bot_id="test-bot",
            channel_id=123,
            messages=[],
            last_tool_call=None,
            agent_loop_iteration=2,
            timestamp="2026-08-20T11:00:00+00:00",
        )

        await manager.save(state1)
        await manager.save(state2)

        latest = await manager.get_latest()
        assert latest is not None
        assert latest.agent_loop_iteration == 2

    async def test_restore_raises_keyerror_for_missing(self, redis_client) -> None:
        manager = CheckpointManager("test-bot", redis_client=redis_client)

        with pytest.raises(KeyError, match="Checkpoint not found"):
            await manager.restore("nonexistent-key")

    async def test_redis_storage_required(self) -> None:
        with pytest.raises(ValueError, match="redis_client is required"):
            CheckpointManager("test-bot", storage="redis")
