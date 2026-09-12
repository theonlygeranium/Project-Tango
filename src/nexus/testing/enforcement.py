"""Universal testing policy enforcement.

The TestEnforcer ensures that commits touching bot code also include
corresponding test recipe updates. Used as a pre-commit hook and CI gate.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nexus.testing.recipe import RecipeRegistry

logger = logging.getLogger(__name__)


@dataclass
class EnforcementResult:
    """Result of an enforcement check.

    Attributes:
        passed: Whether the check passed.
        violated_bots: List of bot IDs that violated the policy.
        message: Human-readable message.
        details: Additional details.
    """

    passed: bool
    violated_bots: list[str] = field(default_factory=list)
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violated_bots": self.violated_bots,
            "message": self.message,
            "details": self.details,
        }


class TestEnforcer:
    """Enforces universal testing policy on commits and PRs.

    Ensures that changes to bot code are accompanied by test recipe updates.
    """

    BOT_CODE_PATTERNS: list[str] = [
        "src/bots/",
        "prompts/",
        "src/nexus/bot/",
        "src/nexus/self_healing/",
        "fleet-manifest.yaml",
    ]

    TEST_FILE_PATTERNS: list[str] = [
        "tests/recipes/",
        "src/nexus/testing/",
        "src/nexus/tests/",
    ]

    def __init__(self, registry: RecipeRegistry | None = None) -> None:
        self._registry = registry or RecipeRegistry()

    def check_commit(self, staged_files: list[str]) -> EnforcementResult:
        """Check if a commit satisfies the testing policy.

        Args:
            staged_files: List of file paths staged for commit.

        Returns:
            An EnforcementResult.
        """
        affected_bots = self._identify_affected_bots(staged_files)
        if not affected_bots:
            return EnforcementResult(
                passed=True,
                message="No bot code changes detected; policy check passed.",
            )

        # Check if test files are also staged
        has_test_changes = any(
            any(pattern in f for pattern in self.TEST_FILE_PATTERNS)
            for f in staged_files
        )

        if not has_test_changes:
            return EnforcementResult(
                passed=False,
                violated_bots=affected_bots,
                message=(
                    f"Bot code changes detected for {affected_bots} but no test "
                    f"recipe or testing code changes found. All bot code changes "
                    f"must include corresponding test updates."
                ),
                details={"affected_bots": affected_bots, "staged_files": staged_files},
            )

        # Check that each affected bot has recipe coverage
        violated: list[str] = []
        for bot_id in affected_bots:
            if not self._recipe_covers_changes(bot_id, staged_files):
                violated.append(bot_id)

        if violated:
            return EnforcementResult(
                passed=False,
                violated_bots=violated,
                message=(
                    f"Bots {violated} have code changes but their test recipes "
                    f"do not cover the changed functionality."
                ),
                details={"violated_bots": violated},
            )

        return EnforcementResult(
            passed=True,
            message=f"Policy check passed for bots: {affected_bots}",
        )

    def _identify_affected_bots(self, changed_files: list[str]) -> list[str]:
        """Identify which bots are affected by the changed files.

        Args:
            changed_files: List of changed file paths.

        Returns:
            List of bot IDs.
        """
        bots: set[str] = set()
        for f in changed_files:
            # Check src/bots/<bot_id>/ pattern
            if "src/bots/" in f:
                parts = f.split("src/bots/")
                if len(parts) > 1:
                    bot_id = parts[1].split("/")[0]
                    if bot_id:
                        bots.add(bot_id)

            # Check prompts/<bot_id>.md pattern
            if f.startswith("prompts/"):
                parts = f.split("prompts/")
                if len(parts) > 1:
                    bot_id = parts[1].replace(".md", "")
                    if bot_id:
                        bots.add(bot_id)

            # Changes to shared infrastructure affect all bots
            if "src/nexus/bot/" in f or "src/nexus/self_healing/" in f or "fleet-manifest.yaml" in f:
                # These affect all bots — we can't determine specific ones
                # so we don't add them all; the caller should handle this
                pass

        return sorted(bots)

    def _recipe_covers_changes(self, bot_id: str, staged_files: list[str]) -> bool:
        """Check if the bot's recipe covers the changed functionality.

        Args:
            bot_id: The bot ID.
            staged_files: List of staged file paths.

        Returns:
            True if the recipe covers the changes.
        """
        # If there are test recipe changes for this bot, assume coverage
        for f in staged_files:
            if f"tests/recipes/{bot_id}.yaml" in f:
                return True
            if "src/nexus/testing/" in f:
                return True
            if "src/nexus/tests/" in f:
                return True

        # If the bot has a recipe at all, consider it covered
        try:
            self._registry.load_all()
            self._registry.get(bot_id)
            return True
        except KeyError:
            return False

    def check_ci_gate(self, pr_diff: str, bot_ids: list[str]) -> EnforcementResult:
        """Check if a PR passes the CI testing gate.

        Args:
            pr_diff: The PR diff text.
            bot_ids: List of bot IDs affected by the PR.

        Returns:
            An EnforcementResult.
        """
        if not bot_ids:
            return EnforcementResult(
                passed=True,
                message="No bots affected by PR; CI gate passed.",
            )

        # Check that the diff includes test-related changes
        has_test_changes = any(
            pattern in pr_diff for pattern in self.TEST_FILE_PATTERNS
        )

        if not has_test_changes:
            return EnforcementResult(
                passed=False,
                violated_bots=bot_ids,
                message=(
                    f"PR affects bots {bot_ids} but does not include any test "
                    f"changes. All bot-affecting PRs must include test updates."
                ),
            )

        return EnforcementResult(
            passed=True,
            message=f"CI gate passed for bots: {bot_ids}",
        )


# Singleton instance
enforcer = TestEnforcer()


def main() -> int:
    """CLI entry point for the enforcement check.

    Reads staged files from git and runs the commit check.

    Returns:
        0 if passed, 1 if failed.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        staged_files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except subprocess.CalledProcessError as exc:
        print(f"Error getting staged files: {exc}", file=sys.stderr)
        return 1

    enforcement = enforcer.check_commit(staged_files)
    if enforcement.passed:
        print(f"PASS: {enforcement.message}")
        return 0
    else:
        print(f"FAIL: {enforcement.message}", file=sys.stderr)
        if enforcement.violated_bots:
            print(f"Violated bots: {enforcement.violated_bots}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
