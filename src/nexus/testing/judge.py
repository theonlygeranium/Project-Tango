"""Agent-as-a-Judge evaluator — uses LLM to score conversation trajectories.

The judge evaluates the full conversation trajectory (not just the final answer)
against a structured rubric, producing per-criterion scores, a weighted composite,
pass/fail determination, and failure reasons.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from nexus.testing.conversation import ConversationTrajectory
from nexus.testing.recipe import TestCase
from nexus.testing.rubrics import Rubric, RubricCriterion, RUBRICS

logger = logging.getLogger(__name__)


@dataclass
class CriterionScore:
    """Score for a single rubric criterion.

    Attributes:
        name: Criterion name.
        score: Score from 1 to 10.
        reasoning: Explanation for the score.
    """

    name: str
    score: float
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "score": self.score, "reasoning": self.reasoning}


@dataclass
class JudgeResult:
    """Complete evaluation result from the judge.

    Attributes:
        test_id: The test case ID.
        bot_id: The bot that was tested.
        rubric_id: The rubric used for evaluation.
        criterion_scores: Per-criterion scores.
        composite_score: Weighted average score (1-10).
        passed: Whether the test passed (composite >= min_score).
        summary: Brief summary of the evaluation.
        failure_reasons: List of reasons if the test failed.
        trajectory_error: Error from the trajectory, if any.
    """

    test_id: str
    bot_id: str
    rubric_id: str
    criterion_scores: list[CriterionScore] = field(default_factory=list)
    composite_score: float = 0.0
    passed: bool = False
    summary: str = ""
    failure_reasons: list[str] = field(default_factory=list)
    trajectory_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "bot_id": self.bot_id,
            "rubric_id": self.rubric_id,
            "criterion_scores": [c.to_dict() for c in self.criterion_scores],
            "composite_score": self.composite_score,
            "passed": self.passed,
            "summary": self.summary,
            "failure_reasons": self.failure_reasons,
            "trajectory_error": self.trajectory_error,
        }


class AgentJudge:
    """LLM-powered judge that evaluates conversation trajectories.

    Uses writer/palmyra-x6 with temperature=0.3 for consistency.
    Evaluates the full trajectory, not just the final answer.
    """

    JUDGE_MODEL: str = "writer/palmyra-x6"
    JUDGE_TEMPERATURE: float = 0.3

    def __init__(self, llm_client: Any) -> None:
        self._llm_client = llm_client

    async def evaluate(
        self,
        trajectory: ConversationTrajectory,
        test_case: TestCase,
    ) -> JudgeResult:
        """Evaluate a conversation trajectory against a test case.

        Args:
            trajectory: The conversation trajectory to evaluate.
            test_case: The test case that was run.

        Returns:
            A JudgeResult with scores and pass/fail determination.
        """
        rubric = RUBRICS.get(test_case.rubric_id)
        if rubric is None:
            rubric = RUBRICS["domain_knowledge_rubric"]

        result = JudgeResult(
            test_id=test_case.test_id,
            bot_id=trajectory.bot_id,
            rubric_id=rubric.rubric_id,
            trajectory_error=trajectory.error,
        )

        # If trajectory had an error, auto-fail
        if trajectory.error is not None:
            result.composite_score = 0.0
            result.passed = False
            result.summary = f"Trajectory error: {trajectory.error}"
            result.failure_reasons = [f"Trajectory error: {trajectory.error}"]
            for criterion in rubric.criteria:
                result.criterion_scores.append(
                    CriterionScore(name=criterion.name, score=0.0, reasoning="Trajectory error")
                )
            return result

        # Build the judge prompt and get LLM evaluation
        prompt = self._build_judge_prompt(trajectory, test_case, rubric)
        try:
            response = await self._llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                model=self.JUDGE_MODEL,
                temperature=self.JUDGE_TEMPERATURE,
            )
            response_text = ""
            if isinstance(response, dict):
                response_text = response.get("content", "")
            elif isinstance(response, str):
                response_text = response

            result.criterion_scores = self._parse_scores(response_text, rubric)
            result.composite_score = self._compute_composite(result.criterion_scores, rubric)
            result.failure_reasons = self._extract_failures(result.criterion_scores, test_case)
            result.summary = self._extract_summary(response_text)
            result.passed = result.composite_score >= test_case.min_score

        except Exception as exc:
            logger.error("Judge evaluation failed for test %s: %s", test_case.test_id, exc)
            result.composite_score = 0.0
            result.passed = False
            result.summary = f"Judge error: {exc}"
            result.failure_reasons = [f"Judge error: {exc}"]
            for criterion in rubric.criteria:
                result.criterion_scores.append(
                    CriterionScore(name=criterion.name, score=0.0, reasoning="Judge error")
                )

        return result

    def _build_judge_prompt(
        self,
        trajectory: ConversationTrajectory,
        test_case: TestCase,
        rubric: Rubric,
    ) -> str:
        """Build the prompt for the judge LLM.

        Args:
            trajectory: The conversation trajectory.
            test_case: The test case.
            rubric: The rubric to use.

        Returns:
            The prompt string.
        """
        messages = trajectory.to_judge_format()
        conversation_text = ""
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            conversation_text += f"\n[{role}]: {content}"
            if "tool_name" in msg and msg["tool_name"] is not None:
                conversation_text += f"\n  (tool: {msg['tool_name']}, args: {msg.get('tool_args')})"
                conversation_text += f"\n  (result: {msg.get('tool_result')})"

        criteria_text = ""
        for c in rubric.criteria:
            criteria_text += (
                f"\n  - {c.name}: {c.description}\n"
                f"    1 (poor): {c.anchor_1}\n"
                f"    4 (below avg): {c.anchor_4}\n"
                f"    7 (good): {c.anchor_7}\n"
                f"    10 (excellent): {c.anchor_10}\n"
                f"    weight: {c.weight}"
            )

        acceptance_kw = ", ".join(test_case.acceptance_keywords) or "none"
        rejection_kw = ", ".join(test_case.rejection_keywords) or "none"

        prompt = f"""You are a strict test judge evaluating a bot conversation.

## Test Case
- Test ID: {test_case.test_id}
- Category: {test_case.category}
- Difficulty: {test_case.difficulty}
- Expected behavior: {test_case.expected_behavior}
- Acceptance keywords: {acceptance_kw}
- Rejection keywords: {rejection_kw}
- Minimum passing score: {test_case.min_score}

## Conversation Trajectory
{conversation_text}

## Rubric: {rubric.rubric_id}
Score each criterion from 1 to 10 based on the anchors:{criteria_text}

## Instructions
Evaluate the FULL conversation trajectory, not just the final answer.
Check if acceptance keywords appear and rejection keywords do not appear.

Respond in JSON format:
```json
{{
  "criterion_scores": [
    {{"name": "<criterion_name>", "score": <1-10>, "reasoning": "<explanation>"}}
  ],
  "summary": "<brief evaluation summary>"
}}
```
"""
        return prompt

    def _parse_scores(self, response: str, rubric: Rubric) -> list[CriterionScore]:
        """Parse the judge LLM response into criterion scores.

        Args:
            response: The raw LLM response text.
            rubric: The rubric used for evaluation.

        Returns:
            List of CriterionScore objects.
        """
        # Try to extract JSON from the response
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find a bare JSON object
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                logger.warning("Could not parse JSON from judge response")
                return [
                    CriterionScore(name=c.name, score=5.0, reasoning="Parse failure")
                    for c in rubric.criteria
                ]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse judge JSON: %s", exc)
            return [
                CriterionScore(name=c.name, score=5.0, reasoning="JSON parse failure")
                for c in rubric.criteria
            ]

        scores: list[CriterionScore] = []
        for item in data.get("criterion_scores", []):
            name = item.get("name", "")
            score = float(item.get("score", 5.0))
            score = max(1.0, min(10.0, score))
            reasoning = item.get("reasoning", "")
            scores.append(CriterionScore(name=name, score=score, reasoning=reasoning))

        # Ensure all rubric criteria are represented
        existing_names = {s.name for s in scores}
        for criterion in rubric.criteria:
            if criterion.name not in existing_names:
                scores.append(
                    CriterionScore(name=criterion.name, score=5.0, reasoning="Missing from response")
                )

        return scores

    def _compute_composite(self, scores: list[CriterionScore], rubric: Rubric) -> float:
        """Compute the weighted composite score.

        Args:
            scores: List of criterion scores.
            rubric: The rubric with criterion weights.

        Returns:
            Weighted average score (1-10).
        """
        total_weight = 0.0
        weighted_sum = 0.0
        weight_map = {c.name: c.weight for c in rubric.criteria}

        for score in scores:
            weight = weight_map.get(score.name, 1.0)
            weighted_sum += score.score * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return round(weighted_sum / total_weight, 2)

    def _extract_failures(
        self, scores: list[CriterionScore], test_case: TestCase
    ) -> list[str]:
        """Extract failure reasons from low criterion scores.

        Args:
            scores: List of criterion scores.
            test_case: The test case.

        Returns:
            List of failure reason strings.
        """
        failures: list[str] = []
        for score in scores:
            if score.score < 5.0:
                failures.append(
                    f"Criterion '{score.name}' scored {score.score}/10: {score.reasoning}"
                )

        # Check rejection keywords in the trajectory
        # This is a basic check; the judge LLM does the deep analysis
        return failures

    def _extract_summary(self, response: str) -> str:
        """Extract the summary from the judge response.

        Args:
            response: The raw LLM response text.

        Returns:
            The summary string.
        """
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                return ""

        try:
            data = json.loads(json_str)
            return data.get("summary", "")
        except json.JSONDecodeError:
            return ""
