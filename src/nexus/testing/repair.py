"""Failure documentation, repair attempt, and re-test loop.

The RepairEngine takes a failed test, attempts to fix it using a strategy
ladder (prompt_fix -> config_fix -> code_fix -> escalate), and re-tests
after each attempt. If all strategies fail, it escalates to the Admiral.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from nexus.bus.event import EventType, NexusEvent
from nexus.testing.conversation import ConversationTrajectory
from nexus.testing.judge import AgentJudge, JudgeResult
from nexus.testing.recipe import TestCase

logger = logging.getLogger(__name__)


@dataclass
class FailureReport:
    """Report of a test failure and repair attempts.

    Attributes:
        failure_id: Unique identifier for this failure.
        test_id: The test case that failed.
        bot_id: The bot that failed.
        category: Test category.
        composite_score: The score that caused the failure.
        min_score: The minimum score required to pass.
        failure_reasons: List of failure reason strings.
        trajectory_summary: Brief summary of the trajectory.
        timestamp: ISO-8601 timestamp.
        repair_attempts: List of RepairAttempt objects.
        final_status: "passed", "failed", or "escalated".
        escalated_to: Who the failure was escalated to, if any.
    """

    failure_id: str
    test_id: str
    bot_id: str
    category: str
    composite_score: float
    min_score: float
    failure_reasons: list[str] = field(default_factory=list)
    trajectory_summary: str = ""
    timestamp: str = ""
    repair_attempts: list[RepairAttempt] = field(default_factory=list)
    final_status: str = "failed"
    escalated_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "test_id": self.test_id,
            "bot_id": self.bot_id,
            "category": self.category,
            "composite_score": self.composite_score,
            "min_score": self.min_score,
            "failure_reasons": self.failure_reasons,
            "trajectory_summary": self.trajectory_summary,
            "timestamp": self.timestamp,
            "repair_attempts": [a.to_dict() for a in self.repair_attempts],
            "final_status": self.final_status,
            "escalated_to": self.escalated_to,
        }


@dataclass
class RepairAttempt:
    """A single repair attempt.

    Attributes:
        attempt_id: Unique identifier.
        strategy: The repair strategy used.
        description: Description of the repair.
        timestamp: ISO-8601 timestamp.
        retest_score: Score after re-test.
        retest_passed: Whether the re-test passed.
        error: Error message if the repair failed.
    """

    attempt_id: str
    strategy: str
    description: str = ""
    timestamp: str = ""
    retest_score: float = 0.0
    retest_passed: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "strategy": self.strategy,
            "description": self.description,
            "timestamp": self.timestamp,
            "retest_score": self.retest_score,
            "retest_passed": self.retest_passed,
            "error": self.error,
        }


class RepairEngine:
    """Attempts to repair failed tests using a strategy ladder.

    Strategy ladder: prompt_fix -> config_fix -> code_fix -> escalate.
    Each attempt is followed by a re-test.
    """

    MAX_REPAIR_ATTEMPTS: int = 3

    def __init__(
        self,
        nexus: Any,
        llm_client: Any,
        conversation_runner: ConversationRunner,
        judge: AgentJudge,
    ) -> None:
        self._nexus = nexus
        self._llm_client = llm_client
        self._runner = conversation_runner
        self._judge = judge

    async def repair(
        self,
        failure: JudgeResult,
        test_case: TestCase,
        trajectory: ConversationTrajectory,
    ) -> FailureReport:
        """Attempt to repair a failed test.

        Args:
            failure: The judge result that failed.
            test_case: The test case that was run.
            trajectory: The conversation trajectory.

        Returns:
            A FailureReport with all repair attempts and final status.
        """
        report = FailureReport(
            failure_id=str(uuid4()),
            test_id=failure.test_id,
            bot_id=failure.bot_id,
            category=test_case.category,
            composite_score=failure.composite_score,
            min_score=test_case.min_score,
            failure_reasons=failure.failure_reasons,
            trajectory_summary=failure.summary,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        strategies = self._select_strategies(failure, test_case)

        for i, strategy in enumerate(strategies[: self.MAX_REPAIR_ATTEMPTS]):
            attempt_id = f"{report.failure_id}-attempt-{i + 1}"
            logger.info(
                "Repair attempt %d/%d for %s: strategy=%s",
                i + 1,
                self.MAX_REPAIR_ATTEMPTS,
                failure.test_id,
                strategy,
            )

            attempt = RepairAttempt(
                attempt_id=attempt_id,
                strategy=strategy,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

            try:
                description = await self._execute_repair(strategy, failure, test_case, trajectory)
                attempt.description = description

                # Re-test after repair
                new_trajectory = await self._runner.run_test(failure.bot_id, test_case)
                new_result = await self._judge.evaluate(new_trajectory, test_case)

                attempt.retest_score = new_result.composite_score
                attempt.retest_passed = new_result.passed

                if new_result.passed:
                    report.final_status = "passed"
                    report.repair_attempts.append(attempt)
                    logger.info("Repair succeeded for %s with strategy %s", failure.test_id, strategy)
                    await self._publish_report(report)
                    return report

            except Exception as exc:
                attempt.error = str(exc)
                logger.error("Repair attempt %s failed: %s", attempt_id, exc)

            report.repair_attempts.append(attempt)

        # All repair attempts failed — escalate
        report.final_status = "escalated"
        report.escalated_to = "admiral"
        await self._escalate(report)
        await self._publish_report(report)
        return report

    def _select_strategies(self, failure: JudgeResult, test_case: TestCase) -> list[str]:
        """Select repair strategies based on the failure.

        Args:
            failure: The judge result.
            test_case: The test case.

        Returns:
            Ordered list of strategy names.
        """
        strategies: list[str] = ["prompt_fix", "config_fix", "code_fix"]
        return strategies

    async def _execute_repair(
        self,
        strategy: str,
        failure: JudgeResult,
        test_case: TestCase,
        trajectory: ConversationTrajectory,
    ) -> str:
        """Execute a single repair strategy.

        Args:
            strategy: The strategy name.
            failure: The judge result.
            test_case: The test case.
            trajectory: The conversation trajectory.

        Returns:
            Description of the repair.
        """
        if strategy == "prompt_fix":
            return await self._repair_prompt(failure, test_case, trajectory)
        elif strategy == "config_fix":
            return await self._repair_config(failure, test_case, trajectory)
        elif strategy == "code_fix":
            return await self._repair_code(failure, test_case, trajectory)
        else:
            raise ValueError(f"Unknown repair strategy: {strategy}")

    async def _repair_prompt(
        self,
        failure: JudgeResult,
        test_case: TestCase,
        trajectory: ConversationTrajectory,
    ) -> str:
        """Attempt to fix the bot's system prompt.

        Args:
            failure: The judge result.
            test_case: The test case.
            trajectory: The conversation trajectory.

        Returns:
            Description of the prompt fix.
        """
        prompt = f"""A bot failed a test. Suggest a prompt fix.

Bot: {failure.bot_id}
Test: {failure.test_id}
Failure reasons: {failure.failure_reasons}
Current summary: {failure.summary}

Suggest a specific change to the bot's system prompt that would fix this failure.
Respond with just the suggested prompt change."""

        try:
            response = await self._llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                model="writer/palmyra-x6",
                temperature=0.3,
            )
            suggestion = ""
            if isinstance(response, dict):
                suggestion = response.get("content", "")
            return f"Prompt fix suggestion: {suggestion[:200]}"
        except Exception as exc:
            logger.error("Prompt repair LLM call failed: %s", exc)
            return f"Prompt repair failed: {exc}"

    async def _repair_config(
        self,
        failure: JudgeResult,
        test_case: TestCase,
        trajectory: ConversationTrajectory,
    ) -> str:
        """Attempt to fix the bot's configuration.

        Args:
            failure: The judge result.
            test_case: The test case.
            trajectory: The conversation trajectory.

        Returns:
            Description of the config fix.
        """
        prompt = f"""A bot failed a test. Suggest a configuration fix.

Bot: {failure.bot_id}
Test: {failure.test_id}
Failure reasons: {failure.failure_reasons}

Suggest a specific configuration change (e.g. circuit breaker thresholds,
health check intervals, tool parameters) that would fix this failure.
Respond with just the suggested config change."""

        try:
            response = await self._llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                model="writer/palmyra-x6",
                temperature=0.3,
            )
            suggestion = ""
            if isinstance(response, dict):
                suggestion = response.get("content", "")
            return f"Config fix suggestion: {suggestion[:200]}"
        except Exception as exc:
            logger.error("Config repair LLM call failed: %s", exc)
            return f"Config repair failed: {exc}"

    async def _repair_code(
        self,
        failure: JudgeResult,
        test_case: TestCase,
        trajectory: ConversationTrajectory,
    ) -> str:
        """Attempt to fix the bot's code.

        Args:
            failure: The judge result.
            test_case: The test case.
            trajectory: The conversation trajectory.

        Returns:
            Description of the code fix.
        """
        prompt = f"""A bot failed a test. Suggest a code fix.

Bot: {failure.bot_id}
Test: {failure.test_id}
Failure reasons: {failure.failure_reasons}
Trajectory error: {trajectory.error}

Suggest a specific code change that would fix this failure.
Respond with just the suggested code change."""

        try:
            response = await self._llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                model="writer/palmyra-x6",
                temperature=0.3,
            )
            suggestion = ""
            if isinstance(response, dict):
                suggestion = response.get("content", "")
            return f"Code fix suggestion: {suggestion[:200]}"
        except Exception as exc:
            logger.error("Code repair LLM call failed: %s", exc)
            return f"Code repair failed: {exc}"

    async def _escalate(self, report: FailureReport) -> None:
        """Escalate a failure to the Admiral.

        Args:
            report: The failure report.
        """
        event = NexusEvent.create(
            event_type=EventType.FAILURE_LOGGED,
            source="sentinel",
            target="admiral",
            payload={
                "bot_id": report.bot_id,
                "failure_type": "test_failure",
                "error_message": f"Test {report.test_id} failed after {len(report.repair_attempts)} repair attempts",
                "stack_trace": None,
                "context": report.to_dict(),
            },
        )
        await self._nexus.publish(event)
        logger.warning("Escalated failure %s to admiral", report.failure_id)

    async def _publish_report(self, report: FailureReport) -> None:
        """Publish the failure report to the Nexus Bus.

        Args:
            report: The failure report.
        """
        event = NexusEvent.create(
            event_type=EventType.FLYWHEEL_TEST_RESULTS,
            source="sentinel",
            target="broadcast",
            payload={
                "bot_id": report.bot_id,
                "test_id": report.test_id,
                "results": report.to_dict(),
            },
        )
        await self._nexus.publish(event)
        logger.info("Published failure report for %s", report.test_id)
