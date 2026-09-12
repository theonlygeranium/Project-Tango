"""Recovery Engine — retry / fallback / escalate ladder for failure handling.

When a bot operation fails, the RecoveryEngine attempts recovery through a
three-rung ladder:
1. Retry with exponential backoff
2. Fallback to a degraded response
3. Escalate to a human or supervisor

All failures and recovery outcomes are published to the Nexus Bus.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.self_healing.circuit_breaker import CircuitBreakerManager, CircuitOpenError
from nexus.self_healing.checkpoint import CheckpointManager
from nexus.self_healing.remediation_actions import RemediationActions
from nexus.self_healing.semantic_breaker import SemanticBreaker

logger = logging.getLogger(__name__)


class FailureType(Enum):
    LLM_FAILURE = "llm_failure"
    TOOL_FAILURE = "tool_failure"
    DISCORD_FAILURE = "discord_failure"
    SEMANTIC_LOOP = "semantic_loop"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


class RecoveryOutcome(Enum):
    RETRIED = "retried"
    FELL_BACK = "fell_back"
    ESCALATED = "escalated"
    UNRECOVERED = "unrecovered"


@dataclass
class Failure:
    failure_id: str
    source: str
    error_type: str
    error_message: str
    context: dict[str, Any]
    timestamp: str


@dataclass
class RecoveryResult:
    failure: Failure
    outcome: RecoveryOutcome
    strategy: str
    detail: str
    retried: bool


class RecoveryEngine:
    """Handles failures through a retry -> fallback -> escalate ladder."""

    def __init__(
        self,
        bot_id: str,
        breaker_manager: CircuitBreakerManager,
        semantic_breaker: SemanticBreaker,
        checkpoint_manager: CheckpointManager,
        remediation_actions: RemediationActions,
        nexus_bus: NexusBus,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        self._bot_id = bot_id
        self._breaker_manager = breaker_manager
        self._semantic_breaker = semantic_breaker
        self._checkpoint_manager = checkpoint_manager
        self._remediation_actions = remediation_actions
        self._nexus_bus = nexus_bus
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff

    async def handle_failure(
        self,
        source: str,
        error_type: str,
        error_message: str,
        context: dict[str, Any],
    ) -> RecoveryResult:
        """Handle a failure through the recovery ladder."""
        failure = Failure(
            failure_id=str(uuid4()),
            source=source,
            error_type=error_type,
            error_message=error_message,
            context=context,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        await self._publish_failure_logged(failure)

        # Determine failure type
        ftype = self._classify_failure(error_type, error_message)

        # Circuit open failures go straight to fallback/escalate
        if ftype == FailureType.CIRCUIT_OPEN:
            result = await self._fallback(failure)
            if result.outcome == RecoveryOutcome.UNRECOVERED:
                result = await self._escalate(failure)
            return result

        # Semantic loops go straight to escalate
        if ftype == FailureType.SEMANTIC_LOOP:
            return await self._escalate(failure)

        # Normal ladder: retry -> fallback -> escalate
        result = await self._retry(failure)
        if result.outcome == RecoveryOutcome.UNRECOVERED:
            result = await self._fallback(failure)
        if result.outcome == RecoveryOutcome.UNRECOVERED:
            result = await self._escalate(failure)

        await self._publish_recovery_executed(failure, result)
        return result

    async def _retry(self, failure: Failure) -> RecoveryResult:
        """Attempt to retry the failed operation with exponential backoff."""
        retry_fn = failure.context.get("retry_fn")
        if retry_fn is None:
            return RecoveryResult(
                failure=failure,
                outcome=RecoveryOutcome.UNRECOVERED,
                strategy="retry",
                detail="No retry function provided in context",
                retried=False,
            )

        last_error = failure.error_message
        for attempt in range(self._max_retries):
            backoff = min(
                self._base_backoff * (2 ** attempt), self._max_backoff
            )
            logger.info(
                "Retrying %s (attempt %d/%d) after %.1fs backoff",
                failure.source,
                attempt + 1,
                self._max_retries,
                backoff,
            )
            await asyncio.sleep(backoff)

            try:
                result = await retry_fn()
                return RecoveryResult(
                    failure=failure,
                    outcome=RecoveryOutcome.RETRIED,
                    strategy="retry",
                    detail=f"Succeeded on attempt {attempt + 1}",
                    retried=True,
                )
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Retry attempt %d failed: %s", attempt + 1, exc)

        return RecoveryResult(
            failure=failure,
            outcome=RecoveryOutcome.UNRECOVERED,
            strategy="retry",
            detail=f"All {self._max_retries} retries failed. Last error: {last_error}",
            retried=True,
        )

    async def _fallback(self, failure: Failure) -> RecoveryResult:
        """Attempt a fallback response."""
        fallback_fn = failure.context.get("fallback_fn")
        if fallback_fn is not None:
            try:
                result = await fallback_fn()
                return RecoveryResult(
                    failure=failure,
                    outcome=RecoveryOutcome.FELL_BACK,
                    strategy="fallback",
                    detail=f"Fallback succeeded: {result}",
                    retried=False,
                )
            except Exception as exc:
                logger.warning("Fallback failed: %s", exc)
                return RecoveryResult(
                    failure=failure,
                    outcome=RecoveryOutcome.UNRECOVERED,
                    strategy="fallback",
                    detail=f"Fallback failed: {exc}",
                    retried=False,
                )

        return RecoveryResult(
            failure=failure,
            outcome=RecoveryOutcome.UNRECOVERED,
            strategy="fallback",
            detail="No fallback function provided",
            retried=False,
        )

    async def _escalate(self, failure: Failure) -> RecoveryResult:
        """Escalate the failure to a human via remediation actions."""
        message = (
            f"Bot {self._bot_id} failed unrecoverably. "
            f"Source: {failure.source}, Error: {failure.error_message}"
        )
        await self._remediation_actions.escalate_to_human(message)
        return RecoveryResult(
            failure=failure,
            outcome=RecoveryOutcome.ESCALATED,
            strategy="escalate",
            detail="Escalated to human operator",
            retried=False,
        )

    def _classify_failure(self, error_type: str, error_message: str) -> FailureType:
        """Classify a failure by its error type and message."""
        et = error_type.lower()
        msg = error_message.lower()

        if "circuit" in et or "circuit" in msg or "circuitopen" in et:
            return FailureType.CIRCUIT_OPEN
        if "semantic" in et or "semantic_loop" in et:
            return FailureType.SEMANTIC_LOOP
        if "llm" in et or "llm" in msg:
            return FailureType.LLM_FAILURE
        if "tool" in et:
            return FailureType.TOOL_FAILURE
        if "discord" in et:
            return FailureType.DISCORD_FAILURE
        return FailureType.UNKNOWN

    def _sanitize_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Remove non-serializable values from context for event publishing."""
        safe: dict[str, Any] = {}
        for key, value in context.items():
            if callable(value):
                continue
            try:
                import json

                json.dumps(value)
                safe[key] = value
            except (TypeError, ValueError):
                safe[key] = repr(value)
        return safe

    async def _publish_failure_logged(self, failure: Failure) -> None:
        event = NexusEvent.create(
            event_type=EventType.FAILURE_LOGGED,
            source=self._bot_id,
            target="broadcast",
            payload={
                "bot_id": self._bot_id,
                "failure_type": failure.error_type,
                "error_message": failure.error_message,
                "stack_trace": None,
                "context": self._sanitize_context(failure.context),
            },
        )
        await self._nexus_bus.publish(event)

    async def _publish_recovery_executed(
        self, failure: Failure, result: RecoveryResult
    ) -> None:
        event = NexusEvent.create(
            event_type=EventType.RECOVERY_EXECUTED,
            source=self._bot_id,
            target="broadcast",
            payload={
                "bot_id": self._bot_id,
                "failure_type": failure.error_type,
                "recovery_action": result.strategy,
                "success": result.outcome != RecoveryOutcome.UNRECOVERED,
                "details": {
                    "outcome": result.outcome.value,
                    "detail": result.detail,
                    "retried": result.retried,
                },
            },
        )
        await self._nexus_bus.publish(event)
