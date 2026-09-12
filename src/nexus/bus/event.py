"""Nexus Bus event definitions.

Defines the NexusEvent dataclass, EventType constants, and payload TypedDicts
for all event types used across the Nexus Fleet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import uuid4

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

class EventType:
    """Constants for all Nexus event types."""

    # Core task lifecycle
    TASK_NEW = "task.new"
    TASK_ACK = "task.ack"
    TASK_PROGRESS = "task.progress"
    TASK_RESULT = "task.result"
    TASK_COMPLETE = "task.complete"
    TASK_TIMEOUT = "task.timeout"

    # Health monitoring
    HEALTH_REPORT = "health.report"
    HEALTH_ALERT = "health.alert"

    # Failure and recovery
    FAILURE_LOGGED = "failure.logged"
    RECOVERY_EXECUTED = "recovery.executed"

    # Updates
    UPDATE_PROPOSE = "update.propose"
    UPDATE_DEPLOY = "update.deploy"
    UPDATE_ACK = "update.ack"

    # System
    SYSTEM_SHUTDOWN = "system.shutdown"

    # Testing (Sentinel NX-SPEC-10)
    TESTING_RUN_NOW = "testing.run_now"
    TESTING_RECIPE_UPDATED = "testing.recipe_updated"
    TESTING_CYCLE_COMPLETE = "testing.cycle_complete"

    # Flywheel (Sentinel NX-SPEC-10)
    FLYWHEEL_LLM_CALL = "flywheel.llm_call"
    FLYWHEEL_TEST_RESULTS = "flywheel.test_results"


# ---------------------------------------------------------------------------
# Payload TypedDicts
# ---------------------------------------------------------------------------

class TaskNewPayload(TypedDict):
    """Payload for task.new events."""

    task_id: str
    task_type: str
    description: str
    priority: str
    deadline: str | None


class TaskAckPayload(TypedDict):
    """Payload for task.ack events."""

    task_id: str
    bot_id: str
    accepted: bool


class TaskProgressPayload(TypedDict):
    """Payload for task.progress events."""

    task_id: str
    bot_id: str
    progress: int
    message: str


class TaskResultPayload(TypedDict):
    """Payload for task.result events."""

    task_id: str
    bot_id: str
    status: str
    result: Any
    error: str | None


class TaskCompletePayload(TypedDict):
    """Payload for task.complete events."""

    task_id: str
    bot_id: str
    status: str
    duration_ms: int


class TaskTimeoutPayload(TypedDict):
    """Payload for task.timeout events."""

    task_id: str
    bot_id: str
    timeout_seconds: int


class HealthReportPayload(TypedDict):
    """Payload for health.report events."""

    bot_id: str
    status: str
    uptime_seconds: int
    metrics: dict[str, Any]


class HealthAlertPayload(TypedDict):
    """Payload for health.alert events."""

    bot_id: str
    alert_type: str
    severity: str
    message: str
    details: dict[str, Any]


class FailureLoggedPayload(TypedDict):
    """Payload for failure.logged events."""

    bot_id: str
    failure_type: str
    error_message: str
    stack_trace: str | None
    context: dict[str, Any]


class RecoveryExecutedPayload(TypedDict):
    """Payload for recovery.executed events."""

    bot_id: str
    failure_type: str
    recovery_action: str
    success: bool
    details: dict[str, Any]


class UpdateProposePayload(TypedDict):
    """Payload for update.propose events."""

    update_id: str
    bot_id: str
    change_type: str
    description: str
    diff: str | None


class UpdateDeployPayload(TypedDict):
    """Payload for update.deploy events."""

    update_id: str
    bot_id: str
    version: str
    artifact_url: str | None


class UpdateAckPayload(TypedDict):
    """Payload for update.ack events."""

    update_id: str
    bot_id: str
    status: str
    message: str | None


class SystemShutdownPayload(TypedDict):
    """Payload for system.shutdown events."""

    reason: str
    initiator: str
    grace_period_seconds: int


class TestingRunNowPayload(TypedDict):
    """Payload for testing.run_now events."""

    __test__ = False  # prevent pytest from collecting this as a test class

    bot_id: str
    test_suite: str
    priority: str


class TestingRecipeUpdatedPayload(TypedDict):
    """Payload for testing.recipe_updated events."""

    __test__ = False

    bot_id: str
    recipe_id: str
    changes: dict[str, Any]


class TestingCycleCompletePayload(TypedDict):
    """Payload for testing.cycle_complete events."""

    __test__ = False

    bot_id: str
    cycle_id: str
    passed: int
    failed: int
    skipped: int


class FlywheelLlmCallPayload(TypedDict):
    """Payload for flywheel.llm_call events."""

    bot_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class FlywheelTestResultsPayload(TypedDict):
    """Payload for flywheel.test_results events."""

    bot_id: str
    test_id: str
    results: dict[str, Any]


# ---------------------------------------------------------------------------
# NexusEvent dataclass
# ---------------------------------------------------------------------------

@dataclass
class NexusEvent:
    """A single event flowing through the Nexus Bus.

    Attributes:
        event_type: The event type string (see EventType constants).
        source: The bot or component that emitted this event.
        target: The intended recipient bot_id, or "broadcast" for all.
        timestamp: ISO-8601 UTC timestamp string.
        correlation_id: UUID for tracing event chains.
        payload: Event-specific data dict.
    """

    event_type: str
    source: str
    target: str
    timestamp: str
    correlation_id: str
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        event_type: str,
        source: str,
        target: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> "NexusEvent":
        """Create a new NexusEvent with auto-generated timestamp and correlation_id."""
        event = cls(
            event_type=event_type,
            source=source,
            target=target,
            timestamp=datetime.now(timezone.utc).isoformat(),
            correlation_id=correlation_id or str(uuid4()),
            payload=payload,
        )
        logger.debug("Created event %s (correlation_id=%s)", event_type, event.correlation_id)
        return event
