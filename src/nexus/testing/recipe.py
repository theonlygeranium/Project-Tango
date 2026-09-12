"""Test recipe data model and registry.

A TestRecipe defines the full set of test cases for a single bot, organized
by category and validated for coverage minimums.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """A single test case in a test recipe.

    Attributes:
        test_id: Unique identifier (e.g. "cortex-001").
        category: Test category (domain_knowledge, tool_use, routing, etc.).
        question: The primary question to ask the bot.
        follow_ups: Optional list of follow-up questions.
        expected_behavior: Description of what the bot should do.
        acceptance_keywords: Keywords that should appear in a good response.
        rejection_keywords: Keywords that should NOT appear.
        rubric_id: Which rubric to use for scoring.
        difficulty: "easy", "medium", or "hard".
        source: "manual" or "generated".
        created_at: ISO-8601 timestamp.
        tests_feature: Name of the feature being tested, if any.
        min_score: Minimum composite score to pass (1-10).
    """

    test_id: str
    category: str
    question: str
    follow_ups: list[str] = field(default_factory=list)
    expected_behavior: str = ""
    acceptance_keywords: list[str] = field(default_factory=list)
    rejection_keywords: list[str] = field(default_factory=list)
    rubric_id: str = "domain_knowledge_rubric"
    difficulty: str = "medium"
    source: str = "manual"
    created_at: str = ""
    tests_feature: str | None = None
    min_score: float = 7.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        """Create a TestCase from a YAML-loaded dict."""
        return cls(
            test_id=data["test_id"],
            category=data["category"],
            question=data["question"],
            follow_ups=data.get("follow_ups", []),
            expected_behavior=data.get("expected_behavior", ""),
            acceptance_keywords=data.get("acceptance_keywords", []),
            rejection_keywords=data.get("rejection_keywords", []),
            rubric_id=data.get("rubric_id", "domain_knowledge_rubric"),
            difficulty=data.get("difficulty", "medium"),
            source=data.get("source", "manual"),
            created_at=data.get("created_at", ""),
            tests_feature=data.get("tests_feature"),
            min_score=float(data.get("min_score", 7.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for YAML dumping."""
        return {
            "test_id": self.test_id,
            "category": self.category,
            "question": self.question,
            "follow_ups": self.follow_ups,
            "expected_behavior": self.expected_behavior,
            "acceptance_keywords": self.acceptance_keywords,
            "rejection_keywords": self.rejection_keywords,
            "rubric_id": self.rubric_id,
            "difficulty": self.difficulty,
            "source": self.source,
            "created_at": self.created_at,
            "tests_feature": self.tests_feature,
            "min_score": self.min_score,
        }


@dataclass
class TestRecipe:
    """A complete test recipe for a single bot.

    Attributes:
        bot_id: The bot this recipe tests.
        version: Semantic version string.
        last_updated: ISO-8601 timestamp.
        total_cases: Number of test cases.
        cases: List of TestCase objects.
        coverage: Mapping of category -> list of test_ids.
    """

    bot_id: str
    version: str = "1.0.0"
    last_updated: str = ""
    total_cases: int = 0
    cases: list[TestCase] = field(default_factory=list)
    coverage: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestRecipe:
        """Create a TestRecipe from a YAML-loaded dict."""
        cases = [TestCase.from_dict(c) for c in data.get("cases", [])]
        return cls(
            bot_id=data["bot_id"],
            version=data.get("version", "1.0.0"),
            last_updated=data.get("last_updated", ""),
            total_cases=data.get("total_cases", len(cases)),
            cases=cases,
            coverage=data.get("coverage", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for YAML dumping."""
        return {
            "bot_id": self.bot_id,
            "version": self.version,
            "last_updated": self.last_updated,
            "total_cases": len(self.cases),
            "coverage": self.coverage,
            "cases": [c.to_dict() for c in self.cases],
        }


class RecipeRegistry:
    """Loads, validates, and saves test recipes from YAML files."""

    RECIPES_DIR: Path = Path("tests/recipes")

    def __init__(self, recipes_dir: Path | None = None) -> None:
        if recipes_dir is not None:
            self.RECIPES_DIR = recipes_dir
        self._cache: dict[str, TestRecipe] | None = None

    def load_all(self) -> dict[str, TestRecipe]:
        """Load all recipe YAML files from the recipes directory.

        Returns:
            Mapping of bot_id -> TestRecipe.
        """
        recipes: dict[str, TestRecipe] = {}
        if not self.RECIPES_DIR.exists():
            logger.warning("Recipes directory %s does not exist", self.RECIPES_DIR)
            return recipes

        for path in sorted(self.RECIPES_DIR.glob("*.yaml")):
            try:
                recipe = self._load_one(path)
                self._validate(recipe)
                recipes[recipe.bot_id] = recipe
            except (ValueError, KeyError, yaml.YAMLError) as exc:
                logger.error("Failed to load recipe from %s: %s", path, exc)

        self._cache = recipes
        logger.info("Loaded %d test recipes from %s", len(recipes), self.RECIPES_DIR)
        return recipes

    def _load_one(self, path: Path) -> TestRecipe:
        """Load a single recipe YAML file.

        Args:
            path: Path to the YAML file.

        Returns:
            A TestRecipe instance.

        Raises:
            yaml.YAMLError: If the file is not valid YAML.
            KeyError: If required fields are missing.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            raise ValueError(f"Empty recipe file: {path}")
        return TestRecipe.from_dict(data)

    def _validate(self, recipe: TestRecipe) -> None:
        """Validate a recipe meets minimum quality standards.

        Args:
            recipe: The recipe to validate.

        Raises:
            ValueError: If validation fails.
        """
        if len(recipe.cases) < 20:
            raise ValueError(
                f"Recipe for {recipe.bot_id} has only {len(recipe.cases)} cases; "
                f"minimum 20 required"
            )

        test_ids: list[str] = [c.test_id for c in recipe.cases]
        seen: set[str] = set()
        duplicates: list[str] = []
        for tid in test_ids:
            if tid in seen:
                duplicates.append(tid)
            seen.add(tid)
        if duplicates:
            raise ValueError(
                f"Recipe for {recipe.bot_id} has duplicate test_ids: {duplicates}"
            )

        for case in recipe.cases:
            if not (1 <= case.min_score <= 10):
                raise ValueError(
                    f"Test case {case.test_id} has min_score {case.min_score}; "
                    f"must be between 1 and 10"
                )

        recipe.total_cases = len(recipe.cases)
        logger.debug("Recipe for %s validated: %d cases", recipe.bot_id, len(recipe.cases))

    def get(self, bot_id: str) -> TestRecipe:
        """Get a recipe for a specific bot.

        Args:
            bot_id: The bot to get the recipe for.

        Returns:
            The TestRecipe for the bot.

        Raises:
            KeyError: If no recipe exists for the bot.
        """
        if self._cache is None:
            self.load_all()
        assert self._cache is not None
        if bot_id not in self._cache:
            raise KeyError(f"No recipe found for bot: {bot_id}")
        return self._cache[bot_id]

    def all_bot_ids(self) -> list[str]:
        """Return all bot IDs that have recipes.

        Returns:
            List of bot_id strings.
        """
        if self._cache is None:
            self.load_all()
        assert self._cache is not None
        return list(self._cache.keys())

    def save(self, bot_id: str, recipe: TestRecipe) -> Path:
        """Save a recipe to a YAML file.

        Args:
            bot_id: The bot ID (used for filename).
            recipe: The recipe to save.

        Returns:
            The path the recipe was saved to.
        """
        self.RECIPES_DIR.mkdir(parents=True, exist_ok=True)
        path = self.RECIPES_DIR / f"{bot_id}.yaml"
        recipe.last_updated = datetime.now(timezone.utc).isoformat()
        recipe.total_cases = len(recipe.cases)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(recipe.to_dict(), f, default_flow_style=False, sort_keys=False)
        logger.info("Saved recipe for %s to %s", bot_id, path)

        if self._cache is not None:
            self._cache[bot_id] = recipe
        return path
