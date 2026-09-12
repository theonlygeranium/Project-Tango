"""Health Registry — fleet-wide health aggregation from Nexus Bus events.

Subscribes to health.report and health.alert events on the Nexus Bus and
maintains an in-memory registry of all bots' health states. Provides queries
for individual bot health and fleet-wide summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.self_healing.health_monitor import HealthReport, HealthStatus

logger = logging.getLogger(__name__)


@dataclass
class BotHealthState:
    """Aggregated health state for a single bot."""

    bot_id: str
    status: HealthStatus
    last_report: HealthReport | None
    last_seen: str
    breaker_states: dict[str, str]


@dataclass
class FleetHealthSummary:
    """Fleet-wide health summary."""

    total_bots: int
    healthy: int
    degraded: int
    unhealthy: int
    offline: int
    bots: dict[str, BotHealthState]


class HealthRegistry:
    """Aggregates fleet health from Nexus Bus events."""

    OFFLINE_THRESHOLD_SECONDS = 120

    def __init__(self, nexus_bus: NexusBus) -> None:
        self._nexus_bus = nexus_bus
        self._bots: dict[str, BotHealthState] = {}
        self._running = False

    async def start(self) -> None:
        """Subscribe to health events on the Nexus Bus."""
        await self._nexus_bus.subscribe(
            EventType.HEALTH_REPORT, self._on_health_report
        )
        await self._nexus_bus.subscribe(
            EventType.HEALTH_ALERT, self._on_health_alert
        )
        self._running = True
        logger.info("HealthRegistry started")

    async def _on_health_report(self, event: NexusEvent) -> None:
        """Handle a health.report event."""
        payload = event.payload
        bot_id = payload.get("bot_id", "")
        status_str = payload.get("status", "healthy")

        try:
            status = HealthStatus(status_str)
        except ValueError:
            status = HealthStatus.UNHEALTHY

        # Reconstruct a minimal HealthReport
        report = HealthReport(
            bot_id=bot_id,
            status=status,
            uptime_s=float(payload.get("uptime_seconds", 0)),
            checks=[],
            metrics=payload.get("metrics", {}),
            timestamp=event.timestamp,
        )

        await self.update_bot_health(report)

    async def _on_health_alert(self, event: NexusEvent) -> None:
        """Handle a health.alert event by marking the bot as unhealthy."""
        payload = event.payload
        bot_id = payload.get("bot_id", "")
        if bot_id:
            existing = self._bots.get(bot_id)
            self._bots[bot_id] = BotHealthState(
                bot_id=bot_id,
                status=HealthStatus.UNHEALTHY,
                last_report=existing.last_report if existing else None,
                last_seen=datetime.now(timezone.utc).isoformat(),
                breaker_states=existing.breaker_states if existing else {},
            )

    async def update_bot_health(self, report: HealthReport) -> None:
        """Update the registry with a new health report from a bot."""
        self._bots[report.bot_id] = BotHealthState(
            bot_id=report.bot_id,
            status=report.status,
            last_report=report,
            last_seen=report.timestamp,
            breaker_states={},
        )
        logger.debug("Updated health for bot '%s': %s", report.bot_id, report.status)

    async def get_fleet_summary(self) -> FleetHealthSummary:
        """Return a fleet-wide health summary."""
        now = datetime.now(timezone.utc)

        healthy = 0
        degraded = 0
        unhealthy = 0
        offline = 0

        for state in self._bots.values():
            # Check if the bot is offline (no report in threshold)
            try:
                last_seen = datetime.fromisoformat(state.last_seen)
                if (now - last_seen).total_seconds() > self.OFFLINE_THRESHOLD_SECONDS:
                    offline += 1
                    continue
            except (ValueError, TypeError):
                pass

            if state.status == HealthStatus.HEALTHY:
                healthy += 1
            elif state.status == HealthStatus.DEGRADED:
                degraded += 1
            else:
                unhealthy += 1

        return FleetHealthSummary(
            total_bots=len(self._bots),
            healthy=healthy,
            degraded=degraded,
            unhealthy=unhealthy,
            offline=offline,
            bots=dict(self._bots),
        )

    async def get_bot_health(self, bot_id: str) -> BotHealthState | None:
        """Return the health state for a single bot, or None if unknown."""
        return self._bots.get(bot_id)
