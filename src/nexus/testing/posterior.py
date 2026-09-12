"""Adaptive difficulty posterior tracking.

Tracks per-bot, per-category performance over time to enable adaptive
test difficulty. Uses Redis for persistence.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CapabilityScore:
    """Tracks performance for a single capability category.

    Attributes:
        category: The test category name.
        total_tests: Total number of tests run.
        total_score: Sum of all scores.
        failures: Number of failed tests.
        last_tested: ISO-8601 timestamp of last test.
        recent_scores: List of recent scores (most recent last).
    """

    category: str
    total_tests: int = 0
    total_score: float = 0.0
    failures: int = 0
    last_tested: str = ""
    recent_scores: list[float] = field(default_factory=list)

    @property
    def average_score(self) -> float:
        """Return the average score across all tests."""
        if self.total_tests == 0:
            return 0.0
        return round(self.total_score / self.total_tests, 2)

    @property
    def weakness_score(self) -> float:
        """Return a weakness score (higher = weaker).

        Combines failure rate and inverse of average score.
        """
        if self.total_tests == 0:
            return 0.0
        failure_rate = self.failures / self.total_tests
        avg_inverse = (10.0 - self.average_score) / 10.0
        return round(failure_rate * 0.5 + avg_inverse * 0.5, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "total_tests": self.total_tests,
            "total_score": self.total_score,
            "failures": self.failures,
            "last_tested": self.last_tested,
            "recent_scores": self.recent_scores,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityScore:
        return cls(
            category=data["category"],
            total_tests=data.get("total_tests", 0),
            total_score=data.get("total_score", 0.0),
            failures=data.get("failures", 0),
            last_tested=data.get("last_tested", ""),
            recent_scores=data.get("recent_scores", []),
        )


@dataclass
class BotPosterior:
    """Posterior tracking for a single bot.

    Attributes:
        bot_id: The bot ID.
        capabilities: Mapping of category -> CapabilityScore.
        last_updated: ISO-8601 timestamp.
    """

    bot_id: str
    capabilities: dict[str, CapabilityScore] = field(default_factory=dict)
    last_updated: str = ""

    def get_weakest_categories(self, n: int = 3) -> list[str]:
        """Return the n weakest categories by weakness score.

        Args:
            n: Number of categories to return.

        Returns:
            List of category names, weakest first.
        """
        scored = [
            (cat, cap.weakness_score)
            for cat, cap in self.capabilities.items()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [cat for cat, _ in scored[:n]]

    def update(self, category: str, score: float, passed: bool) -> None:
        """Update the posterior with a new test result.

        Args:
            category: The test category.
            score: The composite score (1-10).
            passed: Whether the test passed.
        """
        if category not in self.capabilities:
            self.capabilities[category] = CapabilityScore(category=category)

        cap = self.capabilities[category]
        cap.total_tests += 1
        cap.total_score += score
        if not passed:
            cap.failures += 1
        cap.last_tested = datetime.now(timezone.utc).isoformat()
        cap.recent_scores.append(score)
        # Keep only the last 20 scores
        if len(cap.recent_scores) > 20:
            cap.recent_scores = cap.recent_scores[-20:]

        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "capabilities": {
                cat: cap.to_dict() for cat, cap in self.capabilities.items()
            },
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BotPosterior:
        capabilities = {
            cat: CapabilityScore.from_dict(cap_data)
            for cat, cap_data in data.get("capabilities", {}).items()
        }
        return cls(
            bot_id=data["bot_id"],
            capabilities=capabilities,
            last_updated=data.get("last_updated", ""),
        )


class PosteriorStore:
    """Redis-backed store for bot posteriors.

    Attributes:
        KEY_PREFIX: Redis key prefix for posterior storage.
    """

    KEY_PREFIX: str = "nexus:sentinel:posterior"

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def load(self, bot_id: str) -> BotPosterior:
        """Load a bot posterior from Redis.

        Args:
            bot_id: The bot ID.

        Returns:
            A BotPosterior (empty if not found).
        """
        key = f"{self.KEY_PREFIX}:{bot_id}"
        try:
            data = await self._redis.get(key)
            if data is None:
                return BotPosterior(bot_id=bot_id)
            if isinstance(data, str):
                data_dict = json.loads(data)
            elif isinstance(data, bytes):
                data_dict = json.loads(data.decode("utf-8"))
            else:
                data_dict = data
            return BotPosterior.from_dict(data_dict)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to load posterior for %s: %s", bot_id, exc)
            return BotPosterior(bot_id=bot_id)

    async def save(self, posterior: BotPosterior) -> None:
        """Save a bot posterior to Redis.

        Args:
            posterior: The BotPosterior to save.
        """
        key = f"{self.KEY_PREFIX}:{posterior.bot_id}"
        data = json.dumps(self._serialize(posterior))
        await self._redis.set(key, data)
        logger.debug("Saved posterior for %s", posterior.bot_id)

    def _serialize(self, posterior: BotPosterior) -> dict[str, Any]:
        """Serialize a BotPosterior to a dict.

        Args:
            posterior: The BotPosterior to serialize.

        Returns:
            A dict representation.
        """
        return posterior.to_dict()

    def _deserialize(self, data: dict[str, Any]) -> BotPosterior:
        """Deserialize a dict to a BotPosterior.

        Args:
            data: The dict to deserialize.

        Returns:
            A BotPosterior instance.
        """
        return BotPosterior.from_dict(data)
