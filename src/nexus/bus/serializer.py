"""Nexus Bus event serialization and deserialization.

Converts NexusEvent objects to/from flat dict[str, str] for Redis Streams XADD.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .event import NexusEvent

logger = logging.getLogger(__name__)


def serialize_event(event: NexusEvent) -> dict[str, str]:
    """Serialize a NexusEvent into a flat dict of strings for Redis XADD.

    The payload dict is JSON-serialized into a single string field.

    Args:
        event: The NexusEvent to serialize.

    Returns:
        A flat dict with keys: event_type, source, target, timestamp,
        correlation_id, payload (JSON string).
    """
    return {
        "event_type": event.event_type,
        "source": event.source,
        "target": event.target,
        "timestamp": event.timestamp,
        "correlation_id": event.correlation_id,
        "payload": json.dumps(event.payload),
    }


def deserialize_event(fields: dict[str, str]) -> NexusEvent:
    """Reconstruct a NexusEvent from Redis stream fields.

    The payload field is JSON-deserialized back into a dict.

    Args:
        fields: Flat dict of strings from Redis XREADGROUP.

    Returns:
        A NexusEvent with all fields restored.

    Raises:
        ValueError: If the payload field contains malformed JSON.
        KeyError: If required envelope fields are missing.
    """
    try:
        payload: dict[str, Any] = json.loads(fields["payload"])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Malformed JSON payload in event {fields.get('correlation_id', 'unknown')}: {exc}"
        ) from exc

    return NexusEvent(
        event_type=fields["event_type"],
        source=fields["source"],
        target=fields["target"],
        timestamp=fields["timestamp"],
        correlation_id=fields["correlation_id"],
        payload=payload,
    )
