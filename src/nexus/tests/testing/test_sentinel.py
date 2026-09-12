"""Tests for Sentinel — run_full_cycle, _test_bot, publishes cycle summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
import yaml

from nexus.testing.conversation import ConversationTrajectory, ConversationTurn
from nexus.testing.judge import CriterionScore, JudgeResult
from nexus.testing.recipe import RecipeRegistry, TestCase, TestRecipe
from nexus.testing.sentinel import Sentinel, TestCycleResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Create a temporary recipes directory with a valid recipe."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()

    cases = []
    for i in range(20):
        cases.append({
            "test_id": f"testbot-{i:03d}",
            "category": "domain_knowledge",
            "question": f"Question {i}?",
            "follow_ups": [],
            "expected_behavior": "Good response",
            "acceptance_keywords": ["good"],
            "rejection_keywords": ["bad"],
            "rubric_id": "domain_knowledge_rubric",
            "difficulty": "easy",
            "source": "manual",
            "created_at": "2026-08-21T05:00:00Z",
            "tests_feature": None,
            "min_score": 7.0,
        })

    recipe_data = {
        "bot_id": "testbot",
        "version": "1.0.0",
        "last_updated": "2026-08-21T05:00:00Z",
        "total_cases": 20,
        "coverage": {"domain_knowledge": [c["test_id"] for c in cases]},
        "cases": cases,
    }
    with open(recipes / "testbot.yaml", "w") as f:
        yaml.dump(recipe_data, f)

    return recipes


@pytest.fixture
async def redis_client() -> Any:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def mock_nexus() -> Any:
    nexus = MagicMock()
    nexus.publish = AsyncMock()
    nexus.subscribe = AsyncMock()
    return nexus


@pytest.fixture
def mock_llm() -> Any:
    llm = MagicMock()
    llm.call = AsyncMock(return_value={"content": "Good response"})
    return llm


@pytest.fixture
def sentinel(
    mock_nexus: Any, mock_llm: Any, redis_client: Any, recipes_dir: Path
) -> Sentinel:
    registry = RecipeRegistry(recipes_dir=recipes_dir)
    return Sentinel(mock_nexus, mock_llm, redis_client, registry=registry)


def _make_passing_judge_result(test_id: str, bot_id: str) -> JudgeResult:
    return JudgeResult(
        test_id=test_id,
        bot_id=bot_id,
        rubric_id="domain_knowledge_rubric",
        criterion_scores=[CriterionScore(name="role_clarity", score=9.0)],
        composite_score=9.0,
        passed=True,
        summary="Good response",
    )


def _make_failing_judge_result(test_id: str, bot_id: str) -> JudgeResult:
    return JudgeResult(
        test_id=test_id,
        bot_id=bot_id,
        rubric_id="domain_knowledge_rubric",
        criterion_scores=[CriterionScore(name="role_clarity", score=3.0)],
        composite_score=3.0,
        passed=False,
        summary="Poor response",
        failure_reasons=["Low score"],
    )


def _make_trajectory(test_id: str, bot_id: str) -> ConversationTrajectory:
    traj = ConversationTrajectory(test_id=test_id, bot_id=bot_id)
    traj.add_turn(ConversationTurn(role="user", content="Question?"))
    traj.add_turn(ConversationTurn(role="assistant", content="Answer"))
    return traj


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSentinelRunFullCycle:
    """Tests for Sentinel.run_full_cycle()."""

    async def test_run_full_cycle_returns_results(
        self, sentinel: Sentinel, mock_nexus: Any
    ) -> None:
        # Mock the runner and judge
        sentinel._runner.run_test = AsyncMock(
            return_value=_make_trajectory("testbot-000", "testbot")
        )
        sentinel._judge.evaluate = AsyncMock(
            return_value=_make_passing_judge_result("testbot-000", "testbot")
        )

        results = await sentinel.run_full_cycle()

        assert "testbot" in results
        assert isinstance(results["testbot"], TestCycleResult)
        assert results["testbot"].total_tests == 20
        assert results["testbot"].passed == 20
        assert results["testbot"].failed == 0

    async def test_run_full_cycle_publishes_summary(
        self, sentinel: Sentinel, mock_nexus: Any
    ) -> None:
        sentinel._runner.run_test = AsyncMock(
            return_value=_make_trajectory("testbot-000", "testbot")
        )
        sentinel._judge.evaluate = AsyncMock(
            return_value=_make_passing_judge_result("testbot-000", "testbot")
        )

        await sentinel.run_full_cycle()

        # Should have published at least one event (the cycle summary)
        mock_nexus.publish.assert_called()
        # Check that a TESTING_CYCLE_COMPLETE event was published
        publish_calls = mock_nexus.publish.call_args_list
        found_cycle_complete = False
        for call in publish_calls:
            event = call.args[0]
            if event.event_type == "testing.cycle_complete":
                found_cycle_complete = True
                assert event.payload["passed"] == 20
                break
        assert found_cycle_complete


class TestSentinelTestBot:
    """Tests for Sentinel._test_bot()."""

    async def test_test_bot_all_pass(
        self, sentinel: Sentinel
    ) -> None:
        sentinel._runner.run_test = AsyncMock(
            return_value=_make_trajectory("testbot-000", "testbot")
        )
        sentinel._judge.evaluate = AsyncMock(
            return_value=_make_passing_judge_result("testbot-000", "testbot")
        )

        result = await sentinel._test_bot("testbot")

        assert result.bot_id == "testbot"
        assert result.total_tests == 20
        assert result.passed == 20
        assert result.failed == 0
        assert result.repaired == 0
        assert result.escalated == 0

    async def test_test_bot_with_failures(
        self, sentinel: Sentinel
    ) -> None:
        sentinel._runner.run_test = AsyncMock(
            return_value=_make_trajectory("testbot-000", "testbot")
        )
        sentinel._judge.evaluate = AsyncMock(
            return_value=_make_failing_judge_result("testbot-000", "testbot")
        )
        # Mock repair engine to return a passed report
        from nexus.testing.repair import FailureReport
        sentinel._repair_engine.repair = AsyncMock(
            return_value=FailureReport(
                failure_id="f1",
                test_id="testbot-000",
                bot_id="testbot",
                category="domain_knowledge",
                composite_score=3.0,
                min_score=7.0,
                final_status="passed",
            )
        )

        result = await sentinel._test_bot("testbot")

        assert result.failed == 20
        assert result.repaired == 20
        assert result.passed == 0

    async def test_test_bot_missing_recipe(
        self, sentinel: Sentinel
    ) -> None:
        result = await sentinel._test_bot("nonexistent")

        assert result.bot_id == "nonexistent"
        assert result.total_tests == 0


class TestSentinelPublishCycleSummary:
    """Tests for Sentinel._publish_cycle_summary()."""

    async def test_publish_cycle_summary(
        self, sentinel: Sentinel, mock_nexus: Any
    ) -> None:
        results = {
            "testbot": TestCycleResult(
                bot_id="testbot",
                total_tests=20,
                passed=15,
                failed=5,
            )
        }

        await sentinel._publish_cycle_summary(results)

        mock_nexus.publish.assert_called_once()
        event = mock_nexus.publish.call_args.args[0]
        assert event.event_type == "testing.cycle_complete"
        assert event.payload["passed"] == 15
        assert event.payload["failed"] == 5
        assert event.payload["total_tests"] == 20


class TestSentinelStartStop:
    """Tests for Sentinel.start() and stop()."""

    async def test_start_subscribes_to_events(
        self, sentinel: Sentinel, mock_nexus: Any
    ) -> None:
        await sentinel.start()
        await sentinel.stop()

        # Should have subscribed to testing.run_now and testing.recipe_updated
        subscribed_types: list[str] = []
        for call in mock_nexus.subscribe.call_args_list:
            subscribed_types.append(call.args[0])
        assert "testing.run_now" in subscribed_types
        assert "testing.recipe_updated" in subscribed_types
