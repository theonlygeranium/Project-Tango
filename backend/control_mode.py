"""Control Mode — voice-driven administrative override for persona behavior.

When the user says "Control Mode" mid-conversation, the agent swaps its system
prompt to an administrative prompt that lets the user adjust the persona's
tone, instructions, or behavior rules.  Changes are persisted to PostgreSQL
(``tango.persona_overrides``) and applied to all future sessions with that
persona.  Saying "Exit Control Mode" restores the normal persona prompt.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import asyncpg
from livekit.agents.llm import function_tool

logger = logging.getLogger("project-tango.control-mode")

# ---------------------------------------------------------------------------
# Trigger phrases
# ---------------------------------------------------------------------------

CONTROL_MODE_PHRASES: tuple[str, ...] = (
    "control mode",
    "control mood",  # STT may mishear
    "control modes",
    "enter control mode",
    "activate control mode",
    "go to control mode",
    "switch to control mode",
)

EXIT_CONTROL_MODE_PHRASES: tuple[str, ...] = (
    "exit control mode",
    "exit control mood",
    "leave control mode",
    "leave control mood",
    "end control mode",
    "stop control mode",
    "exit admin mode",
    "back to normal",
    "resume normal",
    "resume normal mode",
)

# ---------------------------------------------------------------------------
# Control Mode system prompt
# ---------------------------------------------------------------------------

CONTROL_MODE_INSTRUCTIONS = (
    "You are now in CONTROL MODE — an administrative state for Project Tango.\n\n"
    "In this mode your sole purpose is to help the user adjust the persona's "
    "behavior, tone, or system prompt. You are no longer acting as the persona "
    "for general conversation. Instead, you are a configuration assistant.\n\n"
    "RULES:\n"
    "1. Listen to what the user wants to change about the persona's behavior.\n"
    "2. Translate their request into a structured change using the "
    "update_persona_behavior tool.\n"
    "3. The change_type should be:\n"
    "   - 'tone' for adjustments to speaking style, warmth, formality, etc.\n"
    "   - 'instruction_addition' for new rules or guidance to add.\n"
    "   - 'instruction_replacement' to replace the entire persona system prompt.\n"
    "   - 'behavior_rule' for specific behavioral constraints.\n"
    "4. After applying a change, confirm what was changed in plain language "
    "and ask if there's anything else to adjust.\n"
    "5. When the user is done, they will say 'Exit Control Mode' to return to "
    "normal conversation.\n"
    "6. Keep your responses short and conversational — this is still a voice "
    "interface.\n"
    "7. If the user asks something unrelated to persona configuration, gently "
    "remind them they're in Control Mode and ask if they want to exit first.\n"
)

# ---------------------------------------------------------------------------
# Phrase detection
# ---------------------------------------------------------------------------

def detect_control_mode_phrase(text: str) -> str | None:
    """Check if *text* contains a control mode trigger phrase.

    Returns ``"enter"`` if an entry phrase is detected, ``"exit"`` if an exit
    phrase is detected, or ``None`` if no phrase matches.
    """
    if not text:
        return None

    normalized = text.strip().lower().rstrip(".!?,")

    # Check exit phrases first — "exit control mode" contains "control mode"
    # so we must check the more specific pattern before the generic one.
    for phrase in EXIT_CONTROL_MODE_PHRASES:
        if phrase in normalized:
            return "exit"

    for phrase in CONTROL_MODE_PHRASES:
        if phrase in normalized:
            return "enter"

    return None


def control_mode_enabled() -> bool:
    """Master switch — check env var."""
    return os.getenv("TANGO_CONTROL_MODE", "true").lower() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

async def load_persona_overrides(
    pool: asyncpg.Pool, persona_id: str
) -> list[dict[str, str]]:
    """Load all active overrides for a persona, ordered oldest-first."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, change_type, content
                FROM tango.persona_overrides
                WHERE persona_id = $1 AND active = TRUE
                ORDER BY created_at ASC
                """,
                persona_id,
            )
        return [
            {
                "id": str(row["id"]),
                "change_type": row["change_type"],
                "content": row["content"],
            }
            for row in rows
        ]
    except Exception:
        logger.exception("Failed to load persona overrides persona_id=%s", persona_id)
        return []


async def save_persona_override(
    pool: asyncpg.Pool,
    persona_id: str,
    change_type: str,
    content: str,
) -> str | None:
    """Persist a new override row. Returns the override ID or None on failure."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO tango.persona_overrides
                    (persona_id, change_type, content)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                persona_id,
                change_type,
                content,
            )
        override_id = str(row["id"]) if row else None
        logger.info(
            "Saved persona override persona_id=%s type=%s id=%s",
            persona_id,
            change_type,
            override_id,
        )
        return override_id
    except Exception:
        logger.exception(
            "Failed to save persona override persona_id=%s type=%s",
            persona_id,
            change_type,
        )
        return None


# ---------------------------------------------------------------------------
# Override application
# ---------------------------------------------------------------------------

def apply_overrides_to_prompt(
    base_prompt: str, overrides: list[dict[str, str]]
) -> str:
    """Merge persona overrides into a system prompt string.

    - ``instruction_replacement``: replaces the entire base prompt (only the
      last one wins if multiple exist).
    - ``tone``, ``instruction_addition``, ``behavior_rule``: appended to the
      base prompt in order.
    """
    if not overrides:
        return base_prompt

    # Check for a full replacement — last one wins.
    replacement = None
    additions: list[str] = []

    for ov in overrides:
        ct = ov["change_type"]
        content = ov["content"]
        if ct == "instruction_replacement":
            replacement = content
        elif ct in ("tone", "instruction_addition", "behavior_rule"):
            label = {
                "tone": "TONE ADJUSTMENT",
                "instruction_addition": "ADDITIONAL INSTRUCTION",
                "behavior_rule": "BEHAVIOR RULE",
            }.get(ct, ct.upper())
            additions.append(f"[{label}] {content}")

    if replacement is not None:
        prompt = replacement
    else:
        prompt = base_prompt

    if additions:
        prompt = prompt + "\n\n" + "\n".join(additions)

    return prompt


# ---------------------------------------------------------------------------
# Function tool for applying changes
# ---------------------------------------------------------------------------

def build_control_mode_tools(agent: Any, persona_id: str, pool: asyncpg.Pool) -> list[Any]:
    """Build the function tools used while in Control Mode.

    Returns a list containing the ``update_persona_behavior`` tool, which
    is bound to *agent* so it can call ``update_instructions`` and to
    *pool*/*persona_id* so it can persist changes.
    """

    @function_tool
    async def update_persona_behavior(
        change_type: str,
        content: str,
    ) -> str:
        """Apply a behavior change to the current persona.

        Args:
            change_type: One of 'tone', 'instruction_addition',
                'instruction_replacement', 'behavior_rule'.
                - 'tone': Adjust the persona's speaking style, warmth, formality.
                - 'instruction_addition': Add a new rule or guidance to the persona.
                - 'instruction_replacement': Replace the entire persona system prompt.
                - 'behavior_rule': Add a specific behavioral constraint.
            content: The new instruction, tone description, or behavior rule text.

        Returns:
            A confirmation message describing what was changed.
        """
        valid_types = {
            "tone",
            "instruction_addition",
            "instruction_replacement",
            "behavior_rule",
        }
        if change_type not in valid_types:
            return (
                f"Invalid change_type '{change_type}'. "
                f"Must be one of: {', '.join(sorted(valid_types))}."
            )

        if not content or not content.strip():
            return "Content cannot be empty."

        content = content.strip()

        # Persist to database for future sessions.
        override_id = await save_persona_override(pool, persona_id, change_type, content)

        # Apply to the current session immediately.
        # Rebuild the full instructions with all overrides (including the new one).
        overrides = await load_persona_overrides(pool, persona_id)

        # Get the base instructions (stored when entering Control Mode).
        base = getattr(agent, "_base_instructions", None) or ""

        # For instruction_replacement, the base is replaced entirely.
        # For other types, we append to the base.
        new_prompt = apply_overrides_to_prompt(base, overrides)

        try:
            await agent.update_instructions(new_prompt)
            logger.info(
                "Applied persona override to live session persona_id=%s type=%s override_id=%s",
                persona_id,
                change_type,
                override_id,
            )
        except Exception:
            logger.exception(
                "Failed to update instructions live persona_id=%s type=%s",
                persona_id,
                change_type,
            )
            return "The change was saved for future sessions, but could not be applied to the current session."

        type_labels = {
            "tone": "Tone adjustment",
            "instruction_addition": "Instruction added",
            "instruction_replacement": "System prompt replaced",
            "behavior_rule": "Behavior rule added",
        }
        label = type_labels.get(change_type, change_type)
        return f"{label} applied successfully. The change is now active and will persist for all future sessions with this persona."

    return [update_persona_behavior]
