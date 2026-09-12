"""Tests for BotPosterior and PosteriorStore — updates, weakness scores, save/load."""

from __future__ import annotations

import json
from typing import Any

import fakeredis.aioredis
import pytest

from nexus.testing.posterior import BotPosterior, CapabilityScore, PosteriorStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def redis_client() -> Any:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def store(redis_client: Any) -> PosteriorStore:
    return PosteriorStore(redis_client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCapabilityScore:
    """Tests for CapabilityScore dataclass."""

    def test_average_score_no_tests(self) -> None:
        cap = CapabilityScore(category="domain_knowledge")
        assert cap.average_score == 0.0

    def test_average_score_with_tests(self) -> None:
        cap = CapabilityScore(category="domain_knowledge", total_tests=4, total_score=32.0)
        assert cap.average_score == 8.0

    def test_weakness_score_no_tests(self) -> None:
        cap = CapabilityScore(category="domain_knowledge")
        assert cap.weakness_score == 0.0

    def test_weakness_score_high_failures(self) -> None:
        cap = CapabilityScore(
            category="domain_knowledge",
            total_tests=10,
            total_score=40.0,
            failures=8,
        )
        # failure_rate = 0.8, avg = 4.0, avg_inverse = 0.6
        # weakness = 0.8 * 0.5 + 0.6 * 0.5 = 0.7
        assert cap.weakness_score == 0.7

    def test_weakness_score_low_failures(self) -> None:
        cap = CapabilityScore(
            category="domain_knowledge",
            total_tests=10,
            total_score=90.0,
            failures=1,
        )
        # failure_rate = 0.1, avg = 9.0, avg_inverse = 0.1
        # weakness = 0.1 * 0.5 + 0.1 * 0.5 = 0.1
        assert cap.weakness_score == 0.1

    def test_to_dict_roundtrip(self) -> None:
        cap = CapabilityScore(
            category="safety",
            total_tests=5,
            total_score=35.0,
            failures=1,
            last_tested="2026-08-21T05:00:00Z",
            recent_scores=[7.0, 8.0, 9.0],
        )
        d = cap.to_dict()
        cap2 = CapabilityScore.from_dict(d)
        assert cap2.category == cap.category
        assert cap2.total_tests == cap.total_tests
        assert cap2.recent_scores == cap.recent_scores


class TestBotPosterior:
    """Tests for BotPosterior dataclass."""

    def test_update_creates_new_category(self) -> None:
        posterior = BotPosterior(bot_id="cortex")
        posterior.update("domain_knowledge", 8.0, True)
        assert "domain_knowledge" in posterior.capabilities
        cap = posterior.capabilities["domain_knowledge"]
        assert cap.total_tests == 1
        assert cap.total_score == 8.0
        assert cap.failures == 0
        assert cap.recent_scores == [8.0]

    def test_update_accumulates(self) -> None:
        posterior = BotPosterior(bot_id="cortex")
        posterior.update("domain_knowledge", 8.0, True)
        posterior.update("domain_knowledge", 6.0, False)
        cap = posterior.capabilities["domain_knowledge"]
        assert cap.total_tests == 2
        assert cap.total_score == 14.0
        assert cap.failures == 1
        assert cap.recent_scores == [8.0, 6.0]

    def test_update_trims_recent_scores(self) -> None:
        posterior = BotPosterior(bot_id="cortex")
        for i in range(25):
            posterior.update("domain_knowledge", float(i), True)
        cap = posterior.capabilities["domain_knowledge"]
        assert len(cap.recent_scores) == 20

    def test_get_weakest_categories(self) -> None:
        posterior = BotPosterior(bot_id="cortex")
        # Strong category
        posterior.update("domain_knowledge", 9.0, True)
        posterior.update("domain_knowledge", 9.0, True)
        # Weak category
        posterior.update("safety", 3.0, False)
        posterior.update("safety", 2.0, False)
        # Medium category
        posterior.update("tool_use", 6.0, True)
        posterior.update("tool_use", 5.0, False)

        weakest = posterior.get_weakest_categories(2)
        assert "safety" in weakest
        assert weakest[0] == "safety"

    def test_get_weakest_categories_empty(self) -> None:
        posterior = BotPosterior(bot_id="cortex")
        assert posterior.get_weakest_categories(3) == []

    def test_to_dict_roundtrip(self) -> None:
        posterior = BotPosterior(bot_id="cortex")
        posterior.update("domain_knowledge", 8.0, True)
        posterior.update("safety", 5.0, False)

        d = posterior.to_dict()
        posterior2 = BotPosterior.from_dict(d)
        assert posterior2.bot_id == "cortex"
        assert "domain_knowledge" in posterior2.capabilities
        assert "safety" in posterior2.capabilities


class TestPosteriorStore:
    """Tests for PosteriorStore save/load."""

    async def test_save_and_load(self, store: PosteriorStore) -> None:
        posterior = BotPosterior(bot_id="cortex")
        posterior.update("domain_knowledge", 8.0, True)
        posterior.update("safety", 5.0, False)

        await store.save(posterior)

        loaded = await store.load("cortex")
        assert loaded.bot_id == "cortex"
        assert "domain_knowledge" in loaded.capabilities
        assert "safety" in loaded.capabilities
        assert loaded.capabilities["domain_knowledge"].total_tests == 1
        assert loaded.capabilities["safety"].failures == 1

    async def test_load_missing_returns_empty(self, store: PosteriorStore) -> None:
        loaded = await store.load("nonexistent")
        assert loaded.bot_id == "nonexistent"
        assert len(loaded.capabilities) == 0

    async def test_save_overwrites(self, store: PosteriorStore) -> None:
        posterior = BotPosterior(bot_id="cortex")
        posterior.update("domain_knowledge", 8.0, True)
        await store.save(posterior)

        # Save again with different data
        posterior2 = BotPosterior(bot_id="cortex")
        posterior2.update("safety", 6.0, True)
        await store.save(posterior2)

        loaded = await store.load("cortex")
        assert "safety" in loaded.capabilities
        assert "domain_knowledge" not in loaded.capabilities

    async def test_key_prefix(self, store: PosteriorStore, redis_client: Any) -> None:
        posterior = BotPosterior(bot_id="cortex")
        posterior.update("domain_knowledge", 8.0, True)
        await store.save(posterior)

        # Check the key exists in Redis
        keys = await redis_client.keys("nexus:sentinel:posterior:*")
        assert len(keys) == 1
        assert "nexus:sentinel:posterior:cortex" in keys[0]
