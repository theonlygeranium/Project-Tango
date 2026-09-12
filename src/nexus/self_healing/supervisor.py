"""Runtime Supervisor — observes bot behavior and recommends corrective actions.

The supervisor runs a background watchdog that detects stuck bots (no events
within a timeout). It also provides an observe() method that bots call after
each agent loop iteration to get a recommended action (continue, restart, escalate).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent

logger = logging.getLogger(__name__)


@dataclass
class SupervisorConfig:
    """Configuration for the RuntimeSupervisor."""

    enabled: bool = True
    poll_interval: int = 10
    watchdog_timeout: int = 120


@dataclass
class AgentEvent:
    """A single observed agent event."""

    type: str
    tool: str | None
    result: Any
    timestamp: str


@dataclass
class BehaviorReport:
    """Report on a bot's behavior health."""

    bot_id: str
    healthy: bool
    issues: list[str]
    recommendation: str | None


@dataclass
class SupervisorAction:
    """Recommended action from the supervisor."""

    action: str  # "continue", "restart", "escalate"
    reason: str


class RuntimeSupervisor:
    """Observes bot behavior and recommends corrective actions."""

    def __init__(
        self,
        bot_id: str,
        nexus_bus: NexusBus,
        config: SupervisorConfig | dict | None = None,
    ) -> None:
        self._bot_id = bot_id
        self._nexus_bus = nexus_bus

        if config is None:
            self._config = SupervisorConfig()
        elif isinstance(config, dict):
            self._config = SupervisorConfig(**config)
        else:
            self._config = config

        self._events: list[AgentEvent] = []
        self._last_activity: float = time.monotonic()
        self._running = False
        self._watchdog_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the watchdog background task."""
        if not self._config.enabled:
            logger.info("Supervisor disabled for bot '%s'", self._bot_id)
            return

        self._running = True
        self._last_activity = time.monotonic()
        self._watchdog_task = asyncio.create_task(self._watchdog())
        logger.info("Supervisor started for bot '%s'", self._bot_id)

    async def stop(self) -> None:
        """Stop the watchdog background task."""
        self._running = False
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        logger.info("Supervisor stopped for bot '%s'", self._bot_id)

    async def observe(
        self,
        type: str,
        tool: str | None = None,
        result: Any = None,
    ) -> SupervisorAction | None:
        """Record an observed event and return a recommended action if needed.

        Returns None when the bot is behaving normally (continue).
        Returns a SupervisorAction with action="restart" or "escalate" when
        corrective action is needed.
        """
        event = AgentEvent(
            type=type,
            tool=tool,
            result=result,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._events.append(event)
        self._last_activity = time.monotonic()

        # Keep event list bounded
        if len(self._events) > 1000:
            self._events = self._events[-500:]

        # Check for repeated failures first
        recent = self._events[-10:]
        error_count = sum(1 for e in recent if e.type == "error")
        if error_count >= 3:
            return SupervisorAction(
                action="restart",
                reason=f"Too many recent errors: {error_count} in last 10 events",
            )

        # Single error escalates
        if type == "error":
            return SupervisorAction(
                action="escalate",
                reason=f"Error observed: {result}",
            )

        return None

    async def _watchdog(self) -> None:
        """Background loop that checks for stuck bots."""
        while self._running:
            await asyncio.sleep(self._config.poll_interval)

            idle_time = time.monotonic() - self._last_activity
            if idle_time > self._config.watchdog_timeout:
                logger.warning(
                    "Watchdog: bot '%s' has been idle for %.1fs (timeout=%ds)",
                    self._bot_id,
                    idle_time,
                    self._config.watchdog_timeout,
                )
                # Publish a health alert
                try:
                    event = NexusEvent.create(
                        event_type=EventType.HEALTH_ALERT,
                        source=self._bot_id,
                        target="broadcast",
                        payload={
                            "bot_id": self._bot_id,
                            "alert_type": "watchdog_timeout",
                            "severity": "critical",
                            "message": f"Bot {self._bot_id} stuck: no activity for {idle_time:.0f}s",
                            "details": {
                                "idle_seconds": idle_time,
                                "watchdog_timeout": self._config.watchdog_timeout,
                            },
                        },
                    )
                    await self._nexus_bus.publish(event)
                except Exception as exc:
                    logger.error("Watchdog failed to publish alert: %s", exc)

                # Reset the activity timer to avoid spamming alerts
                self._last_activity = time.monotonic()
