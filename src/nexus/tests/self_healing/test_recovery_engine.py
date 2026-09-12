"""Tests for RecoveryEngine."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType
from nexus.self_healing.circuit_breaker import CircuitBreakerManager, BreakerConfig
from nexus.self_healing.checkpoint import CheckpointManager
from nexus.self_healing.recovery_engine import (
    FailureType,
    RecoveryEngine,
    RecoveryOutcome,
)
from nexus.self_healing.remediation_actions import RemediationActions
from nexus.self_healing.semantic_breaker import SemanticBreaker


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
def recovery_engine(bus):
    breaker_manager = CircuitBreakerManager(BreakerConfig.for_llm())
    semantic_breaker = SemanticBreaker()
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    checkpoint_manager = CheckpointManager("test-bot", redis_client=redis_client)
    remediation_actions = RemediationActions("test-bot", bus)

    engine = RecoveryEngine(
        bot_id="test-bot",
        breaker_manager=breaker_manager,
        semantic_breaker=semantic_breaker,
        checkpoint_manager=checkpoint_manager,
        remediation_actions=remediation_actions,
        nexus_bus=bus,
        max_retries=3,
        base_backoff=0.01,
        max_backoff=0.1,
    )
    return engine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecoveryEngine:
    """Tests for RecoveryEngine."""

    async def test_retry_with_backoff_success(self, recovery_engine, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.FAILURE_LOGGED, handler)
        await bus.subscribe(EventType.RECOVERY_EXECUTED, handler)
        await bus.start_consumer("test-bot")

        call_count = [0]

        async def retry_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("transient error")
            return "success"

        result = await recovery_engine.handle_failure(
            source="llm",
            error_type="llm_failure",
            error_message="transient error",
            context={"retry_fn": retry_fn},
        )

        assert result.outcome == RecoveryOutcome.RETRIED
        assert result.retried is True
        assert call_count[0] == 3

        await asyncio.sleep(0.5)
        event_types = [e.event_type for e in received]
        assert EventType.FAILURE_LOGGED in event_types
        assert EventType.RECOVERY_EXECUTED in event_types

        await bus.stop_consumer()

    async def test_retry_exhausted_then_fallback(self, recovery_engine) -> None:
        async def always_fail():
            raise RuntimeError("permanent error")

        async def fallback_fn():
            return "fallback response"

        result = await recovery_engine.handle_failure(
            source="llm",
            error_type="llm_failure",
            error_message="permanent error",
            context={"retry_fn": always_fail, "fallback_fn": fallback_fn},
        )

        assert result.outcome == RecoveryOutcome.FELL_BACK
        assert result.strategy == "fallback"

    async def test_escalate_when_all_fails(self, recovery_engine, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.HEALTH_ALERT, handler)
        await bus.start_consumer("test-bot")

        async def always_fail():
            raise RuntimeError("permanent error")

        result = await recovery_engine.handle_failure(
            source="llm",
            error_type="llm_failure",
            error_message="permanent error",
            context={"retry_fn": always_fail},
        )

        assert result.outcome == RecoveryOutcome.ESCALATED
        assert result.strategy == "escalate"

        await asyncio.sleep(0.5)
        alerts = [e for e in received if e.event_type == EventType.HEALTH_ALERT]
        assert len(alerts) >= 1

        await bus.stop_consumer()

    async def test_publishes_failure_logged(self, recovery_engine, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.FAILURE_LOGGED, handler)
        await bus.start_consumer("test-bot")

        async def retry_fn():
            return "ok"

        await recovery_engine.handle_failure(
            source="tool",
            error_type="tool_failure",
            error_message="some error",
            context={"retry_fn": retry_fn},
        )

        await asyncio.sleep(0.5)

        failure_events = [e for e in received if e.event_type == EventType.FAILURE_LOGGED]
        assert len(failure_events) == 1
        assert failure_events[0].payload["bot_id"] == "test-bot"
        assert failure_events[0].payload["failure_type"] == "tool_failure"

        await bus.stop_consumer()

    async def test_publishes_recovery_executed(self, recovery_engine, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.RECOVERY_EXECUTED, handler)
        await bus.start_consumer("test-bot")

        async def retry_fn():
            return "ok"

        await recovery_engine.handle_failure(
            source="llm",
            error_type="llm_failure",
            error_message="error",
            context={"retry_fn": retry_fn},
        )

        await asyncio.sleep(0.5)

        recovery_events = [e for e in received if e.event_type == EventType.RECOVERY_EXECUTED]
        assert len(recovery_events) == 1
        assert recovery_events[0].payload["recovery_action"] == "retry"
        assert recovery_events[0].payload["success"] is True

        await bus.stop_consumer()

    async def test_no_retry_fn_returns_unrecovered(self, recovery_engine) -> None:
        result = await recovery_engine.handle_failure(
            source="llm",
            error_type="llm_failure",
            error_message="error",
            context={},
        )

        # No retry_fn, no fallback_fn -> escalate
        assert result.outcome == RecoveryOutcome.ESCALATED
