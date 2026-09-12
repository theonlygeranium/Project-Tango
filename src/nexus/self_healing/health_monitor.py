"""Health Monitor — runs periodic health checks and publishes reports to the Nexus Bus.

Each bot registers a set of HealthCheck callables. The HealthMonitor runs them
on an interval, aggregates the results into a HealthReport, and publishes the
report as a health.report event.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    duration_ms: float


@dataclass
class HealthReport:
    bot_id: str
    status: HealthStatus
    uptime_s: float
    checks: list[CheckResult]
    metrics: dict[str, Any]
    timestamp: str


class HealthCheck:
    """A single named health check with an async check function."""

    def __init__(
        self, name: str, check_fn: Callable[[], Awaitable[CheckResult]]
    ) -> None:
        self._name = name
        self._check_fn = check_fn

    async def run(self) -> CheckResult:
        """Execute the check function and return the result."""
        try:
            return await self._check_fn()
        except Exception as exc:
            logger.error("Health check '%s' raised: %s", self._name, exc)
            return CheckResult(
                name=self._name,
                status=CheckStatus.FAIL,
                message=f"Check raised exception: {exc}",
                duration_ms=0.0,
            )


class HealthMonitor:
    """Runs health checks on an interval and publishes reports."""

    def __init__(
        self,
        bot_id: str,
        checks: list[HealthCheck],
        interval_seconds: int,
        nexus_bus: NexusBus | None = None,
    ) -> None:
        self._bot_id = bot_id
        self._checks = checks
        self._interval_seconds = interval_seconds
        self._nexus_bus = nexus_bus
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._start_time: float = 0.0

    async def start(self) -> None:
        """Start the periodic health check loop."""
        self._running = True
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._loop())
        logger.info("HealthMonitor started for bot '%s'", self._bot_id)

    async def stop(self) -> None:
        """Stop the periodic health check loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("HealthMonitor stopped for bot '%s'", self._bot_id)

    async def run_checks(self) -> HealthReport:
        """Run all registered health checks and return a HealthReport."""
        results: list[CheckResult] = []
        for check in self._checks:
            start = time.monotonic()
            result = await check.run()
            if result.duration_ms == 0.0:
                result = CheckResult(
                    name=result.name,
                    status=result.status,
                    message=result.message,
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            results.append(result)

        status = self._aggregate_status(results)
        uptime = time.monotonic() - self._start_time if self._start_time else 0.0

        report = HealthReport(
            bot_id=self._bot_id,
            status=status,
            uptime_s=uptime,
            checks=results,
            metrics=self._collect_metrics(results),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        await self._publish_report(report)
        return report

    async def _loop(self) -> None:
        """Background loop that runs checks on the configured interval."""
        while self._running:
            try:
                await self.run_checks()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Health check loop error: %s", exc)

            await asyncio.sleep(self._interval_seconds)

    def _aggregate_status(self, results: list[CheckResult]) -> HealthStatus:
        has_fail = any(r.status == CheckStatus.FAIL for r in results)
        has_warn = any(r.status == CheckStatus.WARN for r in results)

        if has_fail:
            return HealthStatus.UNHEALTHY
        if has_warn:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def _collect_metrics(self, results: list[CheckResult]) -> dict[str, Any]:
        return {
            "total_checks": len(results),
            "passed": sum(1 for r in results if r.status == CheckStatus.PASS),
            "failed": sum(1 for r in results if r.status == CheckStatus.FAIL),
            "warned": sum(1 for r in results if r.status == CheckStatus.WARN),
        }

    async def _publish_report(self, report: HealthReport) -> None:
        if self._nexus_bus is None:
            return

        event = NexusEvent.create(
            event_type=EventType.HEALTH_REPORT,
            source=self._bot_id,
            target="broadcast",
            payload={
                "bot_id": report.bot_id,
                "status": report.status.value,
                "uptime_seconds": int(report.uptime_s),
                "metrics": report.metrics,
            },
        )
        await self._nexus_bus.publish(event)
