"""Acknowledgment tracker for the Orchestrator Router.

Tracks task acknowledgments from specialist bots. Uses a 30-second ack
window with exponential backoff retries (2s, 4s). After MAX_RETRIES
failed attempts, the on_final_failure callback is invoked (typically
escalation).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import FleetManifest

logger = logging.getLogger(__name__)


class AcknowledgmentTracker:
    """Tracks task acknowledgments with timeout and retry logic.

    Constants:
        DEFAULT_TIMEOUT: Seconds to wait for an ack before retrying.
        MAX_RETRIES: Maximum number of retry attempts (2 retries = 3 total attempts).
        BACKOFF_BASE: Base for exponential backoff (2.0 → 2s, 4s, 8s, ...).
    """

    DEFAULT_TIMEOUT: float = 30.0
    MAX_RETRIES: int = 2
    BACKOFF_BASE: float = 2.0

    def __init__(self, nexus: NexusBus, manifest: FleetManifest) -> None:
        self._nexus = nexus
        self._manifest = manifest
        # correlation_id -> asyncio.Event
        self._pending: dict[str, asyncio.Event] = {}
        # correlation_id -> retry count
        self._retries: dict[str, int] = {}
        # correlation_id -> SubTask (for republishing)
        self._subtasks: dict[str, Any] = {}
        logger.debug("AcknowledgmentTracker initialized")

    def register(self, correlation_id: str, subtask: Any) -> None:
        """Register a pending sub-task for ack tracking.

        Args:
            correlation_id: The correlation ID of the published task.new event.
            subtask: The SubTask object (used for republishing on retry).
        """
        self._pending[correlation_id] = asyncio.Event()
        self._retries[correlation_id] = 0
        self._subtasks[correlation_id] = subtask
        logger.debug("Registered pending ack for correlation_id=%s", correlation_id)

    async def wait_for_ack(
        self, correlation_id: str, timeout: float = DEFAULT_TIMEOUT
    ) -> bool:
        """Wait for an acknowledgment within *timeout* seconds.

        Args:
            correlation_id: The correlation ID to wait for.
            timeout: Maximum seconds to wait.

        Returns:
            True if ack was received, False on timeout.
        """
        event = self._pending.get(correlation_id)
        if event is None:
            logger.warning(
                "No pending ack registered for correlation_id=%s", correlation_id
            )
            return False

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            logger.info("Ack received for correlation_id=%s", correlation_id)
            self._cleanup(correlation_id)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "Ack timeout for correlation_id=%s after %.1fs",
                correlation_id,
                timeout,
            )
            return False

    async def record_ack(self, correlation_id: str) -> None:
        """Record that an ack was received for *correlation_id*.

        This sets the asyncio.Event so that wait_for_ack returns immediately.
        """
        event = self._pending.get(correlation_id)
        if event is not None:
            event.set()
            logger.debug("Recorded ack for correlation_id=%s", correlation_id)
        else:
            logger.warning(
                "Ack received for unknown correlation_id=%s", correlation_id
            )

    async def handle_timeout(
        self,
        correlation_id: str,
        on_final_failure: Callable[[], Any] | None = None,
    ) -> None:
        """Handle a timeout by retrying with exponential backoff.

        Retries up to MAX_RETRIES times. After final failure, calls
        *on_final_failure* if provided.

        Args:
            correlation_id: The correlation ID that timed out.
            on_final_failure: Callback invoked after all retries are exhausted.
        """
        retries = self._retries.get(correlation_id, 0)

        if retries >= self.MAX_RETRIES:
            logger.error(
                "Max retries (%d) exhausted for correlation_id=%s, "
                "invoking final failure callback",
                self.MAX_RETRIES,
                correlation_id,
            )
            if on_final_failure is not None:
                try:
                    result = on_final_failure()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    logger.error("on_final_failure callback raised: %s", exc)
            self._cleanup(correlation_id)
            return

        backoff = self.BACKOFF_BASE ** (retries + 1)
        self._retries[correlation_id] = retries + 1
        logger.info(
            "Retrying correlation_id=%s (attempt %d/%d) after %.1fs backoff",
            correlation_id,
            retries + 1,
            self.MAX_RETRIES,
            backoff,
        )
        await asyncio.sleep(backoff)
        await self._republish(correlation_id)

    async def _republish(self, correlation_id: str) -> bool:
        """Republish the task.new event for *correlation_id*.

        Returns:
            True if republished successfully, False otherwise.
        """
        subtask = self._subtasks.get(correlation_id)
        if subtask is None:
            logger.error(
                "Cannot republish: no subtask for correlation_id=%s", correlation_id
            )
            return False

        try:
            event = NexusEvent.create(
                event_type=EventType.TASK_NEW,
                source="orchestrator",
                target=subtask.target_bot,
                correlation_id=correlation_id,
                payload={
                    "subtask_id": subtask.subtask_id,
                    "description": subtask.description,
                    "priority": subtask.priority,
                    "context": subtask.context,
                    "acceptance_criteria": subtask.acceptance_criteria,
                    "retry": True,
                },
            )
            await self._nexus.publish(event)
            logger.info(
                "Republished task.new for correlation_id=%s to %s",
                correlation_id,
                subtask.target_bot,
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to republish for correlation_id=%s: %s",
                correlation_id,
                exc,
            )
            return False

    def _cleanup(self, correlation_id: str) -> None:
        """Remove all tracking state for *correlation_id*."""
        self._pending.pop(correlation_id, None)
        self._retries.pop(correlation_id, None)
        self._subtasks.pop(correlation_id, None)
