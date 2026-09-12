"""Tests for HealthRegistry."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.self_healing.health_monitor import HealthReport, HealthStatus
from nexus.self_healing.health_registry import HealthRegistry


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
def registry(bus):
    return HealthRegistry(bus)


def _make_report(bot_id: str, status: HealthStatus, timestamp: str | None = None) -> HealthReport:
    return HealthReport(
        bot_id=bot_id,
        status=status,
        uptime_s=100.0,
        checks=[],
        metrics={},
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthRegistry:
    """Tests for HealthRegistry."""

    async def test_updates_on_health_report(self, registry) -> None:
        report = _make_report("bot-1", HealthStatus.HEALTHY)
        await registry.update_bot_health(report)

        state = await registry.get_bot_health("bot-1")
        assert state is not None
        assert state.status == HealthStatus.HEALTHY
        assert state.last_report is not None

    async def test_get_bot_health_returns_none_for_unknown(self, registry) -> None:
        state = await registry.get_bot_health("unknown-bot")
        assert state is None

    async def test_aggregates_fleet_summary(self, registry) -> None:
        await registry.update_bot_health(_make_report("bot-1", HealthStatus.HEALTHY))
        await registry.update_bot_health(_make_report("bot-2", HealthStatus.DEGRADED))
        await registry.update_bot_health(_make_report("bot-3", HealthStatus.UNHEALTHY))

        summary = await registry.get_fleet_summary()

        assert summary.total_bots == 3
        assert summary.healthy == 1
        assert summary.degraded == 1
        assert summary.unhealthy == 1
        assert summary.offline == 0

    async def test_offline_detection(self, registry) -> None:
        old_timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=300)
        ).isoformat()
        await registry.update_bot_health(
            _make_report("bot-1", HealthStatus.HEALTHY, timestamp=old_timestamp)
        )
        await registry.update_bot_health(_make_report("bot-2", HealthStatus.HEALTHY))

        summary = await registry.get_fleet_summary()

        assert summary.total_bots == 2
        assert summary.healthy == 1
        assert summary.offline == 1

    async def test_tracks_multiple_bots(self, registry) -> None:
        for i in range(5):
            await registry.update_bot_health(
                _make_report(f"bot-{i}", HealthStatus.HEALTHY)
            )

        summary = await registry.get_fleet_summary()
        assert summary.total_bots == 5
        assert summary.healthy == 5

    async def test_subscribes_to_health_events(self, bus) -> None:
        registry = HealthRegistry(bus)
        await registry.start()
        await bus.start_consumer("registry-bot")

        # Publish a health report event
        event = NexusEvent.create(
            event_type=EventType.HEALTH_REPORT,
            source="bot-1",
            target="broadcast",
            payload={
                "bot_id": "bot-1",
                "status": "healthy",
                "uptime_seconds": 100,
                "metrics": {},
            },
        )
        await bus.publish(event)

        await asyncio.sleep(0.5)

        state = await registry.get_bot_health("bot-1")
        assert state is not None
        assert state.status == HealthStatus.HEALTHY

        await bus.stop_consumer()

    async def test_alert_marks_unhealthy(self, bus) -> None:
        registry = HealthRegistry(bus)
        await registry.start()
        await bus.start_consumer("registry-bot")

        # First publish a healthy report
        await registry.update_bot_health(_make_report("bot-1", HealthStatus.HEALTHY))

        # Then publish an alert
        alert = NexusEvent.create(
            event_type=EventType.HEALTH_ALERT,
            source="bot-1",
            target="broadcast",
            payload={
                "bot_id": "bot-1",
                "alert_type": "crash_loop",
                "severity": "critical",
                "message": "Crash loop detected",
                "details": {},
            },
        )
        await bus.publish(alert)

        await asyncio.sleep(0.5)

        state = await registry.get_bot_health("bot-1")
        assert state is not None
        assert state.status == HealthStatus.UNHEALTHY

        await bus.stop_consumer()
