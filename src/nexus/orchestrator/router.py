"""Orchestrator Router — top-level request routing for the Nexus Fleet.

The OrchestratorRouter is the Admiral's routing engine. It decomposes
incoming requests into sub-tasks, assigns each to the correct specialist
bot via the Nexus Bus, and waits for acknowledgments. Timeouts trigger
the escalation ladder.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.manifest.schema import FleetManifest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubTask:
    """A single sub-task produced by the decomposer.

    Attributes:
        subtask_id: Unique identifier for this sub-task.
        target_bot: The bot that should handle this sub-task.
        description: Human-readable description of what to do.
        priority: "low" | "normal" | "high" | "critical".
        context: Additional context dict.
        acceptance_criteria: How to verify the task is done.
        correlation_id: UUID for tracing event chains.
        created_at: ISO-8601 UTC timestamp.
    """

    subtask_id: str
    target_bot: str
    description: str
    priority: str  # "low" | "normal" | "high" | "critical"
    context: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: str = ""
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class TaskAssignment:
    """A sub-task paired with its publication metadata.

    Attributes:
        subtask: The SubTask that was assigned.
        event_id: The Redis stream message ID from the published task.new event.
        published_at: ISO-8601 UTC timestamp of publication.
        stream_id: The stream the event was published to.
    """

    subtask: SubTask
    event_id: str
    published_at: str
    stream_id: str


class OrchestratorRouter:
    """Top-level orchestrator router for the Nexus Fleet.

    The router decomposes incoming requests, assigns each sub-task to
    the correct specialist bot, and waits for acknowledgments. If a bot
    fails to ack within the timeout window, the escalation ladder is
    triggered.

    Args:
        nexus: The NexusBus instance for event publishing.
        manifest: The FleetManifest with routing table and bot configs.
        decomposer: Optional TaskDecomposer instance (created if not provided).
        acknowledgment: Optional AcknowledgmentTracker instance (created if not provided).
        escalation: Optional EscalationLadder instance (created if not provided).
    """

    def __init__(
        self,
        nexus: NexusBus,
        manifest: FleetManifest,
        decomposer: Any | None = None,
        acknowledgment: Any | None = None,
        escalation: Any | None = None,
    ) -> None:
        self._nexus = nexus
        self._manifest = manifest

        # Lazily import to avoid circular dependencies
        from nexus.orchestrator.acknowledgment import AcknowledgmentTracker
        from nexus.orchestrator.decomposer import TaskDecomposer
        from nexus.orchestrator.escalation import EscalationLadder

        self._decomposer = decomposer or TaskDecomposer(nexus, manifest)
        self._ack = acknowledgment or AcknowledgmentTracker(nexus, manifest)
        self._escalation = escalation or EscalationLadder(
            nexus, manifest, self._ack
        )
        logger.debug("OrchestratorRouter initialized")

    @property
    def decomposer(self) -> Any:
        return self._decomposer

    @property
    def acknowledgment(self) -> Any:
        return self._ack

    @property
    def escalation(self) -> Any:
        return self._escalation

    async def route_request(self, request: str, source: str) -> list[TaskAssignment]:
        """Top-level: decompose, assign each sub-task, wait for ack.

        Args:
            request: The incoming request string.
            source: Who sent the request (e.g. "human_operator").

        Returns:
            List of TaskAssignment objects for successfully published sub-tasks.
        """
        logger.info("Routing request from %s: %s", source, request[:100])

        # Step 1: Decompose
        subtasks = await self.decompose(request)
        logger.info("Decomposed into %d sub-tasks", len(subtasks))

        # Step 2: Assign each sub-task
        assignments: list[TaskAssignment] = []
        for subtask in subtasks:
            assignment = await self._publish_task(subtask)
            assignments.append(assignment)

            # Register for ack tracking
            self._ack.register(subtask.correlation_id, subtask)
            self._escalation.register(subtask.correlation_id, subtask)

        # Step 3: Wait for acks
        for assignment in assignments:
            acked = await self.wait_for_ack(assignment.subtask.correlation_id)
            if not acked:
                await self.handle_timeout(assignment.subtask.correlation_id)

        return assignments

    async def decompose(self, request: str) -> list[SubTask]:
        """Decompose a request into sub-tasks.

        Args:
            request: The incoming request string.

        Returns:
            List of SubTask objects.
        """
        return await self._decomposer.decompose(request)

    async def assign_task(self, subtask: SubTask) -> str:
        """Assign a sub-task by publishing a task.new event.

        Args:
            subtask: The SubTask to assign.

        Returns:
            The Redis stream message ID.
        """
        assignment = await self._publish_task(subtask)
        self._ack.register(subtask.correlation_id, subtask)
        self._escalation.register(subtask.correlation_id, subtask)
        return assignment.event_id

    async def wait_for_ack(
        self, correlation_id: str, timeout: float = 30.0
    ) -> bool:
        """Wait for a bot to acknowledge the task.

        Args:
            correlation_id: The correlation ID to wait for.
            timeout: Seconds to wait before timing out.

        Returns:
            True if acked, False on timeout.
        """
        return await self._ack.wait_for_ack(correlation_id, timeout)

    async def handle_timeout(self, correlation_id: str) -> None:
        """Handle a task timeout by triggering escalation.

        Args:
            correlation_id: The correlation ID that timed out.
        """
        logger.warning("Handling timeout for correlation_id=%s", correlation_id)

        async def on_final_failure() -> None:
            await self._escalation.escalate_timeout(correlation_id)

        await self._ack.handle_timeout(correlation_id, on_final_failure=on_final_failure)

    async def escalate(self, subtask: SubTask, reason: str) -> None:
        """Escalate a sub-task through the escalation ladder.

        Args:
            subtask: The SubTask to escalate.
            reason: Why escalation is happening.
        """
        await self._escalation.escalate(subtask, reason)

    async def _publish_task(self, subtask: SubTask) -> TaskAssignment:
        """Publish a task.new event for a sub-task.

        Args:
            subtask: The SubTask to publish.

        Returns:
            A TaskAssignment with publication metadata.
        """
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target=subtask.target_bot,
            correlation_id=subtask.correlation_id,
            payload={
                "subtask_id": subtask.subtask_id,
                "description": subtask.description,
                "priority": subtask.priority,
                "context": subtask.context,
                "acceptance_criteria": subtask.acceptance_criteria,
            },
        )
        event_id = await self._nexus.publish(event)
        published_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "Published task.new for subtask %s to %s (event_id=%s)",
            subtask.subtask_id,
            subtask.target_bot,
            event_id,
        )

        return TaskAssignment(
            subtask=subtask,
            event_id=event_id,
            published_at=published_at,
            stream_id="nexus:tasks",
        )
