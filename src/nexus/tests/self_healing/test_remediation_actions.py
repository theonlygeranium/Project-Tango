"""Tests for RemediationActions."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType
from nexus.self_healing.circuit_breaker import CircuitBreakerManager, BreakerConfig, BreakerState
from nexus.self_healing.checkpoint import CheckpointManager, ConversationState
from nexus.self_healing.remediation_actions import RemediationActions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def bus():
    bus = NexusBus(redis_url="redis://localhost:6379/0")
    bus._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield bus
    await bus.stop_consumer()


@pytest.fixture
def actions(bus):
    return RemediationActions("test-bot", bus)


class _FakeProcess:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRemediationActions:
    """Tests for RemediationActions."""

    async def test_restart_service_success(self, actions) -> None:
        proc = _FakeProcess(returncode=0)
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await actions.restart_service()

        assert result.action == "restart_service"
        assert result.success is True
        assert "restarted" in result.detail

    async def test_restart_service_failure(self, actions) -> None:
        proc = _FakeProcess(returncode=1, stderr=b"Unit not found")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await actions.restart_service()

        assert result.action == "restart_service"
        assert result.success is False

    async def test_reset_breakers(self, actions) -> None:
        manager = CircuitBreakerManager(BreakerConfig(failure_threshold=2))

        # Break a breaker
        async def _fail():
            raise RuntimeError("fail")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await manager.call_llm("model1", _fail)

        assert manager.get_all_states()["llm:model1"] == BreakerState.OPEN

        result = await actions.reset_breakers(manager)

        assert result.action == "reset_breakers"
        assert result.success is True
        assert manager.get_all_states()["llm:model1"] == BreakerState.CLOSED

    async def test_clear_checkpoint_no_checkpoint(self, actions) -> None:
        redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        manager = CheckpointManager("test-bot", redis_client=redis_client)

        result = await actions.clear_checkpoint(manager)

        assert result.action == "clear_checkpoint"
        assert result.success is True
        assert "No checkpoint" in result.detail

    async def test_clear_checkpoint_with_data(self, actions) -> None:
        redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        manager = CheckpointManager("test-bot", redis_client=redis_client)

        state = ConversationState(
            bot_id="test-bot",
            channel_id=123,
            messages=[{"role": "user", "content": "hi"}],
            last_tool_call=None,
            agent_loop_iteration=1,
            timestamp="2026-08-20T10:00:00+00:00",
        )
        await manager.save(state)

        result = await actions.clear_checkpoint(manager)

        assert result.action == "clear_checkpoint"
        assert result.success is True

        await redis_client.aclose()

    async def test_escalate_to_human(self, actions, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.HEALTH_ALERT, handler)
        await bus.start_consumer("test-bot")

        result = await actions.escalate_to_human("Something went wrong")

        await asyncio.sleep(0.5)

        assert result.action == "escalate_to_human"
        assert result.success is True
        assert len(received) == 1
        assert received[0].payload["alert_type"] == "escalation"
        assert received[0].payload["severity"] == "critical"

        await bus.stop_consumer()

    async def test_propagate_fix(self, actions, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.UPDATE_DEPLOY, handler)
        await bus.start_consumer("test-bot")

        result = await actions.propagate_fix("Fixed memory leak")

        await asyncio.sleep(0.5)

        assert result.action == "propagate_fix"
        assert result.success is True
        assert len(received) == 1

        await bus.stop_consumer()
