"""Nexus Bus — inter-bot event streaming via Redis Streams.

Public API re-exports for the Nexus Bus package.
"""

from .client import EventHandler, NexusBus, STREAM_MAP
from .consumer import ConsumerManager
from .event import (
    EventType,
    FailureLoggedPayload,
    FlywheelTestResultsPayload,
    HealthAlertPayload,
    HealthReportPayload,
    NexusEvent,
    RecoveryExecutedPayload,
    SystemShutdownPayload,
    TaskAckPayload,
    TaskCompletePayload,
    TaskNewPayload,
    TaskProgressPayload,
    TaskResultPayload,
    TaskTimeoutPayload,
    TestingCycleCompletePayload,
    TestingRecipeUpdatedPayload,
    TestingRunNowPayload,
    UpdateAckPayload,
    UpdateDeployPayload,
    UpdateProposePayload,
)
from .serializer import deserialize_event, serialize_event

__all__ = [
    # Client
    "NexusBus",
    "EventHandler",
    "STREAM_MAP",
    # Event
    "NexusEvent",
    "EventType",
    # Serializer
    "serialize_event",
    "deserialize_event",
    # Consumer
    "ConsumerManager",
    # Payload TypedDicts
    "TaskNewPayload",
    "TaskAckPayload",
    "TaskProgressPayload",
    "TaskResultPayload",
    "TaskCompletePayload",
    "TaskTimeoutPayload",
    "HealthReportPayload",
    "HealthAlertPayload",
    "FailureLoggedPayload",
    "RecoveryExecutedPayload",
    "UpdateProposePayload",
    "UpdateDeployPayload",
    "UpdateAckPayload",
    "SystemShutdownPayload",
    "TestingRunNowPayload",
    "TestingRecipeUpdatedPayload",
    "TestingCycleCompletePayload",
    "FlywheelLlmCallPayload",
    "FlywheelTestResultsPayload",
]
