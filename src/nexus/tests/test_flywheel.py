"""Tests for the data flywheel & self-learning subsystem (NX-SPEC-08).

Uses fakeredis for Redis, mocks for LLM client. All async tests run
under pytest-asyncio with asyncio_mode="auto".
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import fakeredis.aioredis
import pytest

from nexus.bus.client import NexusBus
from nexus.bus.event import EventType, NexusEvent
from nexus.flywheel.collector import (
    FailureEvent,
    FailureEventCollector,
    LLMCallEvent,
    RecoveryEvent,
)
from nexus.flywheel.analyzer import (
    AnalysisReport,
    WeeklyAnalysisEngine,
)
from nexus.flywheel.learning import (
    LearningInsight,
    LearningLoop,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def bus(redis_client):
    bus = NexusBus(
        redis_url="redis://localhost:6379/0",
        namespace="nexus",
    )
    bus._redis = redis_client
    yield bus
    await bus.stop_consumer()


@pytest.fixture
def llm_mock():
    """Mock LLM client with a .call() async method."""
    mock = MagicMock()
    mock.call = AsyncMock(
        return_value={
            "content": (
                "- Increase circuit breaker threshold for llm:writer/palmyra-x6\n"
                "- Review timeout settings for admiral bot\n"
                "- Implement failover to backup model for cortex"
            ),
            "model": "writer/palmyra-x6",
        }
    )
    return mock


@pytest.fixture
async def collector(bus, redis_client):
    c = FailureEventCollector(nexus=bus, redis_client=redis_client)
    yield c


@pytest.fixture
async def analyzer(collector, llm_mock, bus):
    return WeeklyAnalysisEngine(
        collector=collector,
        llm_client=llm_mock,
        nexus=bus,
    )


@pytest.fixture
async def learning_loop(bus, llm_mock, redis_client):
    return LearningLoop(
        nexus=bus,
        llm_client=llm_mock,
        redis_client=redis_client,
    )


# ---------------------------------------------------------------------------
# Helper to create failure/recovery/llm_call events
# ---------------------------------------------------------------------------

def make_failure_event(
    bot_id: str = "admiral",
    failure_type: str = "rate_limit",
    dependency: str | None = None,
    outcome: str = "retried",
    timestamp: str | None = None,
) -> NexusEvent:
    return NexusEvent.create(
        event_type=EventType.FAILURE_LOGGED,
        source=bot_id,
        target="broadcast",
        payload={
            "bot_id": bot_id,
            "failure_type": failure_type,
            "dependency": dependency or f"llm:writer/palmyra-x6",
            "error_message": f"Rate limit exceeded for {bot_id}",
            "stack_trace": None,
            "context": {"attempt": 1},
            "outcome": outcome,
        },
        correlation_id=str(uuid4()),
    )


def make_recovery_event(
    bot_id: str = "admiral",
    recovery_action: str = "exponential_backoff",
    success: bool = True,
    detail: str = "Recovered after 2 retries",
) -> NexusEvent:
    return NexusEvent.create(
        event_type=EventType.RECOVERY_EXECUTED,
        source=bot_id,
        target="broadcast",
        payload={
            "bot_id": bot_id,
            "failure_type": "rate_limit",
            "recovery_action": recovery_action,
            "success": success,
            "details": {
                "outcome": "recovered" if success else "failed",
                "detail": detail,
                "retried": True,
            },
        },
        correlation_id=str(uuid4()),
    )


def make_llm_call_event(
    bot_id: str = "cortex",
    model: str = "writer/palmyra-x6",
    success: bool = True,
    latency_ms: int = 150,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> NexusEvent:
    return NexusEvent.create(
        event_type=EventType.FLYWHEEL_LLM_CALL,
        source="llm_client",
        target="broadcast",
        payload={
            "bot_id": bot_id,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "success": success,
            "error": None if success else "timeout",
        },
        correlation_id=str(uuid4()),
    )


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------

class TestCollector:
    """Tests for FailureEventCollector."""

    async def test_collector_stores_failure_events(self, collector, redis_client) -> None:
        event = make_failure_event(bot_id="admiral")
        await collector.handle_failure(event)

        failures = await collector.get_failures()
        assert len(failures) == 1
        assert failures[0].bot_id == "admiral"
        assert failures[0].failure_type == "rate_limit"
        assert failures[0].error_message == "Rate limit exceeded for admiral"

    async def test_collector_stores_recovery_events(self, collector, redis_client) -> None:
        event = make_recovery_event(bot_id="cortex", success=True)
        await collector.handle_recovery(event)

        recoveries = await collector.get_recoveries()
        assert len(recoveries) == 1
        assert recoveries[0].bot_id == "cortex"
        assert recoveries[0].strategy == "exponential_backoff"
        assert recoveries[0].result == "recovered"

    async def test_collector_stores_llm_calls(self, collector, redis_client) -> None:
        event = make_llm_call_event(bot_id="cortex", model="writer/palmyra-x6")
        await collector.handle_llm_call(event)

        calls = await collector.get_llm_calls()
        assert len(calls) == 1
        assert calls[0].bot_id == "cortex"
        assert calls[0].model == "writer/palmyra-x6"
        assert calls[0].success is True
        assert calls[0].token_count == 150

    async def test_collector_filters_by_bot(self, collector, redis_client) -> None:
        await collector.handle_failure(make_failure_event(bot_id="admiral"))
        await collector.handle_failure(make_failure_event(bot_id="cortex"))
        await collector.handle_failure(make_failure_event(bot_id="admiral"))

        admiral_failures = await collector.get_failures(bot_id="admiral")
        assert len(admiral_failures) == 2
        assert all(f.bot_id == "admiral" for f in admiral_failures)

        cortex_failures = await collector.get_failures(bot_id="cortex")
        assert len(cortex_failures) == 1
        assert cortex_failures[0].bot_id == "cortex"

    async def test_collector_filters_by_time(self, collector, redis_client) -> None:
        # Old event (timestamp in the past)
        old_event = make_failure_event(bot_id="admiral")
        old_event.timestamp = "2026-01-01T00:00:00+00:00"
        await collector.handle_failure(old_event)

        # Recent event (default timestamp = now)
        recent_event = make_failure_event(bot_id="admiral")
        await collector.handle_failure(recent_event)

        # Filter: only events since 2026-08-01
        recent = await collector.get_failures(since="2026-08-01T00:00:00+00:00")
        assert len(recent) == 1
        assert recent[0].timestamp > "2026-08-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Analyzer tests
# ---------------------------------------------------------------------------

class TestAnalyzer:
    """Tests for WeeklyAnalysisEngine."""

    async def test_analyzer_computes_statistics(self, analyzer, collector) -> None:
        # Seed some events
        await collector.handle_failure(make_failure_event(bot_id="admiral", failure_type="rate_limit"))
        await collector.handle_failure(make_failure_event(bot_id="cortex", failure_type="timeout"))
        await collector.handle_failure(make_failure_event(bot_id="admiral", failure_type="rate_limit"))

        await collector.handle_recovery(make_recovery_event(bot_id="admiral", success=True))
        await collector.handle_recovery(make_recovery_event(bot_id="cortex", success=False))

        failures = await collector.get_failures()
        recoveries = await collector.get_recoveries()

        stats = await analyzer._compute_statistics(failures, recoveries)

        assert stats["total_failures"] == 3
        assert stats["total_recoveries"] == 2
        assert stats["failure_rate_by_bot"]["admiral"] == pytest.approx(2 / 3)
        assert stats["failure_rate_by_bot"]["cortex"] == pytest.approx(1 / 3)
        assert stats["recovery_success_rate"] == pytest.approx(0.5)
        assert len(stats["top_failure_types"]) == 2
        assert stats["top_failure_types"][0] == ("rate_limit", 2)

    async def test_analyzer_generates_report(self, analyzer, collector) -> None:
        # Seed events
        await collector.handle_failure(make_failure_event(bot_id="admiral"))
        await collector.handle_recovery(make_recovery_event(bot_id="admiral", success=True))

        report = await analyzer.run_weekly_analysis()

        assert isinstance(report, AnalysisReport)
        assert report.report_id  # non-empty
        assert report.total_failures == 1
        assert report.total_recoveries == 1
        assert "admiral" in report.failure_rate_by_bot
        assert report.recovery_success_rate == pytest.approx(1.0)
        assert len(report.top_failure_types) > 0
        assert len(report.recommendations) > 0
        assert report.generated_at  # non-empty

    async def test_analyzer_publishes_report(self, analyzer, collector, bus, redis_client) -> None:
        # Seed an event
        await collector.handle_failure(make_failure_event(bot_id="admiral"))

        report = await analyzer.run_weekly_analysis()

        # Verify the report was published to the nexus:flywheel stream
        entries = await redis_client.xrange("nexus:flywheel")
        assert len(entries) >= 1

        # Find the report event
        found = False
        for _msg_id, fields in entries:
            if fields.get("event_type") == EventType.FLYWHEEL_TEST_RESULTS:
                payload = json.loads(fields["payload"])
                if payload.get("report_id") == report.report_id:
                    found = True
                    break
        assert found, "Report was not published to Nexus Bus"


# ---------------------------------------------------------------------------
# Learning loop tests
# ---------------------------------------------------------------------------

class TestLearningLoop:
    """Tests for LearningLoop."""

    async def test_learning_loop_extracts_insights(self, learning_loop, llm_mock) -> None:
        # Configure LLM mock to return JSON insights
        llm_mock.call.return_value = {
            "content": json.dumps([
                {
                    "bot_id": "admiral",
                    "insight_type": "failure_pattern",
                    "description": "Admiral has high rate_limit failures on LLM calls",
                    "confidence": 0.85,
                    "recommended_action": "Increase circuit breaker threshold for llm:writer/palmyra-x6",
                },
                {
                    "bot_id": "cortex",
                    "insight_type": "recovery_strategy",
                    "description": "Cortex recovery success rate is low",
                    "confidence": 0.72,
                    "recommended_action": "Review timeout settings for cortex",
                },
            ]),
            "model": "writer/palmyra-x6",
        }

        report = AnalysisReport(
            report_id=str(uuid4()),
            period_start="2026-08-13T00:00:00+00:00",
            period_end="2026-08-20T00:00:00+00:00",
            total_failures=10,
            total_recoveries=8,
            failure_rate_by_bot={"admiral": 0.5, "cortex": 0.3},
            failure_rate_by_dependency={"llm:writer/palmyra-x6": 0.6},
            recovery_success_rate=0.8,
            top_failure_types=[("rate_limit", 5), ("timeout", 3)],
            recommendations=["Increase circuit breaker threshold"],
            generated_at="2026-08-20T00:00:00+00:00",
        )

        insights = await learning_loop.process_report(report)

        assert len(insights) == 2
        assert all(isinstance(i, LearningInsight) for i in insights)
        assert insights[0].bot_id == "admiral"
        assert insights[0].insight_type == "failure_pattern"
        assert insights[0].confidence == pytest.approx(0.85)
        assert insights[0].recommended_action is not None

    async def test_learning_loop_applies_insight(self, learning_loop) -> None:
        insight = LearningInsight(
            insight_id=str(uuid4()),
            bot_id="admiral",
            insight_type="failure_pattern",
            description="High rate_limit failures",
            confidence=0.9,
            recommended_action="Adjust circuit breaker threshold for llm:writer/palmyra-x6",
            timestamp="2026-08-20T00:00:00+00:00",
        )

        result = await learning_loop.apply_insight(insight)
        assert result is True

    async def test_learning_loop_stores_insights(self, learning_loop, llm_mock, redis_client) -> None:
        llm_mock.call.return_value = {
            "content": json.dumps([
                {
                    "bot_id": "admiral",
                    "insight_type": "failure_pattern",
                    "description": "High failure rate",
                    "confidence": 0.8,
                    "recommended_action": "Review dependencies",
                },
            ]),
            "model": "writer/palmyra-x6",
        }

        report = AnalysisReport(
            report_id=str(uuid4()),
            period_start="2026-08-13T00:00:00+00:00",
            period_end="2026-08-20T00:00:00+00:00",
            total_failures=5,
            total_recoveries=3,
            failure_rate_by_bot={"admiral": 0.6},
            failure_rate_by_dependency={"llm:writer/palmyra-x6": 0.6},
            recovery_success_rate=0.6,
            top_failure_types=[("rate_limit", 3)],
            recommendations=["Review dependencies"],
            generated_at="2026-08-20T00:00:00+00:00",
        )

        insights = await learning_loop.process_report(report)
        assert len(insights) == 1

        # Retrieve stored insights
        stored = await learning_loop.get_insights()
        assert len(stored) == 1
        assert stored[0].bot_id == "admiral"
        assert stored[0].description == "High failure rate"
