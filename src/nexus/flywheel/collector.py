"""Failure event collector for the data flywheel.

Subscribes to failure.logged, recovery.executed, and flywheel.llm_call
events on the Nexus Bus and stores them in Redis lists for analysis
by Dr. Cortex's weekly analysis engine.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FailureEvent:
    """A failure event captured from the Nexus Bus."""

    failure_id: str
    bot_id: str
    dependency: str
    failure_type: str
    error_message: str
    context: dict[str, Any]
    outcome: str
    timestamp: str


@dataclass
class RecoveryEvent:
    """A recovery event captured from the Nexus Bus."""

    failure_id: str
    bot_id: str
    strategy: str
    result: str
    detail: str
    timestamp: str


@dataclass
class LLMCallEvent:
    """An LLM call event captured from the Nexus Bus."""

    call_id: str
    bot_id: str
    model: str
    success: bool
    latency_ms: float
    token_count: int
    timestamp: str


# ---------------------------------------------------------------------------
# Redis key constants
# ---------------------------------------------------------------------------

FAILURE_KEY = "nexus:flywheel:failures"
RECOVERY_KEY = "nexus:flywheel:recoveries"
LLM_CALL_KEY = "nexus:flywheel:llm_calls"


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

class FailureEventCollector:
    """Subscribes to failure.logged, recovery.executed, and flywheel.llm_call events.

    Stores them in Redis lists for analysis by Dr. Cortex.
    """

    def __init__(self, nexus: NexusBus, redis_client: Any | None = None) -> None:
        self._nexus = nexus
        self._redis = redis_client or nexus._redis
        if self._redis is None:
            raise RuntimeError("Redis client required — connect NexusBus first")
        self._subscribed = False

    async def start(self) -> None:
        """Subscribe to failure.logged, recovery.executed, flywheel.llm_call."""
        await self._nexus.subscribe(EventType.FAILURE_LOGGED, self.handle_failure)
        await self._nexus.subscribe(EventType.RECOVERY_EXECUTED, self.handle_recovery)
        await self._nexus.subscribe(EventType.FLYWHEEL_LLM_CALL, self.handle_llm_call)
        self._subscribed = True
        logger.info("FailureEventCollector started")

    async def stop(self) -> None:
        """Unsubscribe from all event types."""
        if not self._subscribed:
            return
        await self._nexus.unsubscribe(EventType.FAILURE_LOGGED)
        await self._nexus.unsubscribe(EventType.RECOVERY_EXECUTED)
        await self._nexus.unsubscribe(EventType.FLYWHEEL_LLM_CALL)
        self._subscribed = False
        logger.info("FailureEventCollector stopped")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def handle_failure(self, event: NexusEvent) -> None:
        """Handle a failure.logged event — store as FailureEvent."""
        p = event.payload
        failure = FailureEvent(
            failure_id=str(uuid4()),
            bot_id=p.get("bot_id", "unknown"),
            dependency=p.get("dependency", p.get("failure_type", "unknown")),
            failure_type=p.get("failure_type", "unknown"),
            error_message=p.get("error_message", ""),
            context=p.get("context", {}),
            outcome=p.get("outcome", "unrecovered"),
            timestamp=event.timestamp,
        )
        await self._redis.rpush(FAILURE_KEY, json.dumps(asdict(failure)))
        logger.debug("Stored failure event for bot %s", failure.bot_id)

    async def handle_recovery(self, event: NexusEvent) -> None:
        """Handle a recovery.executed event — store as RecoveryEvent."""
        p = event.payload
        details = p.get("details", {})
        recovery = RecoveryEvent(
            failure_id=p.get("failure_id", str(uuid4())),
            bot_id=p.get("bot_id", "unknown"),
            strategy=p.get("recovery_action", details.get("strategy", "unknown")),
            result="recovered" if p.get("success", False) else "failed",
            detail=details.get("detail", p.get("error_message", "")),
            timestamp=event.timestamp,
        )
        await self._redis.rpush(RECOVERY_KEY, json.dumps(asdict(recovery)))
        logger.debug("Stored recovery event for bot %s", recovery.bot_id)

    async def handle_llm_call(self, event: NexusEvent) -> None:
        """Handle a flywheel.llm_call event — store as LLMCallEvent."""
        p = event.payload
        prompt_tokens = p.get("prompt_tokens", 0)
        completion_tokens = p.get("completion_tokens", 0)
        call = LLMCallEvent(
            call_id=str(uuid4()),
            bot_id=p.get("bot_id", "unknown"),
            model=p.get("model", "unknown"),
            success=p.get("success", True),
            latency_ms=float(p.get("latency_ms", 0)),
            token_count=int(prompt_tokens) + int(completion_tokens),
            timestamp=event.timestamp,
        )
        await self._redis.rpush(LLM_CALL_KEY, json.dumps(asdict(call)))
        logger.debug("Stored LLM call event for model %s", call.model)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def get_failures(
        self, bot_id: str | None = None, since: str | None = None
    ) -> list[FailureEvent]:
        """Retrieve stored failure events, optionally filtered by bot_id and/or since timestamp."""
        raw = await self._redis.lrange(FAILURE_KEY, 0, -1)
        events: list[FailureEvent] = []
        for item in raw:
            data = json.loads(item)
            if bot_id is not None and data["bot_id"] != bot_id:
                continue
            if since is not None and data["timestamp"] < since:
                continue
            events.append(FailureEvent(**data))
        return events

    async def get_recoveries(
        self, bot_id: str | None = None, since: str | None = None
    ) -> list[RecoveryEvent]:
        """Retrieve stored recovery events, optionally filtered by bot_id and/or since timestamp."""
        raw = await self._redis.lrange(RECOVERY_KEY, 0, -1)
        events: list[RecoveryEvent] = []
        for item in raw:
            data = json.loads(item)
            if bot_id is not None and data["bot_id"] != bot_id:
                continue
            if since is not None and data["timestamp"] < since:
                continue
            events.append(RecoveryEvent(**data))
        return events

    async def get_llm_calls(
        self, bot_id: str | None = None, since: str | None = None
    ) -> list[LLMCallEvent]:
        """Retrieve stored LLM call events, optionally filtered by bot_id and/or since timestamp."""
        raw = await self._redis.lrange(LLM_CALL_KEY, 0, -1)
        events: list[LLMCallEvent] = []
        for item in raw:
            data = json.loads(item)
            if bot_id is not None and data["bot_id"] != bot_id:
                continue
            if since is not None and data["timestamp"] < since:
                continue
            events.append(LLMCallEvent(**data))
        return events
