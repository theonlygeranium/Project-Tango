"""Nexus Bus async client.

Wraps redis.asyncio to provide a high-level event publishing/subscribing
API for the Nexus Fleet.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from .consumer import ConsumerManager
from .event import EventType, NexusEvent
from .serializer import deserialize_event, serialize_event

logger = logging.getLogger(__name__)

# Type alias for async event handlers
EventHandler = Callable[[NexusEvent], Awaitable[None]]

# Mapping of event types to their streams
STREAM_MAP: dict[str, str] = {
    # Task lifecycle
    EventType.TASK_NEW: "nexus:tasks",
    EventType.TASK_ACK: "nexus:tasks",
    EventType.TASK_PROGRESS: "nexus:tasks",
    EventType.TASK_RESULT: "nexus:tasks",
    EventType.TASK_COMPLETE: "nexus:tasks",
    EventType.TASK_TIMEOUT: "nexus:tasks",
    # Health
    EventType.HEALTH_REPORT: "nexus:health",
    EventType.HEALTH_ALERT: "nexus:health",
    # Failure and recovery
    EventType.FAILURE_LOGGED: "nexus:failures",
    EventType.RECOVERY_EXECUTED: "nexus:failures",
    # Updates
    EventType.UPDATE_PROPOSE: "nexus:updates",
    EventType.UPDATE_DEPLOY: "nexus:updates",
    EventType.UPDATE_ACK: "nexus:updates",
    # System
    EventType.SYSTEM_SHUTDOWN: "nexus:system",
    # Testing
    EventType.TESTING_RUN_NOW: "nexus:testing",
    EventType.TESTING_RECIPE_UPDATED: "nexus:testing",
    EventType.TESTING_CYCLE_COMPLETE: "nexus:testing",
    # Flywheel
    EventType.FLYWHEEL_LLM_CALL: "nexus:flywheel",
    EventType.FLYWHEEL_TEST_RESULTS: "nexus:flywheel",
}

# Reverse mapping: stream name -> set of event types (for consumer group setup)
_STREAM_TO_EVENT_TYPES: dict[str, set[str]] = {}
for _et, _stream in STREAM_MAP.items():
    _STREAM_TO_EVENT_TYPES.setdefault(_stream, set()).add(_et)


class NexusBus:
    """Async client for the Nexus Bus event transport.

    Wraps redis.asyncio to provide publish/subscribe semantics on top of
    Redis Streams with consumer groups, dead-letter routing, and automatic
    reconnection.

    Args:
        redis_url: Redis connection URL (e.g. "redis://localhost:6379/0").
        namespace: Stream namespace prefix (default "nexus").
        max_stream_len: Maximum number of messages per stream (XADD maxlen).
        dead_letter_max_retries: Failures before a message is dead-lettered.
    """

    def __init__(
        self,
        redis_url: str,
        namespace: str = "nexus",
        max_stream_len: int = 10000,
        dead_letter_max_retries: int = 3,
    ) -> None:
        self._redis_url = redis_url
        self._namespace = namespace
        self._max_stream_len = max_stream_len
        self._dead_letter_max_retries = dead_letter_max_retries
        self._redis: aioredis.Redis | None = None
        self._handlers: dict[str, list[EventHandler]] = {}
        self._consumer_manager: ConsumerManager | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._bot_id: str | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create the Redis async client and verify connectivity with a ping."""
        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            socket_timeout=5.0,
            socket_keepalive=True,
            retry_on_timeout=True,
        )
        try:
            await self._redis.ping()
            logger.info("NexusBus connected to Redis at %s", self._redis_url)
        except Exception as exc:
            logger.error("Failed to connect to Redis: %s", exc)
            raise

    async def close(self) -> None:
        """Stop the consumer loop and close the Redis connection."""
        await self.stop_consumer()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
            logger.info("NexusBus Redis connection closed")

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, event: NexusEvent) -> str:
        """Publish an event to the appropriate stream.

        Args:
            event: The NexusEvent to publish.

        Returns:
            The Redis stream message ID.

        Raises:
            ValueError: If the event_type is not in STREAM_MAP.
            RuntimeError: If not connected.
        """
        if self._redis is None:
            raise RuntimeError("NexusBus not connected — call connect() first")

        stream = STREAM_MAP.get(event.event_type)
        if stream is None:
            raise ValueError(f"Unknown event type: {event.event_type}")

        fields = serialize_event(event)
        message_id = await self._redis.xadd(
            stream,
            fields,
            maxlen=self._max_stream_len,
            approximate=True,
        )
        logger.debug("Published event %s to stream %s (id=%s)", event.event_type, stream, message_id)
        return message_id

    # ------------------------------------------------------------------
    # Subscribing
    # ------------------------------------------------------------------

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type.

        Args:
            event_type: The event type to listen for (must be in STREAM_MAP).
            handler: An async callable that receives a NexusEvent.

        Raises:
            ValueError: If the event_type is not in STREAM_MAP.
        """
        if event_type not in STREAM_MAP:
            raise ValueError(f"Unknown event type: {event_type}")
        self._handlers.setdefault(event_type, []).append(handler)
        logger.info("Subscribed handler for event type '%s'", event_type)

    async def unsubscribe(self, event_type: str) -> None:
        """Remove all handlers for an event type.

        Args:
            event_type: The event type to unsubscribe from.
        """
        if event_type in self._handlers:
            del self._handlers[event_type]
            logger.info("Unsubscribed from event type '%s'", event_type)

    # ------------------------------------------------------------------
    # Consumer management
    # ------------------------------------------------------------------

    async def start_consumer(self, bot_id: str) -> None:
        """Start the background consumer loop for this bot.

        Args:
            bot_id: The unique identifier for this consumer/bot.
        """
        if self._redis is None:
            raise RuntimeError("NexusBus not connected — call connect() first")

        self._bot_id = bot_id

        # Determine which streams we need based on registered handlers
        managed_streams: set[str] = set()
        for event_type in self._handlers:
            stream = STREAM_MAP.get(event_type)
            if stream:
                managed_streams.add(stream)

        self._consumer_manager = ConsumerManager(
            redis=self._redis,
            bot_id=bot_id,
            namespace=self._namespace,
            streams=managed_streams,
            dead_letter_max_retries=self._dead_letter_max_retries,
        )
        await self._consumer_manager.ensure_groups()

        self._running = True
        self._consumer_task = asyncio.create_task(self._consumer_loop())
        logger.info("Started consumer for bot '%s' on streams: %s", bot_id, managed_streams)

    async def stop_consumer(self) -> None:
        """Cancel the consumer loop task. Safe to call when not running."""
        self._running = False
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
            logger.info("Consumer task cancelled")
        self._consumer_manager = None

    async def _consumer_loop(self) -> None:
        """Background loop that reads events and dispatches to handlers.

        Handles reconnection with exponential backoff and jitter.
        """
        backoff = 1.0
        max_backoff = 30.0

        while self._running:
            try:
                if self._consumer_manager is None:
                    break

                events = await self._consumer_manager.read_and_dispatch(self._handlers)

                for event, message_id, stream_name in events:
                    await self._dispatch(event, message_id, stream_name)

                if not events:
                    # No events found — yield control to avoid busy-waiting
                    await asyncio.sleep(0.05)

                # Reset backoff on success
                backoff = 1.0

            except asyncio.CancelledError:
                logger.info("Consumer loop cancelled")
                break
            except aioredis.ConnectionError as exc:
                logger.error("Redis connection error in consumer loop: %s", exc)
                await self._reconnect(backoff)
                backoff = min(backoff * 2, max_backoff)
            except Exception as exc:
                logger.error("Unexpected error in consumer loop: %s", exc)
                await asyncio.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)

    async def _dispatch(self, event: NexusEvent, message_id: str, stream_name: str) -> None:
        """Dispatch an event to registered handlers.

        Filters on event.target — only delivers if target is bot_id or "broadcast".
        On handler exception, increments failure count (may dead-letter).

        Args:
            event: The deserialized NexusEvent.
            message_id: The Redis stream message ID.
            stream_name: The stream the message came from.
        """
        # Target filtering
        if event.target != "broadcast" and event.target != self._bot_id:
            # Not for us — ack and skip
            if self._consumer_manager is not None and self._redis is not None:
                await self._redis.xack(stream_name, self._consumer_manager._group_name, message_id)
            return

        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            # No handlers — ack to remove from PEL
            if self._consumer_manager is not None and self._redis is not None:
                await self._redis.xack(stream_name, self._consumer_manager._group_name, message_id)
            return

        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                logger.error("Handler %s failed for event %s: %s", handler, event.event_type, exc)
                if self._consumer_manager is not None:
                    await self._consumer_manager.increment_failure(stream_name, message_id)
                return

        # All handlers succeeded — ack
        if self._consumer_manager is not None and self._redis is not None:
            await self._redis.xack(stream_name, self._consumer_manager._group_name, message_id)

    async def _reconnect(self, backoff: float) -> None:
        """Attempt to reconnect to Redis with exponential backoff and jitter.

        Args:
            backoff: Current backoff time in seconds.
        """
        jitter = random.uniform(0, 0.5)
        sleep_time = backoff + jitter
        logger.info("Attempting reconnect in %.2fs", sleep_time)
        await asyncio.sleep(sleep_time)

        try:
            if self._redis is not None:
                await self._redis.aclose()
        except Exception:
            pass

        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_timeout=5.0,
                socket_keepalive=True,
                retry_on_timeout=True,
            )
            await self._redis.ping()
            logger.info("Reconnected to Redis")
        except Exception as exc:
            logger.error("Reconnect failed: %s", exc)

    # ------------------------------------------------------------------
    # Low-level stream operations
    # ------------------------------------------------------------------

    async def create_consumer_group(self, stream: str, group: str) -> None:
        """Create a consumer group on a stream. Idempotent.

        Args:
            stream: The stream name.
            group: The consumer group name.
        """
        if self._redis is None:
            raise RuntimeError("NexusBus not connected — call connect() first")

        try:
            await self._redis.xgroup_create(stream, group, id="0")
            logger.info("Created consumer group '%s' on stream '%s'", group, stream)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug("Group '%s' already exists on stream '%s'", group, stream)
            else:
                raise

    async def read_events(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[NexusEvent]:
        """Read events from a stream via a consumer group.

        Args:
            stream: The stream name.
            group: The consumer group name.
            consumer: The consumer name.
            count: Maximum number of events to read.
            block_ms: Milliseconds to block waiting for new events.

        Returns:
            List of deserialized NexusEvent objects.
        """
        if self._redis is None:
            raise RuntimeError("NexusBus not connected — call connect() first")

        response = await self._redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )

        events: list[NexusEvent] = []
        for _stream_name, messages in response:
            for _message_id, fields in messages:
                try:
                    events.append(deserialize_event(fields))
                except (ValueError, KeyError) as exc:
                    logger.error("Failed to deserialize event from stream %s: %s", stream, exc)

        return events

    async def ack_event(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge a message in a consumer group's PEL.

        Args:
            stream: The stream name.
            group: The consumer group name.
            message_id: The Redis stream message ID to acknowledge.
        """
        if self._redis is None:
            raise RuntimeError("NexusBus not connected — call connect() first")

        await self._redis.xack(stream, group, message_id)
        logger.debug("Acked message %s on stream %s", message_id, stream)
