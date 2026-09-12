"""Tests for CircuitBreaker and CircuitBreakerManager."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from nexus.self_healing.circuit_breaker import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitOpenError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_raise(exc: Exception) -> None:
    raise exc


async def _async_success() -> str:
    return "ok"


async def _async_fail() -> None:
    raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Tests for the CircuitBreaker state machine."""

    async def test_closed_by_default(self) -> None:
        breaker = CircuitBreaker("test")
        assert breaker.state == BreakerState.CLOSED
        assert breaker.failure_count == 0

    async def test_opens_after_threshold(self) -> None:
        breaker = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(_async_fail)

        assert breaker.state == BreakerState.OPEN
        assert breaker.failure_count == 3

    async def test_half_open_after_timeout(self) -> None:
        breaker = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(_async_fail)

        assert breaker.state == BreakerState.OPEN

        # Wait for recovery timeout (0 seconds, but we need to let monotonic advance)
        await asyncio.sleep(0.05)

        # Next call should transition to HALF_OPEN
        # If it succeeds, it should be in HALF_OPEN then CLOSED after success_threshold
        with pytest.raises(RuntimeError):
            await breaker.call(_async_fail)

        # It was in HALF_OPEN, then failed, so back to OPEN
        assert breaker.state == BreakerState.OPEN

    async def test_closes_after_success_threshold(self) -> None:
        breaker = CircuitBreaker(
            "test", failure_threshold=2, recovery_timeout=0, success_threshold=2
        )
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(_async_fail)

        assert breaker.state == BreakerState.OPEN

        await asyncio.sleep(0.05)

        # First success in half-open
        result = await breaker.call(_async_success)
        assert result == "ok"
        assert breaker.state == BreakerState.HALF_OPEN

        # Second success -> CLOSED
        result = await breaker.call(_async_success)
        assert result == "ok"
        assert breaker.state == BreakerState.CLOSED

    async def test_reopens_on_half_open_failure(self) -> None:
        breaker = CircuitBreaker(
            "test", failure_threshold=2, recovery_timeout=0, success_threshold=2
        )
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(_async_fail)

        assert breaker.state == BreakerState.OPEN

        await asyncio.sleep(0.05)

        # Fail in half-open -> back to OPEN with doubled timeout
        with pytest.raises(RuntimeError):
            await breaker.call(_async_fail)

        assert breaker.state == BreakerState.OPEN

    async def test_circuit_open_error_raised(self) -> None:
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=300)
        with pytest.raises(RuntimeError):
            await breaker.call(_async_fail)

        # Now OPEN with long timeout -> should raise CircuitOpenError
        with pytest.raises(CircuitOpenError) as exc_info:
            await breaker.call(_async_success)

        assert "test" in str(exc_info.value)

    async def test_reset_works(self) -> None:
        breaker = CircuitBreaker("test", failure_threshold=2)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(_async_fail)

        assert breaker.state == BreakerState.OPEN

        breaker.reset()
        assert breaker.state == BreakerState.CLOSED
        assert breaker.failure_count == 0


# ---------------------------------------------------------------------------
# CircuitBreakerManager tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerManager:
    """Tests for the CircuitBreakerManager."""

    async def test_manager_routes_llm_tool_discord(self) -> None:
        manager = CircuitBreakerManager(BreakerConfig.for_llm())

        # All should succeed
        result = await manager.call_llm("gpt-4", _async_success)
        assert result == "ok"

        result = await manager.call_tool("search", _async_success)
        assert result == "ok"

        result = await manager.call_discord("send_message", _async_success)
        assert result == "ok"

        states = manager.get_all_states()
        assert "llm:gpt-4" in states
        assert "tool:search" in states
        assert "discord:send_message" in states

    async def test_manager_separate_breakers(self) -> None:
        manager = CircuitBreakerManager(BreakerConfig(failure_threshold=2))

        # Break the LLM breaker
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await manager.call_llm("model1", _async_fail)

        # Tool breaker should still work
        result = await manager.call_tool("search", _async_success)
        assert result == "ok"

    async def test_manager_get_failure_counts(self) -> None:
        manager = CircuitBreakerManager(BreakerConfig(failure_threshold=5))

        with pytest.raises(RuntimeError):
            await manager.call_llm("model1", _async_fail)

        counts = manager.get_failure_counts()
        assert counts["llm:model1"] == 1

    async def test_manager_reset_all(self) -> None:
        manager = CircuitBreakerManager(BreakerConfig(failure_threshold=2))

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await manager.call_llm("model1", _async_fail)

        assert manager.get_all_states()["llm:model1"] == BreakerState.OPEN

        manager.reset_all()

        states = manager.get_all_states()
        for state in states.values():
            assert state == BreakerState.CLOSED


# ---------------------------------------------------------------------------
# BreakerConfig tests
# ---------------------------------------------------------------------------

class TestBreakerConfig:
    """Tests for BreakerConfig factory methods."""

    def test_for_llm(self) -> None:
        config = BreakerConfig.for_llm()
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 30
        assert config.success_threshold == 2

    def test_for_tools(self) -> None:
        config = BreakerConfig.for_tools()
        assert config.failure_threshold == 3
        assert config.recovery_timeout == 60
        assert config.success_threshold == 2

    def test_for_discord(self) -> None:
        config = BreakerConfig.for_discord()
        assert config.failure_threshold == 10
        assert config.recovery_timeout == 15
        assert config.success_threshold == 3
