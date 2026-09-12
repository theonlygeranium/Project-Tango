"""Escalation ladder for the Orchestrator Router.

The escalation ladder is monotonic — each step only fires if the prior
step fails:

1. Retry (handled by AcknowledgmentTracker)
2. Reroute to alternative bot (if manifest declares one)
3. Escalate to Dr. Voss for diagnosis
4. Escalate to human operator via Discord
"""

from __future__ import annotations

import logging
from typing import Any

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import FleetManifest

logger = logging.getLogger(__name__)

# Mapping of bot to its alternative bot for rerouting.
# In a production system, this would come from the manifest. For now,
# we use a static fallback mapping.
_ALTERNATIVES: dict[str, str] = {
    "architect": "voss",
    "voss": "architect",
    "cortex": "architect",
    "quartermaster": "architect",
    "cartographer": "cortex",
    "proctor": "cortex",
}


class EscalationLadder:
    """Monotonic escalation ladder for failed tasks.

    Steps:
        1. Retry (AcknowledgmentTracker)
        2. Reroute to alternative bot
        3. Escalate to Dr. Voss for diagnosis
        4. Escalate to human operator via Discord
    """

    def __init__(
        self,
        nexus: NexusBus,
        manifest: FleetManifest,
        acknowledgment: Any,
    ) -> None:
        self._nexus = nexus
        self._manifest = manifest
        self._ack = acknowledgment
        # correlation_id -> SubTask
        self._subtask_registry: dict[str, Any] = {}
        logger.debug("EscalationLadder initialized")

    def register(self, correlation_id: str, subtask: Any) -> None:
        """Register a sub-task for escalation tracking.

        Args:
            correlation_id: The correlation ID of the task.
            subtask: The SubTask object.
        """
        self._subtask_registry[correlation_id] = subtask
        logger.debug("Registered subtask for escalation tracking: %s", correlation_id)

    async def escalate(self, subtask: Any, reason: str) -> None:
        """Escalate a sub-task through the escalation ladder.

        This is the main entry point. It tries rerouting first, then
        escalates to Voss, then to human.

        Args:
            subtask: The SubTask that failed.
            reason: Why the escalation is happening.
        """
        logger.warning(
            "Escalating subtask %s (target=%s): %s",
            subtask.subtask_id,
            subtask.target_bot,
            reason,
        )

        # Step 2: Try rerouting to an alternative bot
        alternative = self._lookup_alternative(subtask.target_bot)
        if alternative is not None:
            logger.info(
                "Rerouting subtask %s from %s to %s",
                subtask.subtask_id,
                subtask.target_bot,
                alternative,
            )
            await self._reroute(subtask, alternative)
            return

        # Step 3: Escalate to Dr. Voss for diagnosis
        logger.info(
            "No alternative for %s, escalating to Dr. Voss",
            subtask.target_bot,
        )
        await self._escalate_to_voss(subtask, reason)

    async def escalate_timeout(self, correlation_id: str) -> None:
        """Escalate after all ack retries have been exhausted.

        Args:
            correlation_id: The correlation ID that timed out.
        """
        subtask = self._lookup_subtask(correlation_id)
        if subtask is None:
            logger.error(
                "Cannot escalate timeout: no subtask for correlation_id=%s",
                correlation_id,
            )
            return

        await self.escalate(subtask, "acknowledgment timeout")

    async def _reroute(self, subtask: Any, alternative_bot: str) -> None:
        """Reroute a sub-task to an alternative bot.

        Args:
            subtask: The SubTask to reroute.
            alternative_bot: The bot to reroute to.
        """
        rerouted = SubTaskRerouted(
            subtask_id=subtask.subtask_id,
            original_bot=subtask.target_bot,
            new_bot=alternative_bot,
            description=subtask.description,
            priority=subtask.priority,
            context=subtask.context,
            acceptance_criteria=subtask.acceptance_criteria,
        )
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target=alternative_bot,
            payload={
                "subtask_id": subtask.subtask_id,
                "description": subtask.description,
                "priority": subtask.priority,
                "context": subtask.context,
                "acceptance_criteria": subtask.acceptance_criteria,
                "rerouted_from": subtask.target_bot,
                "rerouted": True,
            },
        )
        await self._nexus.publish(event)
        logger.info(
            "Rerouted subtask %s to %s",
            subtask.subtask_id,
            alternative_bot,
        )

    async def _escalate_to_voss(self, subtask: Any, reason: str) -> None:
        """Escalate to Dr. Voss for diagnosis.

        Dr. Voss will diagnose whether the target bot is down. If Voss
        confirms the bot is down and no alternative exists, escalation
        proceeds to human.

        Args:
            subtask: The SubTask that failed.
            reason: Why escalation is happening.
        """
        event = NexusEvent.create(
            event_type=EventType.HEALTH_ALERT,
            source="orchestrator",
            target="voss",
            payload={
                "bot_id": subtask.target_bot,
                "alert_type": "task_escalation",
                "severity": "critical",
                "message": f"Task {subtask.subtask_id} failed: {reason}",
                "details": {
                    "subtask_id": subtask.subtask_id,
                    "description": subtask.description,
                    "target_bot": subtask.target_bot,
                    "reason": reason,
                },
            },
        )
        await self._nexus.publish(event)
        logger.info(
            "Escalated subtask %s to Dr. Voss (health.alert)",
            subtask.subtask_id,
        )

        # Also escalate to human since we can't confirm Voss's response
        # in this synchronous flow. In production, Voss would ack and
        # the orchestrator would wait for its diagnosis.
        await self._escalate_to_human(subtask, reason)

    async def _escalate_to_human(self, subtask: Any, reason: str) -> None:
        """Escalate to human operator via Discord.

        Publishes a health.alert event targeted at the admiral (which
        has Discord access) for human notification.

        Args:
            subtask: The SubTask that failed.
            reason: Why escalation is happening.
        """
        event = NexusEvent.create(
            event_type=EventType.HEALTH_ALERT,
            source="orchestrator",
            target="admiral",
            payload={
                "bot_id": subtask.target_bot,
                "alert_type": "human_escalation",
                "severity": "critical",
                "message": (
                    f"Human escalation required: bot {subtask.target_bot} "
                    f"is unresponsive. Task: {subtask.description}. "
                    f"Reason: {reason}"
                ),
                "details": {
                    "subtask_id": subtask.subtask_id,
                    "description": subtask.description,
                    "target_bot": subtask.target_bot,
                    "reason": reason,
                },
            },
        )
        await self._nexus.publish(event)
        logger.warning(
            "Escalated subtask %s to human operator via Discord",
            subtask.subtask_id,
        )

    def _lookup_subtask(self, correlation_id: str) -> Any:
        """Look up a sub-task by correlation ID.

        Args:
            correlation_id: The correlation ID to look up.

        Returns:
            The SubTask object, or None if not found.
        """
        return self._subtask_registry.get(correlation_id)

    def _lookup_alternative(self, bot_name: str) -> str | None:
        """Look up an alternative bot for rerouting.

        Args:
            bot_name: The original target bot.

        Returns:
            Alternative bot name, or None if no alternative exists.
        """
        return _ALTERNATIVES.get(bot_name)


class SubTaskRerouted:
    """Lightweight dataclass for a rerouted sub-task (internal use)."""

    def __init__(
        self,
        subtask_id: str,
        original_bot: str,
        new_bot: str,
        description: str,
        priority: str,
        context: dict[str, Any],
        acceptance_criteria: str,
    ) -> None:
        self.subtask_id = subtask_id
        self.original_bot = original_bot
        self.new_bot = new_bot
        self.description = description
        self.priority = priority
        self.context = context
        self.acceptance_criteria = acceptance_criteria
