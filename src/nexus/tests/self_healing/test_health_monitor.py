"""Tests for HealthMonitor."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType
from nexus.self_healing.health_monitor import (
    CheckResult,
    CheckStatus,
    HealthCheck,
    HealthMonitor,
    HealthReport,
    HealthStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _passing_check() -> CheckResult:
    return CheckResult(name="db", status=CheckStatus.PASS, message="ok", duration_ms=1.0)


async def _failing_check() -> CheckResult:
    return CheckResult(name="api", status=CheckStatus.FAIL, message="down", duration_ms=2.0)


async def _warning_check() -> CheckResult:
    return CheckResult(name="cache", status=CheckStatus.WARN, message="slow", duration_ms=5.0)


async def _raising_check() -> CheckResult:
    raise RuntimeError("check exploded")


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

class TestHealthMonitor:
    """Tests for HealthMonitor."""

    async def test_runs_checks(self) -> None:
        checks = [
            HealthCheck("db", _passing_check),
            HealthCheck("api", _failing_check),
        ]
        monitor = HealthMonitor("test-bot", checks, interval_seconds=60)

        report = await monitor.run_checks()

        assert report.bot_id == "test-bot"
        assert len(report.checks) == 2
        assert report.status == HealthStatus.UNHEALTHY
        assert report.checks[0].name == "db"
        assert report.checks[0].status == CheckStatus.PASS
        assert report.checks[1].name == "api"
        assert report.checks[1].status == CheckStatus.FAIL

    async def test_aggregates_to_degraded(self) -> None:
        checks = [
            HealthCheck("db", _passing_check),
            HealthCheck("cache", _warning_check),
        ]
        monitor = HealthMonitor("test-bot", checks, interval_seconds=60)

        report = await monitor.run_checks()

        assert report.status == HealthStatus.DEGRADED

    async def test_aggregates_to_healthy(self) -> None:
        checks = [HealthCheck("db", _passing_check)]
        monitor = HealthMonitor("test-bot", checks, interval_seconds=60)

        report = await monitor.run_checks()

        assert report.status == HealthStatus.HEALTHY

    async def test_check_exception_becomes_fail(self) -> None:
        checks = [HealthCheck("broken", _raising_check)]
        monitor = HealthMonitor("test-bot", checks, interval_seconds=60)

        report = await monitor.run_checks()

        assert report.status == HealthStatus.UNHEALTHY
        assert report.checks[0].status == CheckStatus.FAIL
        assert "exception" in report.checks[0].message.lower()

    async def test_publishes_to_nexus_bus(self, bus) -> None:
        received: list = []

        async def handler(event):
            received.append(event)

        await bus.subscribe(EventType.HEALTH_REPORT, handler)
        await bus.start_consumer("monitor-bot")

        checks = [HealthCheck("db", _passing_check)]
        monitor = HealthMonitor("test-bot", checks, interval_seconds=60, nexus_bus=bus)

        await monitor.run_checks()
        await asyncio.sleep(0.5)

        assert len(received) == 1
        assert received[0].event_type == EventType.HEALTH_REPORT
        assert received[0].payload["bot_id"] == "test-bot"
        assert received[0].payload["status"] == "healthy"

        await bus.stop_consumer()

    async def test_start_stop_lifecycle(self) -> None:
        checks = [HealthCheck("db", _passing_check)]
        monitor = HealthMonitor("test-bot", checks, interval_seconds=1)

        await monitor.start()
        assert monitor._running
        assert monitor._task is not None

        await asyncio.sleep(0.1)

        await monitor.stop()
        assert not monitor._running
        assert monitor._task is None

    async def test_metrics_in_report(self) -> None:
        checks = [
            HealthCheck("db", _passing_check),
            HealthCheck("api", _failing_check),
            HealthCheck("cache", _warning_check),
        ]
        monitor = HealthMonitor("test-bot", checks, interval_seconds=60)

        report = await monitor.run_checks()

        assert report.metrics["total_checks"] == 3
        assert report.metrics["passed"] == 1
        assert report.metrics["failed"] == 1
        assert report.metrics["warned"] == 1
