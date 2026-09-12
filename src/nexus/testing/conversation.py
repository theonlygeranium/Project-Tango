"""Conversation test runner — sends questions via Nexus Bus and records trajectories.

The runner publishes task.new events to the Nexus Bus targeting a specific bot,
waits for task.result responses, and records the full conversation trajectory
including follow-up questions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from nexus.bus.event import EventType, NexusEvent
from nexus.testing.recipe import TestCase, TestRecipe

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """A single turn in a conversation trajectory.

    Attributes:
        role: "user" or "assistant".
        content: The text content of the turn.
        timestamp: ISO-8601 timestamp.
        tool_name: Name of tool called, if any.
        tool_args: Arguments passed to the tool, if any.
        tool_result: Result returned by the tool, if any.
    """

    role: str
    content: str
    timestamp: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
        }


@dataclass
class ConversationTrajectory:
    """Full trajectory of a conversation test.

    Attributes:
        test_id: The test case ID.
        bot_id: The bot being tested.
        started_at: ISO-8601 timestamp.
        completed_at: ISO-8601 timestamp.
        turns: List of ConversationTurn objects.
        duration_s: Duration in seconds.
        error: Error message if the test failed to complete.
    """

    test_id: str
    bot_id: str
    started_at: str = ""
    completed_at: str = ""
    turns: list[ConversationTurn] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None

    def add_turn(self, turn: ConversationTurn) -> None:
        """Add a turn to the trajectory."""
        if not turn.timestamp:
            turn.timestamp = datetime.now(timezone.utc).isoformat()
        self.turns.append(turn)

    def to_judge_format(self) -> list[dict[str, Any]]:
        """Convert trajectory to a format suitable for the judge LLM.

        Returns:
            List of message dicts with role and content.
        """
        messages: list[dict[str, Any]] = []
        for turn in self.turns:
            msg: dict[str, Any] = {"role": turn.role, "content": turn.content}
            if turn.tool_name is not None:
                msg["tool_name"] = turn.tool_name
                msg["tool_args"] = turn.tool_args
                msg["tool_result"] = turn.tool_result
            messages.append(msg)
        return messages


class ConversationRunner:
    """Runs conversation tests against bots via the Nexus Bus.

    Sends questions as task.new events and waits for task.result responses.
    Records full conversation trajectories including follow-up questions.
    """

    def __init__(
        self,
        nexus: Any,
        llm_client: Any,
        timeout_s: int = 120,
    ) -> None:
        self._nexus = nexus
        self._llm_client = llm_client
        self._timeout_s = timeout_s
        self._pending_results: dict[str, asyncio.Future[str]] = {}

    async def run_test(self, bot_id: str, test_case: TestCase) -> ConversationTrajectory:
        """Run a single test case against a bot.

        Args:
            bot_id: The bot to test.
            test_case: The test case to run.

        Returns:
            A ConversationTrajectory with all turns recorded.
        """
        started = datetime.now(timezone.utc)
        start_time = time.monotonic()
        trajectory = ConversationTrajectory(
            test_id=test_case.test_id,
            bot_id=bot_id,
            started_at=started.isoformat(),
        )

        try:
            # Send the primary question
            response = await self._send_and_wait(bot_id, test_case.question, test_case.test_id)
            trajectory.add_turn(ConversationTurn(role="user", content=test_case.question))
            trajectory.add_turn(ConversationTurn(role="assistant", content=response))

            # Send follow-up questions
            for i, follow_up in enumerate(test_case.follow_ups):
                follow_id = f"{test_case.test_id}-fu{i}"
                fu_response = await self._send_and_wait(bot_id, follow_up, follow_id)
                trajectory.add_turn(ConversationTurn(role="user", content=follow_up))
                trajectory.add_turn(ConversationTurn(role="assistant", content=fu_response))

        except asyncio.TimeoutError:
            trajectory.error = f"Timeout after {self._timeout_s}s waiting for bot response"
            logger.warning("Test %s timed out for bot %s", test_case.test_id, bot_id)
        except Exception as exc:
            trajectory.error = str(exc)
            logger.error("Test %s failed for bot %s: %s", test_case.test_id, bot_id, exc)

        trajectory.completed_at = datetime.now(timezone.utc).isoformat()
        trajectory.duration_s = time.monotonic() - start_time
        return trajectory

    async def run_recipe(self, bot_id: str, recipe: TestRecipe) -> list[ConversationTrajectory]:
        """Run all test cases in a recipe against a bot.

        Args:
            bot_id: The bot to test.
            recipe: The recipe containing test cases.

        Returns:
            List of ConversationTrajectory objects, one per test case.
        """
        trajectories: list[ConversationTrajectory] = []
        for test_case in recipe.cases:
            trajectory = await self.run_test(bot_id, test_case)
            trajectories.append(trajectory)
        return trajectories

    async def _send_and_wait(self, bot_id: str, question: str, test_id: str) -> str:
        """Send a question to a bot via Nexus Bus and wait for the response.

        Publishes a task.new event and waits for the corresponding task.result.

        Args:
            bot_id: The bot to send the question to.
            question: The question text.
            test_id: Unique ID for this interaction.

        Returns:
            The bot's response content.

        Raises:
            asyncio.TimeoutError: If no response within timeout.
        """
        task_id = f"{test_id}-{uuid4().hex[:8]}"
        correlation_id = str(uuid4())

        # Set up a future to receive the result
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending_results[task_id] = future

        # Register a handler for task.result if not already registered
        result_handler = _ResultHandler(self._pending_results)
        await self._nexus.subscribe(EventType.TASK_RESULT, result_handler.handle)

        # Publish the task.new event
        event = NexusEvent.create(
            event_type=EventType.TASK_NEW,
            source="sentinel",
            target=bot_id,
            correlation_id=correlation_id,
            payload={
                "task_id": task_id,
                "task_type": "test",
                "description": question,
                "priority": "normal",
                "deadline": None,
            },
        )
        await self._nexus.publish(event)
        logger.debug("Sent test question to %s (task_id=%s)", bot_id, task_id)

        # Wait for the result
        try:
            result = await asyncio.wait_for(future, timeout=self._timeout_s)
            return result
        except asyncio.TimeoutError:
            self._pending_results.pop(task_id, None)
            raise
        finally:
            self._pending_results.pop(task_id, None)


class _ResultHandler:
    """Internal handler that resolves pending futures when task.result events arrive."""

    def __init__(self, pending: dict[str, asyncio.Future[str]]) -> None:
        self._pending = pending

    async def handle(self, event: NexusEvent) -> None:
        """Handle a task.result event by resolving the pending future."""
        task_id = event.payload.get("task_id", "")
        if task_id in self._pending:
            future = self._pending[task_id]
            if not future.done():
                result_content = ""
                result_data = event.payload.get("result", {})
                if isinstance(result_data, dict):
                    result_content = result_data.get("content", "")
                elif isinstance(result_data, str):
                    result_content = result_data
                future.set_result(result_content)
