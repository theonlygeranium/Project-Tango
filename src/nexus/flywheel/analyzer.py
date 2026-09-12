"""Weekly analysis engine for the data flywheel.

Dr. Cortex's weekly analysis engine. Analyzes collected failure and
recovery events to produce actionable insights about fleet health trends.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.flywheel.collector import (
    FailureEvent,
    FailureEventCollector,
    LLMCallEvent,
    RecoveryEvent,
)

logger = logging.getLogger(__name__)

REPORT_KEY = "nexus:flywheel:reports"


@dataclass
class AnalysisReport:
    """A weekly analysis report produced by the analysis engine."""

    report_id: str
    period_start: str
    period_end: str
    total_failures: int
    total_recoveries: int
    failure_rate_by_bot: dict[str, float]
    failure_rate_by_dependency: dict[str, float]
    recovery_success_rate: float
    top_failure_types: list[tuple[str, int]]
    recommendations: list[str]
    generated_at: str


class WeeklyAnalysisEngine:
    """Dr. Cortex's weekly analysis engine.

    Analyzes collected failure and recovery events to produce
    actionable insights about fleet health trends.
    """

    def __init__(
        self,
        collector: FailureEventCollector,
        llm_client: Any,
        nexus: NexusBus,
    ) -> None:
        self._collector = collector
        self._llm_client = llm_client
        self._nexus = nexus

    async def run_weekly_analysis(self) -> AnalysisReport:
        """Run the weekly analysis cycle.

        1. Collect all failure/recovery events from the past week
        2. Compute statistics (failure rates, recovery success rates)
        3. Use LLM to generate recommendations
        4. Publish analysis report to Nexus Bus
        5. Store report for historical comparison
        """
        now = datetime.now(timezone.utc)
        period_end = now.isoformat()
        period_start = (now - timedelta(days=7)).isoformat()

        failures = await self._collector.get_failures(since=period_start)
        recoveries = await self._collector.get_recoveries(since=period_start)

        stats = await self._compute_statistics(failures, recoveries)
        recommendations = await self._generate_recommendations(stats)

        report = AnalysisReport(
            report_id=str(uuid4()),
            period_start=period_start,
            period_end=period_end,
            total_failures=len(failures),
            total_recoveries=len(recoveries),
            failure_rate_by_bot=stats["failure_rate_by_bot"],
            failure_rate_by_dependency=stats["failure_rate_by_dependency"],
            recovery_success_rate=stats["recovery_success_rate"],
            top_failure_types=stats["top_failure_types"],
            recommendations=recommendations,
            generated_at=now.isoformat(),
        )

        await self._publish_report(report)
        await self._store_report(report)

        return report

    async def _compute_statistics(
        self, failures: list[FailureEvent], recoveries: list[RecoveryEvent]
    ) -> dict[str, Any]:
        """Compute statistics from failure and recovery events."""
        total_failures = len(failures)
        total_recoveries = len(recoveries)

        # Failure rate by bot (fraction of total failures)
        failure_rate_by_bot: dict[str, float] = {}
        if total_failures > 0:
            bot_counts: dict[str, int] = Counter(f.bot_id for f in failures)
            failure_rate_by_bot = {
                bot: count / total_failures for bot, count in bot_counts.items()
            }

        # Failure rate by dependency
        failure_rate_by_dependency: dict[str, float] = {}
        if total_failures > 0:
            dep_counts: dict[str, int] = Counter(f.dependency for f in failures)
            failure_rate_by_dependency = {
                dep: count / total_failures for dep, count in dep_counts.items()
            }

        # Recovery success rate
        recovery_success_rate = 0.0
        if total_recoveries > 0:
            successful = sum(1 for r in recoveries if r.result == "recovered")
            recovery_success_rate = successful / total_recoveries

        # Top failure types
        type_counts: dict[str, int] = Counter(f.failure_type for f in failures)
        top_failure_types = type_counts.most_common(5)

        return {
            "total_failures": total_failures,
            "total_recoveries": total_recoveries,
            "failure_rate_by_bot": failure_rate_by_bot,
            "failure_rate_by_dependency": failure_rate_by_dependency,
            "recovery_success_rate": recovery_success_rate,
            "top_failure_types": top_failure_types,
        }

    async def _generate_recommendations(self, stats: dict[str, Any]) -> list[str]:
        """Use LLM to generate recommendations from statistics."""
        prompt = (
            "You are Dr. Cortex, chief science officer of the Nexus Fleet. "
            "Analyze the following weekly fleet statistics and provide 3-5 "
            "actionable recommendations for improving fleet reliability.\n\n"
            f"Statistics:\n{json.dumps(stats, indent=2, default=str)}\n\n"
            "Provide each recommendation on a separate line, prefixed with '- '."
        )

        try:
            response = await self._llm_client.call(
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.get("content", "") if isinstance(response, dict) else str(response)
            lines = [
                line.strip().lstrip("- ").strip()
                for line in content.strip().splitlines()
                if line.strip()
            ]
            return lines if lines else ["No recommendations generated."]
        except Exception as exc:
            logger.warning("LLM recommendation generation failed: %s", exc)
            return [f"LLM unavailable — manual review recommended. Error: {exc}"]

    async def _publish_report(self, report: AnalysisReport) -> None:
        """Publish the analysis report to the Nexus Bus."""
        event = NexusEvent.create(
            event_type=EventType.FLYWHEEL_TEST_RESULTS,
            source="weekly_analysis_engine",
            target="broadcast",
            payload={
                "report_id": report.report_id,
                "report_type": "weekly_analysis",
                "total_failures": report.total_failures,
                "total_recoveries": report.total_recoveries,
                "recovery_success_rate": report.recovery_success_rate,
                "recommendations": report.recommendations,
            },
        )
        await self._nexus.publish(event)
        logger.info("Published weekly analysis report %s", report.report_id)

    async def _store_report(self, report: AnalysisReport) -> None:
        """Store the report in Redis for historical comparison."""
        redis = self._nexus._redis
        if redis is None:
            logger.warning("Redis unavailable — report not stored")
            return
        data = asdict(report)
        data["top_failure_types"] = [
            [t, c] for t, c in data["top_failure_types"]
        ]
        await redis.rpush(REPORT_KEY, json.dumps(data))
        logger.debug("Stored report %s in Redis", report.report_id)
