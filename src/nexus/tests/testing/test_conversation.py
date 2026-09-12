"""Tests for ConversationRunner — sends questions and records trajectories."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.testing.conversation import ConversationRunner, ConversationTrajectory, ConversationTurn
from nexus.testing.recipe import TestCase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_nexus() -> Any:
    nexus = MagicMock()
    nexus.publish = AsyncMock()
    nexus.subscribe = AsyncMock()
    return nexus


@pytest.fixture
def mock_llm() -> Any:
    llm = MagicMock()
    llm.call = AsyncMock()
    return llm


@pytest.fixture
def runner(mock_nexus: Any, mock_llm: Any) -> ConversationRunner:
    return ConversationRunner(mock_nexus, mock_llm, timeout_s=5)


@pytest.fixture
def test_case() -> TestCase:
    return TestCase(
        test_id="cortex-001",
        category="domain_knowledge",
        question="What is your role?",
        follow_ups=["What tier are you?"],
        expected_behavior="States role clearly",
        acceptance_keywords=["role"],
        rejection_keywords=["unknown"],
        rubric_id="domain_knowledge_rubric",
        difficulty="easy",
        min_score=7.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConversationTurn:
    """Tests for ConversationTurn dataclass."""

    def test_creation(self) -> None:
        turn = ConversationTurn(role="user", content="Hello")
        assert turn.role == "user"
        assert turn.content == "Hello"
        assert turn.tool_name is None

    def test_to_dict(self) -> None:
        turn = ConversationTurn(role="assistant", content="Hi there", tool_name="search")
        d = turn.to_dict()
        assert d["role"] == "assistant"
        assert d["content"] == "Hi there"
        assert d["tool_name"] == "search"


class TestConversationTrajectory:
    """Tests for ConversationTrajectory dataclass."""

    def test_add_turn(self) -> None:
        traj = ConversationTrajectory(test_id="test-001", bot_id="cortex")
        turn = ConversationTurn(role="user", content="Hello")
        traj.add_turn(turn)
        assert len(traj.turns) == 1
        assert traj.turns[0].content == "Hello"
        # Should have a timestamp
        assert traj.turns[0].timestamp != ""

    def test_to_judge_format(self) -> None:
        traj = ConversationTrajectory(test_id="test-001", bot_id="cortex")
        traj.add_turn(ConversationTurn(role="user", content="Hello"))
        traj.add_turn(ConversationTurn(role="assistant", content="Hi"))
        messages = traj.to_judge_format()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "assistant"

    def test_to_judge_format_with_tools(self) -> None:
        traj = ConversationTrajectory(test_id="test-001", bot_id="cortex")
        traj.add_turn(
            ConversationTurn(
                role="assistant",
                content="Let me search",
                tool_name="web_search",
                tool_args={"query": "AI trends"},
                tool_result="Found 5 results",
            )
        )
        messages = traj.to_judge_format()
        assert messages[0]["tool_name"] == "web_search"
        assert messages[0]["tool_args"] == {"query": "AI trends"}
        assert messages[0]["tool_result"] == "Found 5 results"


class TestConversationRunner:
    """Tests for ConversationRunner."""

    async def test_run_test_records_trajectory(
        self, runner: ConversationRunner, test_case: TestCase, mock_nexus: Any
    ) -> None:
        # Mock _send_and_wait to return a response
        runner._send_and_wait = AsyncMock(side_effect=["I am Cortex", "Tier 1"])

        trajectory = await runner.run_test("cortex", test_case)

        assert trajectory.test_id == "cortex-001"
        assert trajectory.bot_id == "cortex"
        assert trajectory.error is None
        # Should have 4 turns: question, answer, follow-up, answer
        assert len(trajectory.turns) == 4
        assert trajectory.turns[0].role == "user"
        assert trajectory.turns[0].content == "What is your role?"
        assert trajectory.turns[1].role == "assistant"
        assert trajectory.turns[1].content == "I am Cortex"
        assert trajectory.turns[2].content == "What tier are you?"
        assert trajectory.turns[3].content == "Tier 1"

    async def test_run_test_handles_timeout(
        self, runner: ConversationRunner, test_case: TestCase
    ) -> None:
        import asyncio

        runner._send_and_wait = AsyncMock(side_effect=asyncio.TimeoutError())

        trajectory = await runner.run_test("cortex", test_case)

        assert trajectory.error is not None
        assert "Timeout" in trajectory.error

    async def test_run_test_handles_error(
        self, runner: ConversationRunner, test_case: TestCase
    ) -> None:
        runner._send_and_wait = AsyncMock(side_effect=RuntimeError("Connection lost"))

        trajectory = await runner.run_test("cortex", test_case)

        assert trajectory.error is not None
        assert "Connection lost" in trajectory.error

    async def test_run_test_no_follow_ups(
        self, runner: ConversationRunner, mock_nexus: Any
    ) -> None:
        tc = TestCase(
            test_id="test-001",
            category="domain_knowledge",
            question="Hello?",
            follow_ups=[],
            min_score=7.0,
        )
        runner._send_and_wait = AsyncMock(return_value="Hi!")

        trajectory = await runner.run_test("cortex", tc)

        assert len(trajectory.turns) == 2
        assert trajectory.duration_s >= 0.0

    async def test_run_recipe_runs_all_cases(
        self, runner: ConversationRunner, mock_nexus: Any
    ) -> None:
        from nexus.testing.recipe import TestRecipe

        cases = [
            TestCase(test_id=f"test-{i:03d}", category="domain_knowledge", question=f"Q{i}", min_score=7.0)
            for i in range(3)
        ]
        recipe = TestRecipe(bot_id="testbot", cases=cases)

        runner._send_and_wait = AsyncMock(return_value="Response")

        trajectories = await runner.run_recipe("testbot", recipe)

        assert len(trajectories) == 3
        assert all(t.bot_id == "testbot" for t in trajectories)
