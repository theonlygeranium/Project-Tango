"""Tests for TestEnforcer — check_commit, identify affected bots, block violations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from nexus.testing.enforcement import EnforcementResult, TestEnforcer, enforcer
from nexus.testing.recipe import RecipeRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def recipes_dir(tmp_path: Path) -> Path:
    """Create a temporary recipes directory with a valid recipe."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()

    cases = []
    for i in range(20):
        cases.append({
            "test_id": f"testbot-{i:03d}",
            "category": "domain_knowledge",
            "question": f"Question {i}?",
            "rubric_id": "domain_knowledge_rubric",
            "min_score": 7.0,
        })

    recipe_data = {
        "bot_id": "testbot",
        "version": "1.0.0",
        "total_cases": 20,
        "coverage": {},
        "cases": cases,
    }
    with open(recipes / "testbot.yaml", "w") as f:
        yaml.dump(recipe_data, f)

    return recipes


@pytest.fixture
def test_enforcer(recipes_dir: Path) -> TestEnforcer:
    registry = RecipeRegistry(recipes_dir=recipes_dir)
    return TestEnforcer(registry=registry)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTestEnforcerCheckCommit:
    """Tests for TestEnforcer.check_commit()."""

    def test_no_bot_code_changes_passes(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_commit(["README.md", "docs/architecture.md"])
        assert result.passed is True

    def test_bot_code_without_tests_fails(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_commit(["src/bots/cortex/bot.py"])
        assert result.passed is False
        assert "cortex" in result.violated_bots

    def test_bot_code_with_tests_passes(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_commit([
            "src/bots/cortex/bot.py",
            "tests/recipes/cortex.yaml",
        ])
        assert result.passed is True

    def test_bot_code_with_testing_code_passes(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_commit([
            "src/bots/cortex/bot.py",
            "src/nexus/testing/judge.py",
        ])
        assert result.passed is True

    def test_prompts_change_without_tests_fails(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_commit(["prompts/dr_cortex.md"])
        assert result.passed is False
        assert "dr_cortex" in result.violated_bots

    def test_prompts_change_with_tests_passes(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_commit([
            "prompts/dr_cortex.md",
            "src/nexus/tests/testing/test_judge.py",
        ])
        assert result.passed is True


class TestTestEnforcerIdentifyAffectedBots:
    """Tests for TestEnforcer._identify_affected_bots()."""

    def test_identifies_bot_from_src_bots(self, test_enforcer: TestEnforcer) -> None:
        bots = test_enforcer._identify_affected_bots(["src/bots/cortex/bot.py"])
        assert "cortex" in bots

    def test_identifies_bot_from_prompts(self, test_enforcer: TestEnforcer) -> None:
        bots = test_enforcer._identify_affected_bots(["prompts/admiral.md"])
        assert "admiral" in bots

    def test_no_bots_for_unrelated_files(self, test_enforcer: TestEnforcer) -> None:
        bots = test_enforcer._identify_affected_bots(["README.md", "docs/setup.md"])
        assert len(bots) == 0

    def test_multiple_bots(self, test_enforcer: TestEnforcer) -> None:
        bots = test_enforcer._identify_affected_bots([
            "src/bots/cortex/bot.py",
            "src/bots/voss/bot.py",
        ])
        assert "cortex" in bots
        assert "voss" in bots


class TestTestEnforcerCIGate:
    """Tests for TestEnforcer.check_ci_gate()."""

    def test_no_bots_passes(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_ci_gate("some diff", [])
        assert result.passed is True

    def test_bots_without_test_changes_fails(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_ci_gate("some diff without tests", ["cortex"])
        assert result.passed is False
        assert "cortex" in result.violated_bots

    def test_bots_with_test_changes_passes(self, test_enforcer: TestEnforcer) -> None:
        result = test_enforcer.check_ci_gate(
            "diff with tests/recipes/cortex.yaml changes", ["cortex"]
        )
        assert result.passed is True


class TestEnforcerSingleton:
    """Tests for the enforcer singleton."""

    def test_enforcer_is_instance(self) -> None:
        assert isinstance(enforcer, TestEnforcer)

    def test_enforcer_has_patterns(self) -> None:
        assert len(enforcer.BOT_CODE_PATTERNS) > 0
        assert len(enforcer.TEST_FILE_PATTERNS) > 0
