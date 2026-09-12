"""Sentinel orchestrator — the autonomous testing and validation agent.

The Sentinel runs scheduled test cycles, handles on-demand test requests,
sweeps the codebase for changes, and publishes cycle summaries.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nexus.bus.event import EventType, NexusEvent
from nexus.testing.conversation import ConversationRunner
from nexus.testing.judge import AgentJudge, JudgeResult
from nexus.testing.posterior import BotPosterior, PosteriorStore
from nexus.testing.recipe import RecipeRegistry, TestRecipe
from nexus.testing.repair import FailureReport, RepairEngine

logger = logging.getLogger(__name__)


@dataclass
class TestCycleResult:
    """Results of a single test cycle for one bot.

    Attributes:
        bot_id: The bot that was tested.
        total_tests: Total number of tests run.
        passed: Number of tests that passed.
        failed: Number of tests that failed.
        repaired: Number of tests that were repaired.
        escalated: Number of tests that were escalated.
        results: List of JudgeResult objects.
        failure_reports: List of FailureReport objects.
        duration_s: Duration in seconds.
        timestamp: ISO-8601 timestamp.
    """

    bot_id: str
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    repaired: int = 0
    escalated: int = 0
    results: list[JudgeResult] = field(default_factory=list)
    failure_reports: list[FailureReport] = field(default_factory=list)
    duration_s: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "repaired": self.repaired,
            "escalated": self.escalated,
            "results": [r.to_dict() for r in self.results],
            "failure_reports": [f.to_dict() for f in self.failure_reports],
            "duration_s": self.duration_s,
            "timestamp": self.timestamp,
        }


class Sentinel:
    """The Sentinel orchestrator — autonomous testing and validation agent.

    Runs scheduled test cycles every 6 hours, codebase sweeps every 24 hours,
    and handles on-demand test requests via Nexus Bus events.
    """

    TEST_CYCLE_INTERVAL_S: int = 6 * 60 * 60
    CODEBASE_SWEEP_INTERVAL_S: int = 24 * 60 * 60

    def __init__(
        self,
        nexus: Any,
        llm_client: Any,
        redis_client: Any,
        registry: RecipeRegistry | None = None,
    ) -> None:
        self._nexus = nexus
        self._llm_client = llm_client
        self._redis = redis_client
        self._registry = registry or RecipeRegistry()
        self._posterior_store = PosteriorStore(redis_client)
        self._runner = ConversationRunner(nexus, llm_client)
        self._judge = AgentJudge(llm_client)
        self._repair_engine = RepairEngine(nexus, llm_client, self._runner, self._judge)
        self._running = False
        self._test_cycle_task: asyncio.Task[None] | None = None
        self._sweep_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the Sentinel — subscribe to events and start scheduled loops."""
        self._running = True
        await self._nexus.subscribe(EventType.TESTING_RUN_NOW, self._handle_run_request)
        await self._nexus.subscribe(
            EventType.TESTING_RECIPE_UPDATED, self._handle_recipe_update
        )
        self._test_cycle_task = asyncio.create_task(self._scheduled_test_cycle())
        self._sweep_task = asyncio.create_task(self._scheduled_codebase_sweep())
        logger.info("Sentinel started — test cycle every %ds, sweep every %ds",
                     self.TEST_CYCLE_INTERVAL_S, self.CODEBASE_SWEEP_INTERVAL_S)

    async def stop(self) -> None:
        """Stop the Sentinel."""
        self._running = False
        if self._test_cycle_task is not None:
            self._test_cycle_task.cancel()
            try:
                await self._test_cycle_task
            except asyncio.CancelledError:
                pass
            self._test_cycle_task = None
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None
        logger.info("Sentinel stopped")

    async def run_full_cycle(self) -> dict[str, TestCycleResult]:
        """Run a full test cycle for all bots with recipes.

        Returns:
            Mapping of bot_id -> TestCycleResult.
        """
        self._registry.load_all()
        bot_ids = self._registry.all_bot_ids()
        results: dict[str, TestCycleResult] = {}

        for bot_id in bot_ids:
            try:
                result = await self._test_bot(bot_id)
                results[bot_id] = result
            except Exception as exc:
                logger.error("Test cycle failed for bot %s: %s", bot_id, exc)
                results[bot_id] = TestCycleResult(
                    bot_id=bot_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

        await self._publish_cycle_summary(results)
        return results

    async def _test_bot(self, bot_id: str) -> TestCycleResult:
        """Run all tests for a single bot.

        Args:
            bot_id: The bot to test.

        Returns:
            A TestCycleResult.
        """
        import time

        start_time = time.monotonic()
        result = TestCycleResult(
            bot_id=bot_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        try:
            recipe = self._registry.get(bot_id)
        except KeyError:
            logger.warning("No recipe found for bot %s", bot_id)
            return result

        # Load posterior for adaptive testing
        posterior = await self._posterior_store.load(bot_id)

        for test_case in recipe.cases:
            result.total_tests += 1
            trajectory = await self._runner.run_test(bot_id, test_case)
            judge_result = await self._judge.evaluate(trajectory, test_case)
            result.results.append(judge_result)

            # Update posterior
            posterior.update(test_case.category, judge_result.composite_score, judge_result.passed)

            if judge_result.passed:
                result.passed += 1
            else:
                result.failed += 1
                # Attempt repair
                failure_report = await self._repair_engine.repair(
                    judge_result, test_case, trajectory
                )
                result.failure_reports.append(failure_report)

                if failure_report.final_status == "passed":
                    result.repaired += 1
                elif failure_report.final_status == "escalated":
                    result.escalated += 1

        # Save posterior
        await self._posterior_store.save(posterior)

        result.duration_s = time.monotonic() - start_time
        logger.info(
            "Test cycle for %s: %d passed, %d failed, %d repaired, %d escalated",
            bot_id,
            result.passed,
            result.failed,
            result.repaired,
            result.escalated,
        )
        return result

    async def _scheduled_test_cycle(self) -> None:
        """Run scheduled test cycles at the configured interval."""
        while self._running:
            try:
                await self.run_full_cycle()
            except Exception as exc:
                logger.error("Scheduled test cycle failed: %s", exc)
            await asyncio.sleep(self.TEST_CYCLE_INTERVAL_S)

    async def _scheduled_codebase_sweep(self) -> None:
        """Run scheduled codebase sweeps at the configured interval."""
        while self._running:
            try:
                await self._sweep_codebase()
            except Exception as exc:
                logger.error("Scheduled codebase sweep failed: %s", exc)
            await asyncio.sleep(self.CODEBASE_SWEEP_INTERVAL_S)

    async def _sweep_codebase(self) -> None:
        """Sweep the codebase for changes and update test recipes."""
        from nexus.testing.generator import RecipeGenerator

        generator = RecipeGenerator(self._registry, self._llm_client, self._nexus)
        # In a real implementation, this would analyze git diffs
        # For now, just log
        logger.info("Codebase sweep completed (no changes detected)")

    async def _handle_run_request(self, event: NexusEvent) -> None:
        """Handle a testing.run_now event.

        Args:
            event: The NexusEvent requesting a test run.
        """
        bot_id = event.payload.get("bot_id", "")
        if bot_id:
            logger.info("Received run request for bot %s", bot_id)
            try:
                result = await self._test_bot(bot_id)
                await self._publish_cycle_summary({bot_id: result})
            except Exception as exc:
                logger.error("Run request failed for %s: %s", bot_id, exc)
        else:
            logger.info("Received run request for all bots")
            await self.run_full_cycle()

    async def _handle_recipe_update(self, event: NexusEvent) -> None:
        """Handle a testing.recipe_updated event.

        Args:
            event: The NexusEvent with recipe update info.
        """
        bot_id = event.payload.get("bot_id", "")
        if bot_id:
            logger.info("Recipe updated for bot %s, reloading", bot_id)
            self._registry.load_all()

    async def _publish_cycle_summary(self, results: dict[str, TestCycleResult]) -> None:
        """Publish a test cycle summary to the Nexus Bus.

        Args:
            results: The test cycle results.
        """
        total_passed = sum(r.passed for r in results.values())
        total_failed = sum(r.failed for r in results.values())
        total_tests = sum(r.total_tests for r in results.values())

        event = NexusEvent.create(
            event_type=EventType.TESTING_CYCLE_COMPLETE,
            source="sentinel",
            target="broadcast",
            payload={
                "bot_id": "sentinel",
                "cycle_id": datetime.now(timezone.utc).isoformat(),
                "passed": total_passed,
                "failed": total_failed,
                "skipped": 0,
                "total_tests": total_tests,
                "results": {bid: r.to_dict() for bid, r in results.items()},
            },
        )
        await self._nexus.publish(event)
        logger.info(
            "Published cycle summary: %d passed, %d failed, %d total",
            total_passed,
            total_failed,
            total_tests,
        )
