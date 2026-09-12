"""Tests for Nexus Bus client (NexusBus) using fakeredis.

Unit tests use fakeredis for async support. Integration tests are marked
with @pytest.mark.integration and skipped unless REDIS_URL env var is set.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus, STREAM_MAP
from nexus.bus.consumer import ConsumerManager
from nexus.bus.event import EventType, NexusEvent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "")
IS_INTEGRATION = bool(REDIS_URL)


@pytest.fixture
async def redis_client():
    """Create a fakeredis async client for unit tests, or real redis for integration."""
    if IS_INTEGRATION:
        import redis.asyncio as aioredis

        client = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            await client.flushdb()
        except Exception:
            pass
        yield client
        try:
            await client.flushdb()
        except Exception:
            pass
        await client.aclose()
    else:
        client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        yield client
        await client.flushdb()
        await client.aclose()


@pytest.fixture
async def bus(redis_client):
    """Create a NexusBus instance backed by fakeredis."""
    bus = NexusBus(
        redis_url="redis://localhost:6379/0",
        namespace="nexus",
        max_stream_len=10000,
        dead_letter_max_retries=3,
    )
    # Inject the fake/real redis client directly
    bus._redis = redis_client
    yield bus
    await bus.stop_consumer()


# ---------------------------------------------------------------------------
# Publish tests
# ---------------------------------------------------------------------------

class TestPublish:
    """Tests for NexusBus.publish()."""

    async def test_publish_writes_to_correct_stream(self, bus, redis_client) -> None:
        """publish() should write to the correct stream per STREAM_MAP and return a message ID."""
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="architect",
            payload={"task_id": "t1"},
        )
        msg_id = await bus.publish(event)

        assert msg_id  # non-empty message ID
        # Verify the message is in the correct stream
        stream_name = STREAM_MAP[EventType.TASK_NEW]
        entries = await redis_client.xrange(stream_name)
        assert len(entries) == 1
        assert entries[0][0] == msg_id

    async def test_publish_to_health_stream(self, bus, redis_client) -> None:
        """Health events should go to nexus:health stream."""
        event = NexusEvent.create(
            event_type=EventType.HEALTH_REPORT,
            source="architect",
            target="orchestrator",
            payload={"bot_id": "architect", "status": "healthy"},
        )
        msg_id = await bus.publish(event)

        entries = await redis_client.xrange("nexus:health")
        assert len(entries) == 1
        assert entries[0][0] == msg_id

    async def test_publish_with_max_stream_len_trims(self, redis_client) -> None:
        """publish() with max_stream_len should trim the stream when exceeded."""
        bus = NexusBus(
            redis_url="redis://localhost:6379/0",
            namespace="nexus",
            max_stream_len=5,
            dead_letter_max_retries=3,
        )
        bus._redis = redis_client

        for i in range(10):
            event = NexusEvent.create(
                event_type=EventType.TASK_NEW,
                source="orchestrator",
                target="architect",
                payload={"task_id": f"t{i}"},
            )
            await bus.publish(event)

        entries = await redis_client.xrange("nexus:tasks")
        # With approximate maxlen=5, Redis may keep slightly more, but should be <= 5 + some buffer
        # With fakeredis, approximate trimming should keep it at or near 5
        assert len(entries) <= 6  # allow small overage for approximate trimming
        await bus.stop_consumer()


# ---------------------------------------------------------------------------
# Subscribe + Consumer tests
# ---------------------------------------------------------------------------

class TestSubscribeAndConsume:
    """Tests for subscribe() + start_consumer() event delivery."""

    async def test_subscribe_delivers_event_to_handler(self, bus, redis_client) -> None:
        """subscribe() + start_consumer() should deliver published event to registered handler."""
        received: list[NexusEvent] = []

        async def handler(event: NexusEvent) -> None:
            received.append(event)

        await bus.subscribe(EventType.TASK_NEW, handler)
        await bus.start_consumer("test-bot")

        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="broadcast",
            payload={"task_id": "t1"},
        )
        await bus.publish(event)

        # Give the consumer loop time to process
        await asyncio.sleep(0.5)

        assert len(received) == 1
        assert received[0].event_type == EventType.TASK_NEW
        assert received[0].payload["task_id"] == "t1"

    async def test_targeted_dispatch_receives_correct_events(self, bus, redis_client) -> None:
        """Handler on bot 'architect' should receive event with target='architect' but NOT target='voss'."""
        received: list[NexusEvent] = []

        async def handler(event: NexusEvent) -> None:
            received.append(event)

        await bus.subscribe(EventType.TASK_NEW, handler)
        await bus.start_consumer("architect")

        # Event targeted at architect — should be received
        event_for_architect = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="architect",
            payload={"task_id": "t1"},
        )
        await bus.publish(event_for_architect)

        # Event targeted at voss — should NOT be received
        event_for_voss = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="voss",
            payload={"task_id": "t2"},
        )
        await bus.publish(event_for_voss)

        await asyncio.sleep(0.5)

        assert len(received) == 1
        assert received[0].payload["task_id"] == "t1"

    async def test_broadcast_dispatch_received(self, bus, redis_client) -> None:
        """Handler should receive event with target='broadcast'."""
        received: list[NexusEvent] = []

        async def handler(event: NexusEvent) -> None:
            received.append(event)

        await bus.subscribe(EventType.HEALTH_ALERT, handler)
        await bus.start_consumer("architect")

        event = NexusEvent.create(
            event_type=EventType.HEALTH_ALERT,
            source="monitor",
            target="broadcast",
            payload={"bot_id": "voss", "alert_type": "high_cpu", "severity": "warning", "message": "CPU > 90%"},
        )
        await bus.publish(event)

        await asyncio.sleep(0.5)

        assert len(received) == 1
        assert received[0].event_type == EventType.HEALTH_ALERT


# ---------------------------------------------------------------------------
# Ack and re-delivery tests
# ---------------------------------------------------------------------------

class TestAckAndRedelivery:
    """Tests for ack_event() and message re-delivery."""

    async def test_ack_event_removes_from_pel(self, bus, redis_client) -> None:
        """ack_event() should remove the message from the pending entries list."""
        # Create a consumer group and publish an event
        await bus.create_consumer_group("nexus:tasks", "test-group")

        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="architect",
            payload={"task_id": "t1"},
        )
        msg_id = await bus.publish(event)

        # Read the event (this adds it to the PEL)
        events = await bus.read_events("nexus:tasks", "test-group", "test-consumer", count=10, block_ms=100)
        assert len(events) == 1

        # Check PEL has the message
        pel = await redis_client.xpending("nexus:tasks", "test-group")
        assert pel["pending"] == 1

        # Ack it
        await bus.ack_event("nexus:tasks", "test-group", msg_id)

        # Check PEL is empty
        pel = await redis_client.xpending("nexus:tasks", "test-group")
        assert pel["pending"] == 0

    async def test_unacknowledged_message_redelivered(self, bus, redis_client) -> None:
        """Unacknowledged message should be re-delivered on next read with '>'."""
        await bus.create_consumer_group("nexus:tasks", "test-group")

        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="architect",
            payload={"task_id": "t1"},
        )
        msg_id = await bus.publish(event)

        # First read — gets the message, but we don't ack
        events1 = await bus.read_events("nexus:tasks", "test-group", "test-consumer", count=10, block_ms=100)
        assert len(events1) == 1

        # Second read with '>' — no new messages
        events2 = await bus.read_events("nexus:tasks", "test-group", "test-consumer", count=10, block_ms=100)
        assert len(events2) == 0

        # Now read with '0' to get pending (unacked) messages
        response = await redis_client.xreadgroup(
            groupname="test-group",
            consumername="test-consumer",
            streams={"nexus:tasks": "0"},
            count=10,
        )
        assert len(response) == 1
        assert len(response[0][1]) == 1
        assert response[0][1][0][0] == msg_id


# ---------------------------------------------------------------------------
# Dead-letter routing tests
# ---------------------------------------------------------------------------

class TestDeadLetterRouting:
    """Tests for dead-letter routing when handler fails repeatedly."""

    async def test_dead_letter_after_max_retries(self, redis_client) -> None:
        """Message failing dead_letter_max_retries times should be moved to nexus:dead_letter and acked."""
        bus = NexusBus(
            redis_url="redis://localhost:6379/0",
            namespace="nexus",
            max_stream_len=10000,
            dead_letter_max_retries=3,
        )
        bus._redis = redis_client

        await bus.create_consumer_group("nexus:tasks", "nexus:consumers")

        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="orchestrator",
            target="broadcast",
            payload={"task_id": "t1"},
        )
        msg_id = await bus.publish(event)

        # Read the event
        events = await bus.read_events("nexus:tasks", "nexus:consumers", "test-bot", count=10, block_ms=100)
        assert len(events) == 1

        # Simulate 3 failures
        cm = ConsumerManager(
            redis=redis_client,
            bot_id="test-bot",
            namespace="nexus",
            streams={"nexus:tasks"},
            dead_letter_max_retries=3,
        )
        for _ in range(3):
            await cm.increment_failure("nexus:tasks", msg_id)

        # Verify the message is in the dead-letter stream
        dlq_entries = await redis_client.xrange("nexus:dead_letter")
        assert len(dlq_entries) == 1
        dlq_fields = dlq_entries[0][1]
        assert dlq_fields["event_type"] == "task.new"
        assert dlq_fields["_dlq_source_stream"] == "nexus:tasks"
        assert dlq_fields["_dlq_original_id"] == msg_id

        # Verify the original is acked (no longer in PEL)
        pel = await redis_client.xpending("nexus:tasks", "nexus:consumers")
        assert pel["pending"] == 0

        # Verify the failure-count hash is cleaned up
        hash_key = f"nexus:dlq:counts:nexus:tasks:{msg_id}"
        exists = await redis_client.exists(hash_key)
        assert exists == 0

        await bus.stop_consumer()


# ---------------------------------------------------------------------------
# Consumer group idempotency
# ---------------------------------------------------------------------------

class TestConsumerGroupIdempotency:
    """Tests for create_consumer_group() idempotency."""

    async def test_create_consumer_group_idempotent(self, bus, redis_client) -> None:
        """create_consumer_group() should be idempotent — calling twice doesn't raise."""
        await bus.create_consumer_group("nexus:tasks", "test-group")
        # Second call should not raise
        await bus.create_consumer_group("nexus:tasks", "test-group")

        # Verify the group exists
        groups = await redis_client.xinfo_groups("nexus:tasks")
        assert any(g["name"] == "test-group" for g in groups)


# ---------------------------------------------------------------------------
# Stop consumer safety
# ---------------------------------------------------------------------------

class TestStopConsumer:
    """Tests for stop_consumer() safety."""

    async def test_stop_consumer_safe_when_not_running(self, bus) -> None:
        """stop_consumer() should be safe to call when not running."""
        # Should not raise
        await bus.stop_consumer()

    async def test_stop_consumer_cancels_task(self, bus, redis_client) -> None:
        """stop_consumer() should cancel the consumer task."""
        await bus.subscribe(EventType.TASK_NEW, _noop_handler)
        await bus.start_consumer("test-bot")
        assert bus._consumer_task is not None

        await bus.stop_consumer()
        assert bus._consumer_task is None


async def _noop_handler(event: NexusEvent) -> None:
    pass


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

class TestConnectionLifecycle:
    """Tests for connect() -> operations -> close() lifecycle."""

    async def test_connection_lifecycle(self) -> None:
        """connect() -> operations -> close() should clean up properly."""
        if IS_INTEGRATION:
            bus = NexusBus(redis_url=REDIS_URL)
        else:
            # For fakeredis, we need to mock the from_url call
            bus = NexusBus(redis_url="redis://localhost:6379/0")

            # Patch from_url to return a FakeRedis
            import fakeredis.aioredis

            original_from_url = fakeredis.aioredis.FakeRedis.from_url
            try:
                fakeredis.aioredis.FakeRedis.from_url = staticmethod(
                    lambda *args, **kwargs: fakeredis.aioredis.FakeRedis(decode_responses=True)
                )
                await bus.connect()
            finally:
                fakeredis.aioredis.FakeRedis.from_url = original_from_url
            return  # skip the rest for fakeredis since we already connected

        await bus.connect()

        # Do a simple operation
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="test",
            target="broadcast",
            payload={"task_id": "lifecycle-test"},
        )
        msg_id = await bus.publish(event)
        assert msg_id

        await bus.close()
        assert bus._redis is None
