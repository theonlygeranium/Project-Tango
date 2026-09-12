"""Auto-generation of test recipes from code diffs.

The RecipeGenerator analyzes code changes (diffs), identifies new tools and
features, and generates test cases via LLM. It then updates the recipe version
and coverage mapping.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nexus.testing.recipe import RecipeRegistry, TestCase, TestRecipe

logger = logging.getLogger(__name__)


@dataclass
class CodeChange:
    """A single code change extracted from a diff.

    Attributes:
        file_path: Path to the changed file.
        change_type: "added", "modified", or "deleted".
        bot_id: The bot affected by this change, if identifiable.
        new_tools: List of new tool names introduced.
        new_features: List of new feature names introduced.
        diff_lines: The actual diff lines.
    """

    file_path: str
    change_type: str = "modified"
    bot_id: str | None = None
    new_tools: list[str] = field(default_factory=list)
    new_features: list[str] = field(default_factory=list)
    diff_lines: str = ""


class RecipeGenerator:
    """Auto-generates test recipes from code diffs.

    Uses LLM to generate test cases for new features and tools, then updates
    the recipe version and coverage mapping.
    """

    def __init__(
        self,
        registry: RecipeRegistry,
        llm_client: Any,
        nexus_bus: Any,
    ) -> None:
        self._registry = registry
        self._llm_client = llm_client
        self._nexus_bus = nexus_bus

    async def analyze_diff(self, diff_text: str) -> list[CodeChange]:
        """Analyze a code diff and extract structured code changes.

        Args:
            diff_text: The raw diff text.

        Returns:
            List of CodeChange objects.
        """
        changes: list[CodeChange] = []
        current_file: str | None = None
        current_lines: list[str] = []
        change_type = "modified"

        for line in diff_text.splitlines():
            if line.startswith("diff --git"):
                if current_file is not None:
                    changes.append(
                        self._build_change(current_file, change_type, "\n".join(current_lines))
                    )
                current_file = None
                current_lines = []
                change_type = "modified"
            elif line.startswith("+++ b/"):
                current_file = line[6:].strip()
                if current_file and not any(
                    current_file.endswith(ext) for ext in (".py", ".md", ".yaml", ".yml")
                ):
                    current_file = None
            elif line.startswith("--- "):
                if line.strip() == "--- /dev/null":
                    change_type = "added"
            elif line.startswith("-") and not line.startswith("---"):
                if change_type != "added":
                    change_type = "modified"
            elif line.startswith("+") and not line.startswith("+++"):
                current_lines.append(line[1:])

        if current_file is not None:
            changes.append(
                self._build_change(current_file, change_type, "\n".join(current_lines))
            )

        logger.info("Analyzed diff: found %d code changes", len(changes))
        return changes

    def _build_change(self, file_path: str, change_type: str, diff_lines: str) -> CodeChange:
        """Build a CodeChange from extracted information.

        Args:
            file_path: Path to the changed file.
            change_type: Type of change.
            diff_lines: The diff content.

        Returns:
            A CodeChange instance.
        """
        bot_id = self._identify_bot(file_path)
        new_tools = self._extract_tools(diff_lines)
        new_features = self._extract_features(diff_lines)

        return CodeChange(
            file_path=file_path,
            change_type=change_type,
            bot_id=bot_id,
            new_tools=new_tools,
            new_features=new_features,
            diff_lines=diff_lines,
        )

    def _identify_bot(self, file_path: str) -> str | None:
        """Identify which bot a file path belongs to.

        Args:
            file_path: The file path.

        Returns:
            Bot ID or None.
        """
        parts = file_path.split("/")
        if "bots" in parts:
            idx = parts.index("bots")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return None

    def _extract_tools(self, diff_lines: str) -> list[str]:
        """Extract new tool names from diff lines.

        Args:
            diff_lines: The added lines from the diff.

        Returns:
            List of tool names.
        """
        tools: list[str] = []
        tool_pattern = re.compile(r'Tool\s*\(\s*name\s*=\s*["\']([^"\']+)["\']')
        for match in tool_pattern.finditer(diff_lines):
            tools.append(match.group(1))
        return tools

    def _extract_features(self, diff_lines: str) -> list[str]:
        """Extract new feature names from diff lines.

        Args:
            diff_lines: The added lines from the diff.

        Returns:
            List of feature names.
        """
        features: list[str] = []
        feature_pattern = re.compile(r'(?:feature|FEATURE)["\']?\s*[:=]\s*["\']([^"\']+)["\']')
        for match in feature_pattern.finditer(diff_lines):
            features.append(match.group(1))
        return features

    async def generate_cases(
        self,
        changes: list[CodeChange],
        existing_recipe: TestRecipe | None = None,
    ) -> list[TestCase]:
        """Generate test cases for a list of code changes.

        Args:
            changes: List of code changes.
            existing_recipe: Existing recipe for the bot, if any.

        Returns:
            List of generated TestCase objects.
        """
        new_cases: list[TestCase] = []
        existing_cases = existing_recipe.cases if existing_recipe else []

        for change in changes:
            if change.bot_id is None:
                continue
            for difficulty in ("easy", "medium", "hard"):
                test_case = await self._generate_case_via_llm(
                    change.bot_id, change, difficulty, existing_cases
                )
                if test_case is not None:
                    new_cases.append(test_case)

        logger.info("Generated %d new test cases", len(new_cases))
        return new_cases

    async def _generate_case_via_llm(
        self,
        bot_id: str,
        change: CodeChange,
        difficulty: str,
        existing_cases: list[TestCase],
    ) -> TestCase:
        """Generate a single test case via LLM.

        Args:
            bot_id: The bot ID.
            change: The code change.
            difficulty: The difficulty level.
            existing_cases: Existing test cases for context.

        Returns:
            A TestCase instance.
        """
        prompt = self._build_generation_prompt(bot_id, change, difficulty, existing_cases)
        try:
            response = await self._llm_client.call(
                messages=[{"role": "user", "content": prompt}],
                model="writer/palmyra-x6",
                temperature=0.4,
            )
            response_text = ""
            if isinstance(response, dict):
                response_text = response.get("content", "")
            elif isinstance(response, str):
                response_text = response
            return self._parse_generated_case(response_text, bot_id)
        except Exception as exc:
            logger.error("LLM case generation failed for %s: %s", bot_id, exc)
            return self._fallback_case(bot_id, change, difficulty)

    def _build_generation_prompt(
        self,
        bot_id: str,
        change: CodeChange,
        difficulty: str,
        existing_cases: list[TestCase],
    ) -> str:
        """Build the prompt for LLM test case generation.

        Args:
            bot_id: The bot ID.
            change: The code change.
            difficulty: The difficulty level.
            existing_cases: Existing test cases for context.

        Returns:
            The prompt string.
        """
        existing_ids = [c.test_id for c in existing_cases[-5:]]
        tools_str = ", ".join(change.new_tools) if change.new_tools else "none"
        features_str = ", ".join(change.new_features) if change.new_features else "none"

        return f"""You are a test case generator for a fleet of AI bots.

## Bot: {bot_id}
## Code Change
- File: {change.file_path}
- Type: {change.change_type}
- New tools: {tools_str}
- New features: {features_str}
- Diff: {change.diff_lines[:500]}

## Existing test IDs (for reference): {existing_ids}

## Task
Generate a {difficulty} test case for this bot that tests the new functionality.
The test case should be realistic and test the bot's behavior.

Respond in JSON format:
```json
{{
  "test_id": "{bot_id}-gen-<unique>",
  "category": "new_feature",
  "question": "<a realistic question for the bot>",
  "follow_ups": ["<follow-up 1>", "<follow-up 2>"],
  "expected_behavior": "<what the bot should do>",
  "acceptance_keywords": ["<keyword1>"],
  "rejection_keywords": ["<keyword1>"],
  "rubric_id": "new_feature_rubric",
  "difficulty": "{difficulty}",
  "min_score": 7.0
}}
```
"""

    def _parse_generated_case(self, response: str, bot_id: str) -> TestCase:
        """Parse the LLM-generated test case from the response.

        Args:
            response: The raw LLM response.
            bot_id: The bot ID.

        Returns:
            A TestCase instance.
        """
        import json

        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            json_str = json_match.group(0) if json_match else "{}"

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse generated case JSON")
            return self._fallback_case(bot_id, CodeChange(file_path="unknown"), "medium")

        return TestCase(
            test_id=data.get("test_id", f"{bot_id}-gen-{datetime.now(timezone.utc).strftime('%H%M%S')}"),
            category=data.get("category", "new_feature"),
            question=data.get("question", ""),
            follow_ups=data.get("follow_ups", []),
            expected_behavior=data.get("expected_behavior", ""),
            acceptance_keywords=data.get("acceptance_keywords", []),
            rejection_keywords=data.get("rejection_keywords", []),
            rubric_id=data.get("rubric_id", "new_feature_rubric"),
            difficulty=data.get("difficulty", "medium"),
            source="generated",
            created_at=datetime.now(timezone.utc).isoformat(),
            tests_feature=data.get("tests_feature"),
            min_score=float(data.get("min_score", 7.0)),
        )

    def _fallback_case(self, bot_id: str, change: CodeChange, difficulty: str) -> TestCase:
        """Generate a fallback test case when LLM generation fails.

        Args:
            bot_id: The bot ID.
            change: The code change.
            difficulty: The difficulty level.

        Returns:
            A TestCase instance.
        """
        return TestCase(
            test_id=f"{bot_id}-gen-fallback-{difficulty}",
            category="new_feature",
            question=f"How do you handle the new feature in {change.file_path}?",
            follow_ups=[],
            expected_behavior="Bot should demonstrate awareness of the new feature",
            acceptance_keywords=[],
            rejection_keywords=[],
            rubric_id="new_feature_rubric",
            difficulty=difficulty,
            source="generated",
            created_at=datetime.now(timezone.utc).isoformat(),
            tests_feature=change.new_features[0] if change.new_features else None,
            min_score=7.0,
        )

    async def update_recipe(self, bot_id: str, new_cases: list[TestCase]) -> TestRecipe:
        """Update a recipe with new test cases.

        Args:
            bot_id: The bot ID.
            new_cases: New test cases to add.

        Returns:
            The updated TestRecipe.
        """
        try:
            existing = self._registry.get(bot_id)
        except KeyError:
            existing = TestRecipe(bot_id=bot_id, version="1.0.0")

        existing.cases.extend(new_cases)
        existing.version = self._bump_version(existing.version)
        self._update_coverage(existing)
        self._registry.save(bot_id, existing)
        logger.info("Updated recipe for %s: %d total cases", bot_id, len(existing.cases))
        return existing

    def _bump_version(self, version: str) -> str:
        """Bump the patch version of a semantic version string.

        Args:
            version: Semantic version string (e.g. "1.0.0").

        Returns:
            Bumped version string (e.g. "1.0.1").
        """
        parts = version.split(".")
        if len(parts) == 3:
            try:
                parts[2] = str(int(parts[2]) + 1)
                return ".".join(parts)
            except ValueError:
                pass
        return "1.0.1"

    def _update_coverage(self, recipe: TestRecipe) -> None:
        """Update the coverage mapping for a recipe.

        Args:
            recipe: The recipe to update.
        """
        coverage: dict[str, list[str]] = {}
        for case in recipe.cases:
            coverage.setdefault(case.category, []).append(case.test_id)
        recipe.coverage = coverage
        recipe.total_cases = len(recipe.cases)
