"""Tool registry and execution — circuit-breaker protected tool calls.

Each tool execution goes through:
1. Resolve tool by name (raise KeyError if unknown)
2. Execute through per-tool circuit breaker
3. Record with semantic breaker
4. Validate result against result_schema if defined
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    """A registered tool with optional handler and result schema."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Awaitable[Any]] | None = None
    result_schema: dict[str, Any] | None = None


@dataclass
class ToolCall:
    """A single tool invocation with args and optional result."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    result: Any | None = None


class ToolRegistry:
    """Registry of tools with circuit-breaker and semantic-breaker protected execution."""

    def __init__(
        self,
        breakers: Any,
        semantic_breaker: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self._breakers = breakers
        self._semantic_breaker = semantic_breaker
        self._logger = logger or logging.getLogger(__name__)
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool by its name."""
        self._tools[tool.name] = tool
        self._logger.debug("Registered tool '%s'", tool.name)

    async def execute(self, tool_call: ToolCall) -> Any:
        """Execute a tool call through circuit breaker and semantic breaker.

        Steps:
        1. Resolve tool by name (raise KeyError if unknown)
        2. Execute through per-tool circuit breaker
        3. Record with semantic breaker
        4. Validate result against result_schema if defined
        """
        tool = self._tools.get(tool_call.name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_call.name}")

        if tool.handler is None:
            raise ValueError(f"Tool '{tool_call.name}' has no handler")

        result = await self._breakers.call_tool(
            tool_call.name, tool.handler, **tool_call.args
        )

        loop_detected = self._semantic_breaker.record_call(
            tool_call.name, tool_call.args, result
        )
        if loop_detected:
            from nexus.self_healing.semantic_breaker import SemanticLoopError

            raise SemanticLoopError(tool_call.name)

        if tool.result_schema is not None:
            self._validate_result(result, tool.result_schema, tool_call.name)

        tool_call.result = result
        return result

    def get(self, name: str) -> Tool | None:
        """Get a tool by name, or None if not registered."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def _validate_result(
        self, result: Any, schema: dict[str, Any], tool_name: str
    ) -> None:
        """Validate the result against the result schema (basic key check)."""
        if not isinstance(result, dict):
            self._logger.warning(
                "Tool '%s' result is not a dict, cannot validate against schema",
                tool_name,
            )
            return

        required_keys = schema.get("required", [])
        for key in required_keys:
            if key not in result:
                self._logger.warning(
                    "Tool '%s' result missing required key '%s'", tool_name, key
                )
