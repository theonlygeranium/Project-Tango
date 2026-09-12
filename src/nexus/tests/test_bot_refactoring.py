"""Tests for NX-SPEC-05: Bot Refactoring (All 7 Bots).

Tests each bot's inheritance, abstract method implementation, system prompt,
tools, and task handling (success and failure paths). Also validates fleet-wide
constraints: unique bot IDs, prompt file existence, and tier assignments from
the fleet manifest.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.bot.base import FleetBot
from nexus.bot.tools import Tool
from nexus.bus.event import NexusEvent
from nexus.manifest.loader import load_manifest

from bots.admiral.bot import AdmiralBot
from bots.admiral.tools import ADMIRAL_TOOLS
from bots.architect.bot import ArchitectBot
from bots.architect.tools import ARCHITECT_TOOLS
from bots.cartographer.bot import CartographerBot
from bots.cartographer.tools import CARTOGRAPHER_TOOLS
from bots.cortex.bot import DrCortexBot
from bots.cortex.tools import DR_CORTEX_TOOLS
from bots.proctor.bot import ProctorBot
from bots.proctor.tools import PROCTOR_TOOLS
from bots.quartermaster.bot import QuartermasterBot
from bots.quartermaster.tools import QUARTERMASTER_TOOLS
from bots.voss.bot import DrVossBot
from bots.voss.tools import DR_VOSS_TOOLS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "fleet-manifest.yaml"
PROMPTS_DIR = REPO_ROOT / "prompts"

BOT_CLASSES: dict[str, type[FleetBot]] = {
    "admiral": AdmiralBot,
    "architect": ArchitectBot,
    "voss": DrVossBot,
    "cortex": DrCortexBot,
    "quartermaster": QuartermasterBot,
    "cartographer": CartographerBot,
    "proctor": ProctorBot,
}

BOT_TOOL_LISTS: dict[str, list[Tool]] = {
    "admiral": ADMIRAL_TOOLS,
    "architect": ARCHITECT_TOOLS,
    "voss": DR_VOSS_TOOLS,
    "cortex": DR_CORTEX_TOOLS,
    "quartermaster": QUARTERMASTER_TOOLS,
    "cartographer": CARTOGRAPHER_TOOLS,
    "proctor": PROCTOR_TOOLS,
}

PROMPT_FILES: dict[str, str] = {
    "admiral": "prompts/admiral.md",
    "architect": "prompts/architect.md",
    "voss": "prompts/dr_voss.md",
    "cortex": "prompts/dr_cortex.md",
    "quartermaster": "prompts/quartermaster.md",
    "cartographer": "prompts/cartographer.md",
    "proctor": "prompts/proctor.md",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_prompt_file(bot_id: str) -> str:
    """Create a temporary prompt file for a bot and return its path."""
    prompt_rel = PROMPT_FILES[bot_id]
    prompt_path = REPO_ROOT / prompt_rel
    if prompt_path.exists():
        return str(prompt_path)
    # Fallback: create a temp file
    fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix=f"{bot_id}_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"# {bot_id} prompt\n")
    return tmp_path


def _make_bot_config(bot_id: str) -> Any:
    """Create a BotConfig for a bot from the manifest."""
    manifest = load_manifest(MANIFEST_PATH)
    return manifest.bots[bot_id]


def _make_mock_nexus() -> Any:
    """Create a mock NexusBus with async publish."""
    nexus = MagicMock()
    nexus.publish = AsyncMock()
    nexus.subscribe = AsyncMock()
    return nexus


def _make_mock_llm(content: str = "LLM response") -> Any:
    """Create a mock LLM client with async call returning content."""
    llm = MagicMock()
    llm.call = AsyncMock(return_value=MagicMock(content=content))
    return llm


def _make_mock_discord() -> Any:
    """Create a mock DiscordHandler with async send."""
    discord_handler = MagicMock()
    discord_handler.send = AsyncMock()
    return discord_handler


def _make_bot(bot_id: str) -> FleetBot:
    """Create a bot instance with mocked dependencies."""
    config = _make_bot_config(bot_id)
    nexus = _make_mock_nexus()
    bot = BOT_CLASSES[bot_id](bot_id, config, nexus)
    bot.llm = _make_mock_llm()
    bot.discord = _make_mock_discord()
    return bot


def _make_task_event(bot_id: str) -> NexusEvent:
    """Create a task.new event for testing handle_task."""
    return NexusEvent.create(
        event_type="task.new",
        source="admiral",
        target=bot_id,
        payload={
            "task_id": "test-task-001",
            "description": "Test task for bot",
            "task_type": "test",
            "priority": "medium",
            "deadline": None,
        },
    )


# ---------------------------------------------------------------------------
# Per-bot tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bot_id", list(BOT_CLASSES.keys()))
def test_bot_inherits_fleetbot(bot_id: str) -> None:
    """Bot class is a subclass of FleetBot."""
    bot_class = BOT_CLASSES[bot_id]
    assert issubclass(bot_class, FleetBot)


@pytest.mark.parametrize("bot_id", list(BOT_CLASSES.keys()))
def test_bot_implements_abstract_methods(bot_id: str) -> None:
    """All 4 abstract methods are implemented (not raising NotImplementedError)."""
    bot = _make_bot(bot_id)

    # get_system_prompt should not raise NotImplementedError
    prompt = bot.get_system_prompt()
    assert isinstance(prompt, str)

    # get_tools should not raise NotImplementedError
    tools = bot.get_tools()
    assert isinstance(tools, list)

    # handle_task and handle_message are async — verify they don't raise
    # NotImplementedError when called (we test them properly below)
    import inspect

    assert inspect.iscoroutinefunction(bot.handle_task)
    assert inspect.iscoroutinefunction(bot.handle_message)


@pytest.mark.parametrize("bot_id", list(BOT_CLASSES.keys()))
def test_bot_get_system_prompt(bot_id: str) -> None:
    """get_system_prompt returns a non-empty string."""
    bot = _make_bot(bot_id)
    prompt = bot.get_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 0


@pytest.mark.parametrize("bot_id", list(BOT_CLASSES.keys()))
def test_bot_get_tools(bot_id: str) -> None:
    """get_tools returns a list of Tool objects."""
    bot = _make_bot(bot_id)
    tools = bot.get_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
    for tool in tools:
        assert isinstance(tool, Tool)
        assert isinstance(tool.name, str)
        assert len(tool.name) > 0
        assert isinstance(tool.description, str)
        assert len(tool.description) > 0
        assert isinstance(tool.parameters, dict)


@pytest.mark.parametrize("bot_id", list(BOT_CLASSES.keys()))
@pytest.mark.asyncio
async def test_bot_handle_task_success(bot_id: str) -> None:
    """handle_task processes a task and publishes task.result with status success."""
    bot = _make_bot(bot_id)
    event = _make_task_event(bot_id)

    await bot.handle_task(event)

    # nexus.publish should have been called
    assert bot.nexus.publish.called

    # Check the published event
    published_event = bot.nexus.publish.call_args.args[0]
    assert published_event.event_type == "task.result"
    assert published_event.payload["task_id"] == "test-task-001"
    assert published_event.payload["status"] == "success"
    assert published_event.payload["error"] is None
    assert "content" in published_event.payload["result"]


@pytest.mark.parametrize("bot_id", list(BOT_CLASSES.keys()))
@pytest.mark.asyncio
async def test_bot_handle_task_failure(bot_id: str) -> None:
    """handle_task catches exceptions and publishes failure result."""
    bot = _make_bot(bot_id)
    # Make LLM call raise an exception
    bot.llm.call = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    event = _make_task_event(bot_id)

    await bot.handle_task(event)

    # nexus.publish should have been called
    assert bot.nexus.publish.called

    # Check the published event has failure status
    published_event = bot.nexus.publish.call_args.args[0]
    assert published_event.event_type == "task.result"
    assert published_event.payload["task_id"] == "test-task-001"
    assert published_event.payload["status"] == "failure"
    assert "LLM unavailable" in published_event.payload["error"]


# ---------------------------------------------------------------------------
# Fleet-wide tests
# ---------------------------------------------------------------------------


def test_all_bots_have_unique_ids() -> None:
    """All 7 bot IDs in BOT_CLASSES are unique."""
    bot_ids = list(BOT_CLASSES.keys())
    assert len(bot_ids) == len(set(bot_ids)), "Bot IDs are not unique"
    assert len(bot_ids) == 7


def test_all_prompt_files_exist() -> None:
    """All prompt files referenced by the manifest exist on disk."""
    for bot_id, prompt_rel in PROMPT_FILES.items():
        prompt_path = REPO_ROOT / prompt_rel
        assert prompt_path.exists(), f"Prompt file missing for {bot_id}: {prompt_path}"


def test_admiral_is_sole_tier_0() -> None:
    """From the manifest, admiral is the sole tier 0 bot."""
    manifest = load_manifest(MANIFEST_PATH)
    tier_0_bots = [name for name, bot in manifest.bots.items() if bot.tier == 0]
    assert len(tier_0_bots) == 1
    assert tier_0_bots[0] == "admiral"


def test_architect_is_tier_1() -> None:
    """From the manifest, architect is tier 1."""
    manifest = load_manifest(MANIFEST_PATH)
    assert manifest.bots["architect"].tier == 1


# ---------------------------------------------------------------------------
# Tool count validation
# ---------------------------------------------------------------------------


def test_admiral_has_8_tools() -> None:
    """Admiral has 8 tools."""
    assert len(ADMIRAL_TOOLS) == 8


def test_architect_has_7_tools() -> None:
    """Architect has 7 tools."""
    assert len(ARCHITECT_TOOLS) == 7


def test_voss_has_5_tools() -> None:
    """Dr. Voss has 5 tools."""
    assert len(DR_VOSS_TOOLS) == 5


def test_cortex_has_6_tools() -> None:
    """Dr. Cortex has 6 tools."""
    assert len(DR_CORTEX_TOOLS) == 6


def test_quartermaster_has_6_tools() -> None:
    """Quartermaster has 6 tools."""
    assert len(QUARTERMASTER_TOOLS) == 6


def test_cartographer_has_5_tools() -> None:
    """Cartographer has 5 tools."""
    assert len(CARTOGRAPHER_TOOLS) == 5


def test_proctor_has_4_tools() -> None:
    """Proctor has 4 tools."""
    assert len(PROCTOR_TOOLS) == 4
