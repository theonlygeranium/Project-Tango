"""Tests for Nexus Bus event definitions and serialization."""

from __future__ import annotations

from datetime import datetime

import pytest

from nexus.bus.event import (
    EventType,
    FailureLoggedPayload,
    FlywheelLlmCallPayload,
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
from nexus.bus.serializer import deserialize_event, serialize_event


class TestNexusEventCreation:
    """Tests for NexusEvent.create() factory method."""

    def test_create_stamps_timestamp_and_correlation_id(self) -> None:
        """create() should auto-generate timestamp and correlation_id."""
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="architect",
            payload={"task_id": "t1", "task_type": "design"},
        )
        assert event.event_type == "task.new"
        assert event.source == "orchestrator"
        assert event.target == "architect"
        assert event.correlation_id  # non-empty
        # Timestamp should be valid ISO-8601
        parsed = datetime.fromisoformat(event.timestamp)
        assert parsed.tzinfo is not None  # should have timezone info

    def test_create_preserves_supplied_correlation_id(self) -> None:
        """create() should use caller-supplied correlation_id when provided."""
        custom_id = "my-custom-correlation-id"
        event = NexusEvent.create(
            event_type=EventType.HEALTH_REPORT,
            source="architect",
            target="orchestrator",
            payload={"bot_id": "architect", "status": "healthy"},
            correlation_id=custom_id,
        )
        assert event.correlation_id == custom_id


class TestEventTypeConstants:
    """Tests for EventType string constants."""

    def test_core_task_event_types(self) -> None:
        assert EventType.TASK_NEW == "task.new"
        assert EventType.TASK_ACK == "task.ack"
        assert EventType.TASK_PROGRESS == "task.progress"
        assert EventType.TASK_RESULT == "task.result"
        assert EventType.TASK_COMPLETE == "task.complete"
        assert EventType.TASK_TIMEOUT == "task.timeout"

    def test_health_event_types(self) -> None:
        assert EventType.HEALTH_REPORT == "health.report"
        assert EventType.HEALTH_ALERT == "health.alert"

    def test_failure_recovery_event_types(self) -> None:
        assert EventType.FAILURE_LOGGED == "failure.logged"
        assert EventType.RECOVERY_EXECUTED == "recovery.executed"

    def test_update_event_types(self) -> None:
        assert EventType.UPDATE_PROPOSE == "update.propose"
        assert EventType.UPDATE_DEPLOY == "update.deploy"
        assert EventType.UPDATE_ACK == "update.ack"

    def test_system_event_types(self) -> None:
        assert EventType.SYSTEM_SHUTDOWN == "system.shutdown"

    def test_testing_event_types(self) -> None:
        assert EventType.TESTING_RUN_NOW == "testing.run_now"
        assert EventType.TESTING_RECIPE_UPDATED == "testing.recipe_updated"
        assert EventType.TESTING_CYCLE_COMPLETE == "testing.cycle_complete"

    def test_flywheel_event_types(self) -> None:
        assert EventType.FLYWHEEL_LLM_CALL == "flywheel.llm_call"
        assert EventType.FLYWHEEL_TEST_RESULTS == "flywheel.test_results"


class TestSerialization:
    """Tests for serialize_event / deserialize_event round-trips."""

    def test_serialize_produces_flat_dict_of_strings(self) -> None:
        """serialize_event() should produce a flat dict[str, str] with all six envelope fields."""
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="architect",
            payload={"task_id": "t1", "task_type": "design"},
        )
        serialized = serialize_event(event)

        assert isinstance(serialized, dict)
        assert all(isinstance(v, str) for v in serialized.values())
        assert set(serialized.keys()) == {
            "event_type", "source", "target", "timestamp",
            "correlation_id", "payload",
        }
        assert serialized["event_type"] == "task.new"
        assert serialized["source"] == "orchestrator"
        assert serialized["target"] == "architect"

    def test_deserialize_round_trips_to_equal_event(self) -> None:
        """deserialize_event() should reconstruct an equal NexusEvent."""
        original = NexusEvent.create(
            event_type=EventType.HEALTH_REPORT,
            source="architect",
            target="orchestrator",
            payload={"bot_id": "architect", "status": "healthy", "uptime_seconds": 3600},
        )
        serialized = serialize_event(original)
        restored = deserialize_event(serialized)

        assert restored.event_type == original.event_type
        assert restored.source == original.source
        assert restored.target == original.target
        assert restored.timestamp == original.timestamp
        assert restored.correlation_id == original.correlation_id
        assert restored.payload == original.payload

    def test_round_trip_preserves_nested_payload_structures(self) -> None:
        """Round-trip should preserve nested dicts, lists, and mixed structures."""
        original = NexusEvent.create(
            event_type=EventType.FAILURE_LOGGED,
            source="voss",
            target="orchestrator",
            payload={
                "bot_id": "voss",
                "failure_type": "timeout",
                "error_message": "Request timed out",
                "stack_trace": "Traceback (most recent call last):\n  ...",
                "context": {
                    "nested_dict": {"key": "value", "number": 42},
                    "nested_list": [1, 2, 3, {"inner": "data"}],
                    "mixed": [{"a": 1}, {"b": [2, 3]}],
                },
            },
        )
        serialized = serialize_event(original)
        restored = deserialize_event(serialized)

        assert restored.payload == original.payload
        assert restored.payload["context"]["nested_dict"] == {"key": "value", "number": 42}
        assert restored.payload["context"]["nested_list"] == [1, 2, 3, {"inner": "data"}]
        assert restored.payload["context"]["mixed"] == [{"a": 1}, {"b": [2, 3]}]

    def test_deserialize_raises_on_malformed_json_payload(self) -> None:
        """deserialize_event() should raise ValueError on malformed JSON."""
        fields = {
            "event_type": "task.new",
            "source": "orchestrator",
            "target": "architect",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "correlation_id": "test-id",
            "payload": "{not valid json",
        }
        with pytest.raises(ValueError, match="Malformed JSON payload"):
            deserialize_event(fields)


class TestPayloadTypedDictsImportable:
    """Verify all payload TypedDicts are importable."""

    def test_all_payload_typeddicts_importable(self) -> None:
        # Just verify they're all valid types by referencing them
        _ = TaskNewPayload
        _ = TaskAckPayload
        _ = TaskProgressPayload
        _ = TaskResultPayload
        _ = TaskCompletePayload
        _ = TaskTimeoutPayload
        _ = HealthReportPayload
        _ = HealthAlertPayload
        _ = FailureLoggedPayload
        _ = RecoveryExecutedPayload
        _ = UpdateProposePayload
        _ = UpdateDeployPayload
        _ = UpdateAckPayload
        _ = SystemShutdownPayload
        _ = TestingRunNowPayload
        _ = TestingRecipeUpdatedPayload
        _ = TestingCycleCompletePayload
        _ = FlywheelLlmCallPayload
        _ = FlywheelTestResultsPayload
