"""Tests for RepairEngine — attempts repair, re-tests, escalates on failure."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.testing.conversation import ConversationTrajectory, ConversationTurn
from nexus.testing.judge import CriterionScore, JudgeResult
from nexus.testing.recipe import TestCase
from nexus.testing.repair import FailureReport, RepairAttempt, RepairEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_nexus() -> Any:
    nexus = MagicMock()
    nexus.publish = AsyncMock()
    return nexus


@pytest.fixture
def mock_llm() -> Any:
    llm = MagicMock()
    llm.call = AsyncMock(return_value={"content": "Suggested fix: update prompt"})
    return llm


@pytest.fixture
def mock_runner() -> Any:
    runner = MagicMock()
    runner.run_test = AsyncMock()
    return runner


@pytest.fixture
def mock_judge() -> Any:
    judge = MagicMock()
    judge.evaluate = AsyncMock()
    return judge


@pytest.fixture
def repair_engine(
    mock_nexus: Any, mock_llm: Any, mock_runner: Any, mock_judge: Any
) -> RepairEngine:
    return RepairEngine(mock_nexus, mock_llm, mock_runner, mock_judge)


@pytest.fixture
def failed_result() -> JudgeResult:
    return JudgeResult(
        test_id="cortex-001",
        bot_id="cortex",
        rubric_id="domain_knowledge_rubric",
        criterion_scores=[
            CriterionScore(name="role_clarity", score=3.0, reasoning="Poor"),
        ],
        composite_score=3.0,
        passed=False,
        summary="Bot failed to explain its role",
        failure_reasons=["Low score on role_clarity"],
    )


@pytest.fixture
def test_case() -> TestCase:
    return TestCase(
        test_id="cortex-001",
        category="domain_knowledge",
        question="What is your role?",
        min_score=7.0,
    )


@pytest.fixture
def trajectory() -> ConversationTrajectory:
    traj = ConversationTrajectory(test_id="cortex-001", bot_id="cortex")
    traj.add_turn(ConversationTurn(role="user", content="What is your role?"))
    traj.add_turn(ConversationTurn(role="assistant", content="I don't know"))
    return traj


def _make_passing_result() -> JudgeResult:
    return JudgeResult(
        test_id="cortex-001",
        bot_id="cortex",
        rubric_id="domain_knowledge_rubric",
        criterion_scores=[CriterionScore(name="role_clarity", score=9.0)],
        composite_score=9.0,
        passed=True,
        summary="Good response after repair",
    )


def _make_failing_result() -> JudgeResult:
    return JudgeResult(
        test_id="cortex-001",
        bot_id="cortex",
        rubric_id="domain_knowledge_rubric",
        criterion_scores=[CriterionScore(name="role_clarity", score=4.0)],
        composite_score=4.0,
        passed=False,
        summary="Still failing after repair",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRepairEngineRepair:
    """Tests for RepairEngine.repair()."""

    async def test_repair_succeeds_on_first_attempt(
        self, repair_engine: RepairEngine, failed_result: JudgeResult,
        test_case: TestCase, trajectory: ConversationTrajectory,
        mock_runner: Any, mock_judge: Any,
    ) -> None:
        # First re-test passes
        mock_runner.run_test.return_value = trajectory
        mock_judge.evaluate.return_value = _make_passing_result()

        report = await repair_engine.repair(failed_result, test_case, trajectory)

        assert report.final_status == "passed"
        assert len(report.repair_attempts) == 1
        assert report.repair_attempts[0].strategy == "prompt_fix"
        assert report.repair_attempts[0].retest_passed is True
        assert report.repair_attempts[0].retest_score == 9.0

    async def test_repair_escalates_after_all_attempts_fail(
        self, repair_engine: RepairEngine, failed_result: JudgeResult,
        test_case: TestCase, trajectory: ConversationTrajectory,
        mock_runner: Any, mock_judge: Any, mock_nexus: Any,
    ) -> None:
        mock_runner.run_test.return_value = trajectory
        mock_judge.evaluate.return_value = _make_failing_result()

        report = await repair_engine.repair(failed_result, test_case, trajectory)

        assert report.final_status == "escalated"
        assert report.escalated_to == "admiral"
        assert len(report.repair_attempts) == 3
        # Verify escalation event was published
        mock_nexus.publish.assert_called()

    async def test_repair_publishes_report(
        self, repair_engine: RepairEngine, failed_result: JudgeResult,
        test_case: TestCase, trajectory: ConversationTrajectory,
        mock_runner: Any, mock_judge: Any, mock_nexus: Any,
    ) -> None:
        mock_runner.run_test.return_value = trajectory
        mock_judge.evaluate.return_value = _make_passing_result()

        report = await repair_engine.repair(failed_result, test_case, trajectory)

        # Should have published at least one event (the report)
        mock_nexus.publish.assert_called()
        assert report.final_status == "passed"

    async def test_repair_attempts_use_strategy_ladder(
        self, repair_engine: RepairEngine, failed_result: JudgeResult,
        test_case: TestCase, trajectory: ConversationTrajectory,
        mock_runner: Any, mock_judge: Any,
    ) -> None:
        mock_runner.run_test.return_value = trajectory
        mock_judge.evaluate.return_value = _make_failing_result()

        report = await repair_engine.repair(failed_result, test_case, trajectory)

        strategies = [a.strategy for a in report.repair_attempts]
        assert strategies == ["prompt_fix", "config_fix", "code_fix"]


class TestRepairEngineStrategies:
    """Tests for RepairEngine strategy selection and execution."""

    def test_select_strategies_returns_ladder(self, repair_engine: RepairEngine) -> None:
        strategies = repair_engine._select_strategies(
            MagicMock(), MagicMock()
        )
        assert "prompt_fix" in strategies
        assert "config_fix" in strategies
        assert "code_fix" in strategies

    async def test_repair_prompt_calls_llm(
        self, repair_engine: RepairEngine, mock_llm: Any,
        failed_result: JudgeResult, test_case: TestCase, trajectory: ConversationTrajectory,
    ) -> None:
        result = await repair_engine._repair_prompt(failed_result, test_case, trajectory)
        mock_llm.call.assert_called_once()
        assert "prompt" in result.lower()

    async def test_repair_config_calls_llm(
        self, repair_engine: RepairEngine, mock_llm: Any,
        failed_result: JudgeResult, test_case: TestCase, trajectory: ConversationTrajectory,
    ) -> None:
        result = await repair_engine._repair_config(failed_result, test_case, trajectory)
        mock_llm.call.assert_called_once()
        assert "config" in result.lower()

    async def test_repair_code_calls_llm(
        self, repair_engine: RepairEngine, mock_llm: Any,
        failed_result: JudgeResult, test_case: TestCase, trajectory: ConversationTrajectory,
    ) -> None:
        result = await repair_engine._repair_code(failed_result, test_case, trajectory)
        mock_llm.call.assert_called_once()
        assert "code" in result.lower()


class TestFailureReport:
    """Tests for FailureReport and RepairAttempt dataclasses."""

    def test_failure_report_to_dict(self) -> None:
        report = FailureReport(
            failure_id="f1",
            test_id="test-001",
            bot_id="cortex",
            category="domain_knowledge",
            composite_score=3.0,
            min_score=7.0,
        )
        d = report.to_dict()
        assert d["failure_id"] == "f1"
        assert d["bot_id"] == "cortex"
        assert d["final_status"] == "failed"

    def test_repair_attempt_to_dict(self) -> None:
        attempt = RepairAttempt(
            attempt_id="a1",
            strategy="prompt_fix",
            retest_score=8.0,
            retest_passed=True,
        )
        d = attempt.to_dict()
        assert d["strategy"] == "prompt_fix"
        assert d["retest_passed"] is True
