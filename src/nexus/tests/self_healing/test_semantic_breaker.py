"""Tests for SemanticBreaker."""

from __future__ import annotations

import time

import pytest

from nexus.self_healing.semantic_breaker import SemanticBreaker, SemanticLoopError


class TestSemanticBreaker:
    """Tests for SemanticBreaker."""

    def test_no_loop_on_varied_calls(self) -> None:
        breaker = SemanticBreaker(window_size=10, time_window_seconds=60, repeat_threshold=3)

        # Different tools and args — should not trigger
        result1 = breaker.record_call("search", {"q": "hello"}, "result1")
        result2 = breaker.record_call("search", {"q": "world"}, "result2")
        result3 = breaker.record_call("fetch", {"id": 1}, "result3")

        assert result1 is False
        assert result2 is False
        assert result3 is False

    def test_detects_repeated_identical_calls(self) -> None:
        breaker = SemanticBreaker(window_size=10, time_window_seconds=60, repeat_threshold=3)

        args = {"q": "same_query"}
        result1 = breaker.record_call("search", args, "result1")
        result2 = breaker.record_call("search", args, "result2")
        result3 = breaker.record_call("search", args, "result3")

        assert result1 is False
        assert result2 is False
        assert result3 is True  # Loop detected on 3rd identical call

    def test_detects_with_different_results(self) -> None:
        breaker = SemanticBreaker(window_size=10, time_window_seconds=60, repeat_threshold=3)

        args = {"action": "retry"}
        breaker.record_call("tool", args, "fail1")
        breaker.record_call("tool", args, "fail2")
        detected = breaker.record_call("tool", args, "fail3")

        assert detected is True

    def test_resets(self) -> None:
        breaker = SemanticBreaker(window_size=10, time_window_seconds=60, repeat_threshold=3)

        args = {"q": "same"}
        breaker.record_call("search", args, "r1")
        breaker.record_call("search", args, "r2")

        breaker.reset()

        # After reset, should not detect loop
        detected = breaker.record_call("search", args, "r3")
        assert detected is False

    def test_time_window_expiry(self) -> None:
        breaker = SemanticBreaker(window_size=10, time_window_seconds=1, repeat_threshold=3)

        args = {"q": "same"}

        breaker.record_call("search", args, "r1")
        breaker.record_call("search", args, "r2")

        # Wait for time window to expire
        time.sleep(1.1)

        # After window expiry, old calls should be pruned
        detected = breaker.record_call("search", args, "r3")
        assert detected is False

    def test_different_args_same_tool_no_loop(self) -> None:
        breaker = SemanticBreaker(window_size=10, time_window_seconds=60, repeat_threshold=3)

        # Same tool, different args — should not trigger
        breaker.record_call("search", {"q": "a"}, "r1")
        breaker.record_call("search", {"q": "b"}, "r2")
        breaker.record_call("search", {"q": "c"}, "r3")

        # No loop because args are different
        detected = breaker.record_call("search", {"q": "d"}, "r4")
        assert detected is False

    def test_semantic_loop_error_attributes(self) -> None:
        error = SemanticLoopError("my_tool")
        assert error.tool_name == "my_tool"
        assert "my_tool" in str(error)
