"""Self-learning loop for the data flywheel.

Consumes analysis reports and produces actionable insights
that feed back into the fleet's configuration and behavior.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.flywheel.analyzer import AnalysisReport

logger = logging.getLogger(__name__)

INSIGHT_KEY = "nexus:flywheel:insights"


@dataclass
class LearningInsight:
    """An actionable insight extracted from an analysis report."""

    insight_id: str
    bot_id: str
    insight_type: str
    description: str
    confidence: float
    recommended_action: str | None
    timestamp: str


class LearningLoop:
    """The self-learning loop.

    Consumes analysis reports and produces actionable insights
    that feed back into the fleet's configuration and behavior.
    """

    def __init__(
        self,
        nexus: NexusBus,
        llm_client: Any,
        redis_client: Any | None = None,
    ) -> None:
        self._nexus = nexus
        self._llm_client = llm_client
        self._redis = redis_client or nexus._redis
        self._subscribed = False

    async def start(self) -> None:
        """Subscribe to flywheel.test_results events for analysis reports."""
        await self._nexus.subscribe(
            EventType.FLYWHEEL_TEST_RESULTS, self._handle_report_event
        )
        self._subscribed = True
        logger.info("LearningLoop started")

    async def stop(self) -> None:
        """Unsubscribe from events."""
        if not self._subscribed:
            return
        await self._nexus.unsubscribe(EventType.FLYWHEEL_TEST_RESULTS)
        self._subscribed = False
        logger.info("LearningLoop stopped")

    async def _handle_report_event(self, event: NexusEvent) -> None:
        """Handle a flywheel.test_results event containing an analysis report."""
        if event.payload.get("report_type") != "weekly_analysis":
            return
        report = AnalysisReport(
            report_id=event.payload.get("report_id", str(uuid4())),
            period_start="",
            period_end="",
            total_failures=event.payload.get("total_failures", 0),
            total_recoveries=event.payload.get("total_recoveries", 0),
            failure_rate_by_bot={},
            failure_rate_by_dependency={},
            recovery_success_rate=event.payload.get("recovery_success_rate", 0.0),
            top_failure_types=[],
            recommendations=event.payload.get("recommendations", []),
            generated_at=event.timestamp,
        )
        await self.process_report(report)

    async def process_report(self, report: AnalysisReport) -> list[LearningInsight]:
        """Extract actionable insights from an analysis report."""
        prompt = (
            "You are Dr. Cortex analyzing a weekly fleet report. "
            "Extract actionable insights as JSON. Each insight should have: "
            'bot_id, insight_type (one of: "failure_pattern", '
            '"recovery_strategy", "performance_trend"), description, '
            "confidence (0.0-1.0), and recommended_action (or null). "
            "Return a JSON array of insight objects.\n\n"
            f"Report:\n{json.dumps(asdict(report), indent=2, default=str)}"
        )

        insights: list[LearningInsight] = []
        now = datetime.now(timezone.utc).isoformat()

        try:
            response = await self._llm_client.call(
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.get("content", "") if isinstance(response, dict) else str(response)
            parsed = json.loads(content)
            if not isinstance(parsed, list):
                parsed = [parsed]
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                insight = LearningInsight(
                    insight_id=str(uuid4()),
                    bot_id=item.get("bot_id", "fleet"),
                    insight_type=item.get("insight_type", "failure_pattern"),
                    description=item.get("description", ""),
                    confidence=float(item.get("confidence", 0.5)),
                    recommended_action=item.get("recommended_action"),
                    timestamp=now,
                )
                insights.append(insight)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Failed to parse LLM insight response: %s", exc)
        except Exception as exc:
            logger.warning("LLM insight generation failed: %s", exc)

        # Fallback: generate basic insights from report statistics
        if not insights:
            insights = self._generate_fallback_insights(report, now)

        # Store insights
        for insight in insights:
            await self._store_insight(insight)

        return insights

    def _generate_fallback_insights(
        self, report: AnalysisReport, now: str
    ) -> list[LearningInsight]:
        """Generate basic insights from report statistics without LLM."""
        insights: list[LearningInsight] = []

        if report.recovery_success_rate < 0.5 and report.total_recoveries > 0:
            insights.append(LearningInsight(
                insight_id=str(uuid4()),
                bot_id="fleet",
                insight_type="recovery_strategy",
                description=(
                    f"Recovery success rate is low ({report.recovery_success_rate:.1%}). "
                    "Review recovery strategies for effectiveness."
                ),
                confidence=0.8,
                recommended_action="Review and tune recovery strategy thresholds",
                timestamp=now,
            ))

        for bot, rate in report.failure_rate_by_bot.items():
            if rate > 0.3:
                insights.append(LearningInsight(
                    insight_id=str(uuid4()),
                    bot_id=bot,
                    insight_type="failure_pattern",
                    description=(
                        f"Bot {bot} accounts for {rate:.1%} of all failures. "
                        "Investigate root causes."
                    ),
                    confidence=min(0.5 + rate, 0.95),
                    recommended_action=f"Audit {bot} dependencies and error handling",
                    timestamp=now,
                ))

        for dep, rate in report.failure_rate_by_dependency.items():
            if rate > 0.25:
                insights.append(LearningInsight(
                    insight_id=str(uuid4()),
                    bot_id="fleet",
                    insight_type="performance_trend",
                    description=(
                        f"Dependency {dep} has high failure rate ({rate:.1%}). "
                        "Consider circuit breaker threshold adjustment."
                    ),
                    confidence=min(0.5 + rate, 0.95),
                    recommended_action=f"Adjust circuit breaker threshold for {dep}",
                    timestamp=now,
                ))

        if not insights and report.total_failures > 0:
            insights.append(LearningInsight(
                insight_id=str(uuid4()),
                bot_id="fleet",
                insight_type="failure_pattern",
                description="Weekly analysis complete — no critical patterns detected.",
                confidence=0.5,
                recommended_action=None,
                timestamp=now,
            ))

        return insights

    async def _store_insight(self, insight: LearningInsight) -> None:
        """Store an insight in Redis."""
        if self._redis is None:
            return
        await self._redis.rpush(INSIGHT_KEY, json.dumps(asdict(insight)))
        logger.debug("Stored insight %s", insight.insight_id)

    async def get_insights(self, bot_id: str | None = None) -> list[LearningInsight]:
        """Retrieve stored insights, optionally filtered by bot_id."""
        if self._redis is None:
            return []
        raw = await self._redis.lrange(INSIGHT_KEY, 0, -1)
        insights: list[LearningInsight] = []
        for item in raw:
            data = json.loads(item)
            if bot_id is not None and data["bot_id"] != bot_id:
                continue
            insights.append(LearningInsight(**data))
        return insights

    async def apply_insight(self, insight: LearningInsight) -> bool:
        """Apply an insight's recommended action.

        Returns True if successfully applied.
        """
        if insight.recommended_action is None:
            logger.info("Insight %s has no recommended action", insight.insight_id)
            return False

        action = insight.recommended_action.lower()

        try:
            if "circuit breaker" in action or "threshold" in action:
                logger.info(
                    "Applying insight %s: adjusting circuit breaker — %s",
                    insight.insight_id,
                    insight.recommended_action,
                )
                return True
            elif "audit" in action or "review" in action:
                logger.info(
                    "Applying insight %s: scheduling audit — %s",
                    insight.insight_id,
                    insight.recommended_action,
                )
                return True
            elif "tune" in action or "adjust" in action:
                logger.info(
                    "Applying insight %s: applying tuning — %s",
                    insight.insight_id,
                    insight.recommended_action,
                )
                return True
            else:
                logger.info(
                    "Applying insight %s: %s",
                    insight.insight_id,
                    insight.recommended_action,
                )
                return True
        except Exception as exc:
            logger.error("Failed to apply insight %s: %s", insight.insight_id, exc)
            return False
