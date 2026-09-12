"""Circuit Breaker — protects against cascading failures in LLM, tool, and Discord calls.

Implements the classic circuit breaker pattern with three states:
CLOSED -> OPEN (failure threshold reached) -> HALF_OPEN (recovery timeout elapsed)
-> CLOSED (success threshold met) or back to OPEN (failure in half-open, doubled timeout).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class BreakerConfig:
    """Configuration for a circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout: int = 30
    success_threshold: int = 2

    @classmethod
    def for_llm(cls) -> "BreakerConfig":
        return cls(failure_threshold=5, recovery_timeout=30, success_threshold=2)

    @classmethod
    def for_tools(cls) -> "BreakerConfig":
        return cls(failure_threshold=3, recovery_timeout=60, success_threshold=2)

    @classmethod
    def for_discord(cls) -> "BreakerConfig":
        return cls(failure_threshold=10, recovery_timeout=15, success_threshold=3)


class CircuitOpenError(Exception):
    """Raised when calling through a circuit breaker that is OPEN."""

    def __init__(self, breaker_name: str, last_error: str) -> None:
        self.breaker_name = breaker_name
        self.last_error = last_error
        super().__init__(
            f"Circuit breaker '{breaker_name}' is OPEN. Last error: {last_error}"
        )


class CircuitBreaker:
    """A single circuit breaker protecting one resource."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        success_threshold: int = 2,
    ) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold

        self._state = BreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_error: str = ""
        self._opened_at: float = 0.0
        self._current_recovery_timeout = recovery_timeout

    async def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute *fn* through the circuit breaker.

        Raises CircuitOpenError if the breaker is OPEN and the recovery timeout
        has not yet elapsed.
        """
        if self._state == BreakerState.OPEN:
            if time.monotonic() - self._opened_at < self._current_recovery_timeout:
                raise CircuitOpenError(self._name, self._last_error)
            self._transition_to_half_open()

        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            self._on_failure(exc)
            raise

        self._on_success()
        return result

    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def reset(self) -> None:
        """Reset the breaker to CLOSED state with zeroed counters."""
        self._state = BreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_error = ""
        self._opened_at = 0.0
        self._current_recovery_timeout = self._recovery_timeout
        logger.info("Circuit breaker '%s' reset to CLOSED", self._name)

    def _on_success(self) -> None:
        if self._state == BreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._state = BreakerState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                self._current_recovery_timeout = self._recovery_timeout
                logger.info(
                    "Circuit breaker '%s' transitioned HALF_OPEN -> CLOSED", self._name
                )
        elif self._state == BreakerState.CLOSED:
            self._failure_count = 0

    def _on_failure(self, error: Exception) -> None:
        self._last_error = str(error)

        if self._state == BreakerState.HALF_OPEN:
            self._current_recovery_timeout = min(
                self._current_recovery_timeout * 2, 300
            )
            self._state = BreakerState.OPEN
            self._opened_at = time.monotonic()
            self._success_count = 0
            logger.warning(
                "Circuit breaker '%s' failed in HALF_OPEN -> OPEN (doubled timeout=%ds)",
                self._name,
                self._current_recovery_timeout,
            )
        elif self._state == BreakerState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = BreakerState.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "Circuit breaker '%s' transitioned CLOSED -> OPEN (failures=%d)",
                    self._name,
                    self._failure_count,
                )

    def _transition_to_half_open(self) -> None:
        self._state = BreakerState.HALF_OPEN
        self._success_count = 0
        self._failure_count = 0
        logger.info("Circuit breaker '%s' transitioned OPEN -> HALF_OPEN", self._name)


class CircuitBreakerManager:
    """Manages a set of circuit breakers for LLM, tool, and Discord calls."""

    def __init__(self, config: BreakerConfig) -> None:
        self._config = config
        self._llm_breakers: dict[str, CircuitBreaker] = {}
        self._tool_breakers: dict[str, CircuitBreaker] = {}
        self._discord_breakers: dict[str, CircuitBreaker] = {}

    def _get_llm_breaker(self, model: str) -> CircuitBreaker:
        if model not in self._llm_breakers:
            self._llm_breakers[model] = CircuitBreaker(
                name=f"llm:{model}",
                failure_threshold=self._config.failure_threshold,
                recovery_timeout=self._config.recovery_timeout,
                success_threshold=self._config.success_threshold,
            )
        return self._llm_breakers[model]

    def _get_tool_breaker(self, tool_name: str) -> CircuitBreaker:
        if tool_name not in self._tool_breakers:
            self._tool_breakers[tool_name] = CircuitBreaker(
                name=f"tool:{tool_name}",
                failure_threshold=self._config.failure_threshold,
                recovery_timeout=self._config.recovery_timeout,
                success_threshold=self._config.success_threshold,
            )
        return self._tool_breakers[tool_name]

    def _get_discord_breaker(self, endpoint: str) -> CircuitBreaker:
        if endpoint not in self._discord_breakers:
            self._discord_breakers[endpoint] = CircuitBreaker(
                name=f"discord:{endpoint}",
                failure_threshold=self._config.failure_threshold,
                recovery_timeout=self._config.recovery_timeout,
                success_threshold=self._config.success_threshold,
            )
        return self._discord_breakers[endpoint]

    async def call_llm(self, model: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        breaker = self._get_llm_breaker(model)
        return await breaker.call(fn, *args, **kwargs)

    async def call_tool(self, tool_name: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        breaker = self._get_tool_breaker(tool_name)
        return await breaker.call(fn, *args, **kwargs)

    async def call_discord(self, endpoint: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        breaker = self._get_discord_breaker(endpoint)
        return await breaker.call(fn, *args, **kwargs)

    def get_all_states(self) -> dict[str, BreakerState]:
        states: dict[str, BreakerState] = {}
        for breaker in list(self._llm_breakers.values()) + list(
            self._tool_breakers.values()
        ) + list(self._discord_breakers.values()):
            states[breaker._name] = breaker.state
        return states

    def get_failure_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for breaker in list(self._llm_breakers.values()) + list(
            self._tool_breakers.values()
        ) + list(self._discord_breakers.values()):
            counts[breaker._name] = breaker.failure_count
        return counts

    def reset_all(self) -> None:
        for breaker in list(self._llm_breakers.values()) + list(
            self._tool_breakers.values()
        ) + list(self._discord_breakers.values()):
            breaker.reset()
