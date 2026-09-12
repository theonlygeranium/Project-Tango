"""Semantic Breaker — detects when a bot is stuck calling the same tool with the same args.

Maintains a sliding window of recent tool calls. If the same tool is called
with the same arguments more than a threshold number of times within the
time window, a SemanticLoopError is raised to break the loop.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class SemanticLoopError(Exception):
    """Raised when a semantic loop is detected (same tool+args repeated)."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(
            f"Semantic loop detected: tool '{tool_name}' called with identical "
            f"arguments too many times"
        )


@dataclass
class _CallRecord:
    tool_name: str
    args_hash: str
    timestamp: float


class SemanticBreaker:
    """Detects semantic loops by tracking repeated tool calls within a time window."""

    def __init__(
        self,
        window_size: int = 3,
        time_window_seconds: int = 60,
        repeat_threshold: int = 3,
    ) -> None:
        self._window_size = window_size
        self._time_window_seconds = time_window_seconds
        self._repeat_threshold = repeat_threshold
        self._calls: deque[_CallRecord] = deque(maxlen=window_size * 10)

    def record_call(self, tool_name: str, args: dict[str, Any], result: Any) -> bool:
        """Record a tool call and return True if a semantic loop is detected.

        A loop is detected when the same tool is called with the same arguments
        at least *repeat_threshold* times within *time_window_seconds*.
        """
        args_hash = self._hash_args(args)
        now = time.monotonic()

        # Prune old entries outside the time window
        self._prune_old(now)

        record = _CallRecord(tool_name=tool_name, args_hash=args_hash, timestamp=now)
        self._calls.append(record)

        # Count how many times this exact tool+args appears in the window
        count = sum(
            1
            for r in self._calls
            if r.tool_name == tool_name and r.args_hash == args_hash
        )

        if count >= self._repeat_threshold:
            logger.warning(
                "Semantic loop detected: tool '%s' called %d times with same args",
                tool_name,
                count,
            )
            return True

        return False

    def reset(self) -> None:
        """Clear all recorded calls."""
        self._calls.clear()
        logger.debug("SemanticBreaker reset")

    def _prune_old(self, now: float) -> None:
        """Remove call records older than the time window."""
        cutoff = now - self._time_window_seconds
        while self._calls and self._calls[0].timestamp < cutoff:
            self._calls.popleft()

    def _hash_args(self, args: dict[str, Any]) -> str:
        """Produce a stable hash of the arguments dict."""
        serialized = repr(sorted(args.items()))
        return hashlib.sha256(serialized.encode()).hexdigest()
