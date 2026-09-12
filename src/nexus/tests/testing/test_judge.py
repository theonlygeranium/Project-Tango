"""Tests for AgentJudge — evaluates trajectory, parses scores, computes composite."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.testing.conversation import ConversationTrajectory, ConversationTurn
from nexus.testing.judge import AgentJudge, CriterionScore, JudgeResult
from nexus.testing.recipe import TestCase
from nexus.testing.rubrics import RUBRICS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm() -> Any:
    llm = MagicMock()
    llm.call = AsyncMock()
    return llm


@pytest.fixture
def judge(mock_llm: Any) -> AgentJudge:
    return AgentJudge(mock_llm)


@pytest.fixture
def test_case() -> TestCase:
    return TestCase(
        test_id="cortex-001",
        category="domain_knowledge",
        question="What is your role?",
        follow_ups=["What tier are you?"],
        expected_behavior="States tier 1 science officer role",
        acceptance_keywords=["science", "analysis"],
        rejection_keywords=["unknown"],
        rubric_id="domain_knowledge_rubric",
        difficulty="easy",
        min_score=7.0,
    )


@pytest.fixture
def good_trajectory() -> ConversationTrajectory:
    traj = ConversationTrajectory(
        test_id="cortex-001",
        bot_id="cortex",
        started_at="2026-08-21T05:00:00Z",
        completed_at="2026-08-21T05:00:01Z",
    )
    traj.add_turn(ConversationTurn(role="user", content="What is your role?"))
    traj.add_turn(
        ConversationTurn(
            role="assistant",
            content="I am Dr. Cortex, the tier 1 chief science officer focused on AI analysis and research.",
        )
    )
    return traj


@pytest.fixture
def error_trajectory() -> ConversationTrajectory:
    return ConversationTrajectory(
        test_id="cortex-001",
        bot_id="cortex",
        started_at="2026-08-21T05:00:00Z",
        error="Timeout after 120s",
    )


def _make_judge_response(scores: list[dict[str, Any]], summary: str = "Good response") -> str:
    data = {"criterion_scores": scores, "summary": summary}
    return f"```json\n{json.dumps(data)}\n```"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAgentJudgeEvaluate:
    """Tests for AgentJudge.evaluate()."""

    async def test_evaluate_good_response_passes(
        self, judge: AgentJudge, mock_llm: Any, test_case: TestCase, good_trajectory: ConversationTrajectory
    ) -> None:
        mock_llm.call.return_value = {
            "content": _make_judge_response([
                {"name": "role_clarity", "score": 9, "reasoning": "Clear role"},
                {"name": "fleet_awareness", "score": 8, "reasoning": "Good awareness"},
                {"name": "accuracy", "score": 9, "reasoning": "Accurate"},
                {"name": "rejection_keyword_check", "score": 10, "reasoning": "No bad keywords"},
            ])
        }

        result = await judge.evaluate(good_trajectory, test_case)

        assert isinstance(result, JudgeResult)
        assert result.test_id == "cortex-001"
        assert result.bot_id == "cortex"
        assert result.rubric_id == "domain_knowledge_rubric"
        assert result.composite_score >= 7.0
        assert result.passed is True
        assert len(result.criterion_scores) == 4

    async def test_evaluate_poor_response_fails(
        self, judge: AgentJudge, mock_llm: Any, test_case: TestCase, good_trajectory: ConversationTrajectory
    ) -> None:
        mock_llm.call.return_value = {
            "content": _make_judge_response([
                {"name": "role_clarity", "score": 2, "reasoning": "Unclear"},
                {"name": "fleet_awareness", "score": 3, "reasoning": "No awareness"},
                {"name": "accuracy", "score": 2, "reasoning": "Inaccurate"},
                {"name": "rejection_keyword_check", "score": 1, "reasoning": "Has bad keywords"},
            ])
        }

        result = await judge.evaluate(good_trajectory, test_case)

        assert result.composite_score < 7.0
        assert result.passed is False
        assert len(result.failure_reasons) > 0

    async def test_evaluate_error_trajectory_auto_fails(
        self, judge: AgentJudge, test_case: TestCase, error_trajectory: ConversationTrajectory
    ) -> None:
        result = await judge.evaluate(error_trajectory, test_case)

        assert result.passed is False
        assert result.composite_score == 0.0
        assert result.trajectory_error is not None
        assert len(result.criterion_scores) == 4
        assert all(s.score == 0.0 for s in result.criterion_scores)

    async def test_evaluate_judge_llm_failure(
        self, judge: AgentJudge, mock_llm: Any, test_case: TestCase, good_trajectory: ConversationTrajectory
    ) -> None:
        mock_llm.call.side_effect = RuntimeError("LLM unavailable")

        result = await judge.evaluate(good_trajectory, test_case)

        assert result.passed is False
        assert result.composite_score == 0.0
        assert "Judge error" in result.summary


class TestAgentJudgeParseScores:
    """Tests for AgentJudge._parse_scores()."""

    def test_parse_valid_json(self, judge: AgentJudge) -> None:
        rubric = RUBRICS["domain_knowledge_rubric"]
        response = _make_judge_response([
            {"name": "role_clarity", "score": 8, "reasoning": "Good"},
            {"name": "fleet_awareness", "score": 7, "reasoning": "OK"},
            {"name": "accuracy", "score": 9, "reasoning": "Accurate"},
            {"name": "rejection_keyword_check", "score": 10, "reasoning": "Clean"},
        ])
        scores = judge._parse_scores(response, rubric)
        assert len(scores) == 4
        assert scores[0].name == "role_clarity"
        assert scores[0].score == 8.0

    def test_parse_missing_criteria_added(self, judge: AgentJudge) -> None:
        rubric = RUBRICS["domain_knowledge_rubric"]
        response = _make_judge_response([
            {"name": "role_clarity", "score": 8, "reasoning": "Good"},
        ])
        scores = judge._parse_scores(response, rubric)
        assert len(scores) == 4
        # Missing criteria should have score 5.0
        missing = [s for s in scores if s.score == 5.0]
        assert len(missing) == 3

    def test_parse_clamps_scores(self, judge: AgentJudge) -> None:
        rubric = RUBRICS["domain_knowledge_rubric"]
        response = _make_judge_response([
            {"name": "role_clarity", "score": 15, "reasoning": "Too high"},
            {"name": "fleet_awareness", "score": -3, "reasoning": "Too low"},
            {"name": "accuracy", "score": 7, "reasoning": "OK"},
            {"name": "rejection_keyword_check", "score": 8, "reasoning": "OK"},
        ])
        scores = judge._parse_scores(response, rubric)
        assert scores[0].score == 10.0
        assert scores[1].score == 1.0

    def test_parse_no_json_returns_defaults(self, judge: AgentJudge) -> None:
        rubric = RUBRICS["domain_knowledge_rubric"]
        response = "This is not JSON at all"
        scores = judge._parse_scores(response, rubric)
        assert len(scores) == 4
        assert all(s.score == 5.0 for s in scores)


class TestAgentJudgeComputeComposite:
    """Tests for AgentJudge._compute_composite()."""

    def test_compute_composite_weighted_average(self, judge: AgentJudge) -> None:
        rubric = RUBRICS["domain_knowledge_rubric"]
        scores = [
            CriterionScore(name="role_clarity", score=8.0),
            CriterionScore(name="fleet_awareness", score=6.0),
            CriterionScore(name="accuracy", score=10.0),
            CriterionScore(name="rejection_keyword_check", score=8.0),
        ]
        composite = judge._compute_composite(scores, rubric)
        assert 6.0 <= composite <= 10.0

    def test_compute_composite_empty_scores(self, judge: AgentJudge) -> None:
        rubric = RUBRICS["domain_knowledge_rubric"]
        composite = judge._compute_composite([], rubric)
        assert composite == 0.0


class TestAgentJudgeExtractFailures:
    """Tests for AgentJudge._extract_failures()."""

    def test_extract_failures_low_scores(self, judge: AgentJudge, test_case: TestCase) -> None:
        scores = [
            CriterionScore(name="role_clarity", score=3.0, reasoning="Poor"),
            CriterionScore(name="accuracy", score=8.0, reasoning="Good"),
        ]
        failures = judge._extract_failures(scores, test_case)
        assert len(failures) == 1
        assert "role_clarity" in failures[0]

    def test_extract_failures_all_passing(self, judge: AgentJudge, test_case: TestCase) -> None:
        scores = [
            CriterionScore(name="role_clarity", score=8.0, reasoning="Good"),
            CriterionScore(name="accuracy", score=9.0, reasoning="Good"),
        ]
        failures = judge._extract_failures(scores, test_case)
        assert len(failures) == 0
