"""Tests for RuntimeSupervisor."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType
from nexus.self_healing.supervisor import (
    AgentEvent,
    BehaviorReport,
    RuntimeSupervisor,
    SupervisorAction,
    SupervisorConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def bus():
    bus = NexusBus(redis_url="redis://localhost:6379/0")
    bus._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield bus
    await bus.stop_consumer()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRuntimeSupervisor:
    """Tests for RuntimeSupervisor."""

    async def test_observe_returns_none_on_healthy(self, bus) -> None:
        supervisor = RuntimeSupervisor("test-bot", bus)
        result = await supervisor.observe("tool_call", tool="search", result="ok")
        assert result is None

    async def test_observe_returns_action_on_error(self, bus) -> None:
        supervisor = RuntimeSupervisor("test-bot", bus)
        result = await supervisor.observe("error", tool="search", result="timeout")
        assert result is not None
        assert result.action == "escalate"
        assert "timeout" in result.reason

    async def test_observe_returns_restart_on_repeated_errors(self, bus) -> None:
        supervisor = RuntimeSupervisor("test-bot", bus)

        # First two errors: escalate
        for _ in range(3):
            await supervisor.observe("error", tool="search", result="fail")

        # After 3 errors in last 10 events, should recommend restart
        result = await supervisor.observe("error", tool="search", result="fail")
        assert result is not None
        assert result.action == "restart"

    async def test_watchdog_detects_stuck_bot(self, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.HEALTH_ALERT, handler)
        await bus.start_consumer("supervisor-bot")

        config = SupervisorConfig(
            enabled=True, poll_interval=1, watchdog_timeout=2
        )
        supervisor = RuntimeSupervisor("test-bot", bus, config=config)

        # Set last_activity to the past to simulate a stuck bot
        supervisor._last_activity = time.monotonic() - 3.0

        await supervisor.start()

        await asyncio.sleep(2.5)

        await supervisor.stop()

        alerts = [e for e in received if e.event_type == EventType.HEALTH_ALERT]
        assert len(alerts) >= 1
        assert alerts[0].payload["alert_type"] == "watchdog_timeout"

        await bus.stop_consumer()

    async def test_start_stop_lifecycle(self, bus) -> None:
        config = SupervisorConfig(enabled=True, poll_interval=60, watchdog_timeout=120)
        supervisor = RuntimeSupervisor("test-bot", bus, config=config)

        await supervisor.start()
        assert supervisor._running
        assert supervisor._watchdog_task is not None

        await supervisor.stop()
        assert not supervisor._running
        assert supervisor._watchdog_task is None

    async def test_disabled_supervisor_no_task(self, bus) -> None:
        config = SupervisorConfig(enabled=False)
        supervisor = RuntimeSupervisor("test-bot", bus, config=config)

        await supervisor.start()
        assert supervisor._watchdog_task is None
        assert not supervisor._running

        await supervisor.stop()

    async def test_config_from_dict(self, bus) -> None:
        supervisor = RuntimeSupervisor(
            "test-bot", bus, config={"enabled": True, "poll_interval": 5, "watchdog_timeout": 30}
        )
        assert supervisor._config.enabled is True
        assert supervisor._config.poll_interval == 5
        assert supervisor._config.watchdog_timeout == 30

    async def test_config_from_supervisor_config(self, bus) -> None:
        config = SupervisorConfig(enabled=False, poll_interval=3, watchdog_timeout=10)
        supervisor = RuntimeSupervisor("test-bot", bus, config=config)
        assert supervisor._config.enabled is False
        assert supervisor._config.poll_interval == 3
        assert supervisor._config.watchdog_timeout == 10

    async def test_config_default_when_none(self, bus) -> None:
        supervisor = RuntimeSupervisor("test-bot", bus, config=None)
        assert supervisor._config.enabled is True
        assert supervisor._config.poll_interval == 10
        assert supervisor._config.watchdog_timeout == 120
