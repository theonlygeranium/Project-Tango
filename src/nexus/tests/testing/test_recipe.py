"""Tests for RecipeRegistry — load, validate, save, and enforce minimums."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from nexus.testing.recipe import RecipeRegistry, TestCase, TestRecipe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Create a temporary recipes directory with valid recipe files."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()

    # Create a valid recipe with 20 cases
    cases = []
    for i in range(1, 21):
        cases.append({
            "test_id": f"testbot-{i:03d}",
            "category": "domain_knowledge",
            "question": f"Question {i}?",
            "follow_ups": ["Follow up?"],
            "expected_behavior": "Expected behavior",
            "acceptance_keywords": ["keyword"],
            "rejection_keywords": ["badword"],
            "rubric_id": "domain_knowledge_rubric",
            "difficulty": "easy",
            "source": "manual",
            "created_at": "2026-08-21T05:00:00Z",
            "tests_feature": None,
            "min_score": 7.0,
        })

    recipe_data = {
        "bot_id": "testbot",
        "version": "1.0.0",
        "last_updated": "2026-08-21T05:00:00Z",
        "total_cases": 20,
        "coverage": {"domain_knowledge": [c["test_id"] for c in cases]},
        "cases": cases,
    }
    with open(recipes / "testbot.yaml", "w") as f:
        yaml.dump(recipe_data, f)

    return recipes


@pytest.fixture
def registry(recipes_dir: Path) -> RecipeRegistry:
    return RecipeRegistry(recipes_dir=recipes_dir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecipeRegistryLoad:
    """Tests for RecipeRegistry.load_all()."""

    def test_load_all_returns_dict(self, registry: RecipeRegistry) -> None:
        recipes = registry.load_all()
        assert isinstance(recipes, dict)
        assert "testbot" in recipes

    def test_load_all_returns_correct_recipe(self, registry: RecipeRegistry) -> None:
        recipes = registry.load_all()
        recipe = recipes["testbot"]
        assert recipe.bot_id == "testbot"
        assert recipe.version == "1.0.0"
        assert len(recipe.cases) == 20

    def test_load_all_empty_dir(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty_recipes"
        empty_dir.mkdir()
        reg = RecipeRegistry(recipes_dir=empty_dir)
        recipes = reg.load_all()
        assert recipes == {}

    def test_load_all_nonexistent_dir(self, tmp_path: Path) -> None:
        reg = RecipeRegistry(recipes_dir=tmp_path / "nonexistent")
        recipes = reg.load_all()
        assert recipes == {}


class TestRecipeRegistryValidate:
    """Tests for RecipeRegistry._validate()."""

    def test_validate_rejects_fewer_than_20_cases(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        cases = [
            {"test_id": f"bot-{i:03d}", "category": "domain_knowledge",
             "question": f"Q{i}", "rubric_id": "domain_knowledge_rubric",
             "min_score": 7.0}
            for i in range(1, 16)
        ]
        recipe_data = {
            "bot_id": "bot", "version": "1.0.0", "total_cases": 15,
            "coverage": {}, "cases": cases,
        }
        with open(recipes_dir / "bot.yaml", "w") as f:
            yaml.dump(recipe_data, f)

        reg = RecipeRegistry(recipes_dir=recipes_dir)
        recipes = reg.load_all()
        # The invalid recipe should be skipped
        assert "bot" not in recipes

    def test_validate_rejects_duplicate_test_ids(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        cases = [
            {"test_id": "bot-001", "category": "domain_knowledge",
             "question": "Q", "rubric_id": "domain_knowledge_rubric",
             "min_score": 7.0}
            for _ in range(20)
        ]
        recipe_data = {
            "bot_id": "bot", "version": "1.0.0", "total_cases": 20,
            "coverage": {}, "cases": cases,
        }
        with open(recipes_dir / "bot.yaml", "w") as f:
            yaml.dump(recipe_data, f)

        reg = RecipeRegistry(recipes_dir=recipes_dir)
        recipes = reg.load_all()
        assert "bot" not in recipes

    def test_validate_rejects_invalid_min_score(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        cases = []
        for i in range(20):
            cases.append({
                "test_id": f"bot-{i:03d}", "category": "domain_knowledge",
                "question": "Q", "rubric_id": "domain_knowledge_rubric",
                "min_score": 15.0,
            })
        recipe_data = {
            "bot_id": "bot", "version": "1.0.0", "total_cases": 20,
            "coverage": {}, "cases": cases,
        }
        with open(recipes_dir / "bot.yaml", "w") as f:
            yaml.dump(recipe_data, f)

        reg = RecipeRegistry(recipes_dir=recipes_dir)
        recipes = reg.load_all()
        assert "bot" not in recipes


class TestRecipeRegistryGet:
    """Tests for RecipeRegistry.get()."""

    def test_get_returns_recipe(self, registry: RecipeRegistry) -> None:
        recipe = registry.get("testbot")
        assert recipe.bot_id == "testbot"
        assert len(recipe.cases) == 20

    def test_get_raises_keyerror_for_missing(self, registry: RecipeRegistry) -> None:
        with pytest.raises(KeyError):
            registry.get("nonexistent")


class TestRecipeRegistryAllBotIds:
    """Tests for RecipeRegistry.all_bot_ids()."""

    def test_all_bot_ids(self, registry: RecipeRegistry) -> None:
        ids = registry.all_bot_ids()
        assert "testbot" in ids


class TestRecipeRegistrySave:
    """Tests for RecipeRegistry.save()."""

    def test_save_writes_yaml_file(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        reg = RecipeRegistry(recipes_dir=recipes_dir)

        cases = [
            TestCase(
                test_id=f"newbot-{i:03d}",
                category="domain_knowledge",
                question=f"Question {i}",
                min_score=7.0,
            )
            for i in range(20)
        ]
        recipe = TestRecipe(bot_id="newbot", version="1.0.0", cases=cases)

        path = reg.save("newbot", recipe)
        assert path.exists()
        assert path.name == "newbot.yaml"

        # Verify it can be loaded back
        reg2 = RecipeRegistry(recipes_dir=recipes_dir)
        loaded = reg2.get("newbot")
        assert loaded.bot_id == "newbot"
        assert len(loaded.cases) == 20


class TestTestCase:
    """Tests for TestCase dataclass."""

    def test_from_dict(self) -> None:
        data = {
            "test_id": "test-001",
            "category": "domain_knowledge",
            "question": "What is your role?",
            "follow_ups": ["Tell me more"],
            "expected_behavior": "Clear answer",
            "acceptance_keywords": ["role"],
            "rejection_keywords": ["unknown"],
            "rubric_id": "domain_knowledge_rubric",
            "difficulty": "easy",
            "source": "manual",
            "created_at": "2026-08-21T05:00:00Z",
            "tests_feature": None,
            "min_score": 7.0,
        }
        tc = TestCase.from_dict(data)
        assert tc.test_id == "test-001"
        assert tc.category == "domain_knowledge"
        assert tc.min_score == 7.0

    def test_to_dict_roundtrip(self) -> None:
        tc = TestCase(
            test_id="test-001",
            category="domain_knowledge",
            question="What is your role?",
            min_score=7.0,
        )
        d = tc.to_dict()
        tc2 = TestCase.from_dict(d)
        assert tc2.test_id == tc.test_id
        assert tc2.category == tc.category
