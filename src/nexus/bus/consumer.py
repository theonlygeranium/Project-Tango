"""Nexus Bus consumer group management.

Manages consumer groups, reading, acknowledgement, and dead-letter routing
for Redis Streams-based event transport.
"""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as aioredis

from .event import NexusEvent
from .serializer import deserialize_event, serialize_event

logger = logging.getLogger(__name__)

# Type alias for async event handlers
EventHandler = Any  # Callable[[NexusEvent], Awaitable[None]] — resolved in client.py

DEAD_LETTER_STREAM = "nexus:dead_letter"


class ConsumerManager:
    """Manages consumer groups, reading, acknowledgement, and dead-letter routing."""

    def __init__(
        self,
        redis: aioredis.Redis,
        bot_id: str,
        namespace: str,
        streams: set[str],
        dead_letter_max_retries: int = 3,
    ) -> None:
        self._redis = redis
        self._bot_id = bot_id
        self._namespace = namespace
        self._streams = streams
        self._dead_letter_max_retries = dead_letter_max_retries
        self._group_name = f"{namespace}:consumers"

    async def ensure_groups(self) -> None:
        """Create consumer groups for all managed streams. Idempotent.

        Uses stream ID "0" so that messages published before the group was
        created are also available to consumers.
        """
        for stream in self._streams:
            full_stream = f"{self._namespace}:{stream}" if not stream.startswith(f"{self._namespace}:") else stream
            try:
                await self._redis.xgroup_create(full_stream, self._group_name, id="0")
                logger.info("Created consumer group '%s' on stream '%s'", self._group_name, full_stream)
            except aioredis.ResponseError as exc:
                if "BUSYGROUP" in str(exc):
                    logger.debug("Group '%s' already exists on stream '%s'", self._group_name, full_stream)
                else:
                    raise

    async def read_and_dispatch(
        self,
        handlers: dict[str, list[EventHandler]],
    ) -> list[tuple[NexusEvent, str, str]]:
        """Read events from all streams and return them with their message IDs and stream names.

        Args:
            handlers: Mapping of event_type to list of handler callables.

        Returns:
            List of (NexusEvent, message_id, stream_name) tuples.
        """
        # Build the stream:key mapping for XREADGROUP
        stream_keys: dict[str, str] = {}
        for stream in self._streams:
            full_stream = f"{self._namespace}:{stream}" if not stream.startswith(f"{self._namespace}:") else stream
            stream_keys[full_stream] = ">"

        results: list[tuple[NexusEvent, str, str]] = []

        try:
            response = await self._redis.xreadgroup(
                groupname=self._group_name,
                consumername=self._bot_id,
                streams=stream_keys,
                count=10,
                block=100,  # Short block to allow loop cancellation
            )
        except Exception as exc:
            logger.error("Error reading from consumer group: %s", exc)
            return results

        if not response:
            return results

        for stream_name, messages in response:
            for message_id, fields in messages:
                try:
                    event = deserialize_event(fields)
                except (ValueError, KeyError) as exc:
                    logger.error("Failed to deserialize event %s from stream %s: %s", message_id, stream_name, exc)
                    await self._move_to_dead_letter(stream_name, message_id, fields)
                    continue

                results.append((event, message_id, stream_name))

        return results

    async def increment_failure(self, stream: str, message_id: str) -> None:
        """Increment failure count for a message. Move to dead-letter if threshold exceeded.

        Args:
            stream: The full stream name where the message lives.
            message_id: The Redis stream message ID.
        """
        hash_key = f"{self._namespace}:dlq:counts:{stream}:{message_id}"
        count = await self._redis.hincrby(hash_key, "failures", 1)
        logger.warning("Message %s on stream %s has %d/%d failures", message_id, stream, count, self._dead_letter_max_retries)

        if count >= self._dead_letter_max_retries:
            await self._move_to_dead_letter(stream, message_id, None)

    async def _move_to_dead_letter(
        self,
        stream: str,
        message_id: str,
        fields: dict[str, str] | None,
    ) -> None:
        """Move a message to the nexus:dead_letter stream and ack the original.

        Args:
            stream: The source stream name.
            message_id: The Redis stream message ID.
            fields: The message fields, if already available. If None, will
                fetch from the source stream.
        """
        if fields is None:
            # Fetch the message fields from the stream
            try:
                raw = await self._redis.xrange(stream, min=message_id, max=message_id, count=1)
                if raw:
                    fields = raw[0][1]
                else:
                    logger.error("Cannot move to dead-letter: message %s not found in %s", message_id, stream)
                    return
            except Exception as exc:
                logger.error("Failed to fetch message %s for dead-letter: %s", message_id, exc)
                return

        # Add to dead-letter stream
        dlq_fields = dict(fields)
        dlq_fields["_dlq_source_stream"] = stream
        dlq_fields["_dlq_original_id"] = message_id
        await self._redis.xadd(DEAD_LETTER_STREAM, dlq_fields)
        logger.info("Moved message %s from %s to %s", message_id, stream, DEAD_LETTER_STREAM)

        # Ack the original message
        await self._redis.xack(stream, self._group_name, message_id)

        # Clean up the failure-count hash
        hash_key = f"{self._namespace}:dlq:counts:{stream}:{message_id}"
        await self._redis.delete(hash_key)

        logger.info("Dead-letter routing complete for message %s", message_id)
