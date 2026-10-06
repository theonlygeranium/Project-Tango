"""Control Mode must change the persona prompt without destroying it.

Before this fix, update_persona_behavior rebuilt the live prompt from
``agent._base_instructions``, which Control Mode never set. The first change
replaced the whole prompt (Control Mode instructions, persona, Tango preamble)
with just the override text, and "Exit Control Mode" then restored the old
prompt without the new override.
"""

from __future__ import annotations

from typing import Any

import pytest
from livekit.agents.llm import ChatContext, ChatMessage

import control_mode
from jarvis_agent import Jarvis
from personas import get_persona

EXTRAS = "\n\nMEMORY CONTEXT: the user prefers short answers."
TAIL_MARKER = "You are part of Project Tango"


def _override(override_id: str, change_type: str, content: str) -> dict[str, str]:
    return {"id": override_id, "change_type": change_type, "content": content}


def _agent(persona_id: str = "jacob") -> Jarvis:
    return Jarvis(get_persona(persona_id), llm_model="local/qwen3-fast", prompt_extras=EXTRAS)


async def _say(agent: Jarvis, text: str) -> None:
    message = ChatMessage(role="user", content=[text])
    await agent.on_user_turn_completed(ChatContext(), message)


def _tool(agent: Jarvis) -> Any:
    tools = control_mode.build_control_mode_tools(agent=agent, persona_id=agent.persona.id, pool=object())
    return tools[0]


def test_session_start_prompt_matches_previous_composition() -> None:
    persona = get_persona("jacob")
    agent = _agent()

    # main.py used to bake EXTRAS into persona.system_prompt before Jarvis
    # appended "\n\n" + the Tango preamble; the result must be identical.
    assert agent.instructions.startswith(f"{persona.system_prompt}{EXTRAS}\n\n{TAIL_MARKER}")
    assert agent.instructions.count(TAIL_MARKER) == 1


@pytest.mark.asyncio
async def test_override_outside_control_mode_applies_live_once() -> None:
    agent = _agent()

    first = await agent.apply_persona_overrides([_override("1", "tone", "Be warmer.")])
    second = await agent.apply_persona_overrides(
        [_override("1", "tone", "Be warmer."), _override("2", "behavior_rule", "No jargon.")]
    )

    assert (first, second) == ("live", "live")
    assert agent.instructions.count("[TONE ADJUSTMENT] Be warmer.") == 1
    assert agent.instructions.count("[BEHAVIOR RULE] No jargon.") == 1
    assert "You are Jacob" in agent.instructions
    assert EXTRAS in agent.instructions
    assert agent.instructions.count(TAIL_MARKER) == 1


@pytest.mark.asyncio
async def test_change_in_control_mode_keeps_admin_prompt_and_survives_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[dict[str, str]] = []

    async def fake_save(_pool: Any, _persona_id: str, change_type: str, content: str) -> str:
        saved.append(_override(str(len(saved) + 1), change_type, content))
        return saved[-1]["id"]

    async def fake_load(_pool: Any, _persona_id: str) -> list[dict[str, str]]:
        return list(saved)

    monkeypatch.setattr(control_mode, "save_persona_override", fake_save)
    monkeypatch.setattr(control_mode, "load_persona_overrides", fake_load)
    agent = _agent()

    await _say(agent, "control mode")
    assert agent.instructions == control_mode.CONTROL_MODE_INSTRUCTIONS

    result = await _tool(agent)(change_type="behavior_rule", content="Always end with a question.")

    # Still in Control Mode: the admin prompt must stay in place.
    assert agent.instructions == control_mode.CONTROL_MODE_INSTRUCTIONS
    assert "when you exit Control Mode" in result

    await _say(agent, "exit control mode")

    assert "[BEHAVIOR RULE] Always end with a question." in agent.instructions
    assert "You are Jacob" in agent.instructions
    assert EXTRAS in agent.instructions
    assert agent.instructions.count(TAIL_MARKER) == 1


@pytest.mark.asyncio
async def test_db_reload_failure_leaves_live_prompt_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_save(*_args: Any) -> str:
        return "new-id"

    async def fake_load(*_args: Any) -> list[dict[str, str]]:
        return []  # what load_persona_overrides returns on a DB error

    monkeypatch.setattr(control_mode, "save_persona_override", fake_save)
    monkeypatch.setattr(control_mode, "load_persona_overrides", fake_load)
    agent = _agent()
    before = agent.instructions

    result = await _tool(agent)(change_type="tone", content="Be warmer.")

    assert agent.instructions == before
    assert "could not be applied to the current session" in result


@pytest.mark.asyncio
async def test_save_failure_reports_nothing_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_save(*_args: Any) -> None:
        return None

    monkeypatch.setattr(control_mode, "save_persona_override", fake_save)
    agent = _agent()
    before = agent.instructions

    result = await _tool(agent)(change_type="tone", content="Be warmer.")

    assert agent.instructions == before
    assert "could not be saved" in result


@pytest.mark.asyncio
async def test_change_during_program_is_restored_when_program_ends() -> None:
    agent = _agent()
    persona_instructions = agent.instructions
    # Simulate an active program the way on_user_turn_completed sets it up.
    agent._base_instructions = persona_instructions
    agent._active_program = "focus-coach"
    await agent.update_instructions("PROGRAM PROMPT")

    applied = await agent.apply_persona_overrides([_override("1", "tone", "Be calmer.")])

    assert applied == "after_program"
    assert agent.instructions == "PROGRAM PROMPT"
    assert "[TONE ADJUSTMENT] Be calmer." in (agent._base_instructions or "")
