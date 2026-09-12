"""Programs — voice-created derived personas with custom system prompts.

A Program is a named profile that inherits the base persona's voice, TTS, STT,
and MCP tools, but swaps the system prompt for a specialized purpose (e.g.
"therapy program", "coding program").  Programs are created via the
``create_program`` function tool while in Control Mode, persisted to
PostgreSQL (``tango.programs``), and activated by voice commands like
"activate therapy program" during normal conversation.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import asyncpg
from livekit.agents.llm import function_tool

logger = logging.getLogger("project-tango.programs")

# ---------------------------------------------------------------------------
# Trigger phrases
# ---------------------------------------------------------------------------

ACTIVATE_PHRASES: tuple[str, ...] = (
    "activate",
    "switch to",
    "start",
)

DEACTIVATE_PHRASES: tuple[str, ...] = (
    "deactivate program",
    "return to default",
    "exit program",
    "deactivate",
    "end program",
    "stop program",
    "back to default",
    "back to normal program",
    "default program",
)

# Suffix that must follow the program name for a valid activation phrase.
_PROGRAM_SUFFIX = "program"


# ---------------------------------------------------------------------------
# Phrase detection
# ---------------------------------------------------------------------------

def detect_program_activation(text: str) -> tuple[str, str] | None:
    """Check if *text* contains a program activation or deactivation phrase.

    Returns a tuple ``(action, program_name)`` where *action* is
    ``"activate"`` or ``"deactivate"``.  For deactivation, *program_name*
    is an empty string.  Returns ``None`` if no phrase matches.
    """
    if not text:
        return None

    normalized = text.strip().lower().rstrip(".!?,")

    # Check deactivation phrases first — some overlap with activation keywords.
    for phrase in DEACTIVATE_PHRASES:
        if phrase in normalized:
            return ("deactivate", "")

    # Check activation phrases: "<verb> <name> program"
    for verb in ACTIVATE_PHRASES:
        pattern = rf"\b{re.escape(verb)}\s+(.+?)\s+{re.escape(_PROGRAM_SUFFIX)}\b"
        match = re.search(pattern, normalized)
        if match:
            program_name = match.group(1).strip()
            if program_name:
                return ("activate", program_name)

    return None


def programs_enabled() -> bool:
    """Master switch — check env var."""
    return os.getenv("TANGO_PROGRAMS", "true").lower() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

async def load_programs(
    pool: asyncpg.Pool, persona_id: str
) -> list[dict[str, Any]]:
    """Load all active programs for a persona, ordered newest-first."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, base_persona_id, name, description,
                       system_prompt, active, created_at, updated_at
                FROM tango.programs
                WHERE base_persona_id = $1 AND active = TRUE
                ORDER BY created_at DESC
                """,
                persona_id,
            )
        return [
            {
                "id": str(row["id"]),
                "base_persona_id": row["base_persona_id"],
                "name": row["name"],
                "description": row["description"],
                "system_prompt": row["system_prompt"],
                "active": row["active"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    except Exception:
        logger.exception("Failed to load programs persona_id=%s", persona_id)
        return []


async def load_program_by_name(
    pool: asyncpg.Pool, persona_id: str, name: str
) -> dict[str, Any] | None:
    """Load a specific program by name (case-insensitive)."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, base_persona_id, name, description,
                       system_prompt, active, created_at, updated_at
                FROM tango.programs
                WHERE base_persona_id = $1
                  AND active = TRUE
                  AND LOWER(name) = LOWER($2)
                """,
                persona_id,
                name,
            )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "base_persona_id": row["base_persona_id"],
            "name": row["name"],
            "description": row["description"],
            "system_prompt": row["system_prompt"],
            "active": row["active"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    except Exception:
        logger.exception(
            "Failed to load program by name persona_id=%s name=%s",
            persona_id,
            name,
        )
        return None


async def save_program(
    pool: asyncpg.Pool,
    persona_id: str,
    name: str,
    description: str,
    system_prompt: str,
) -> str | None:
    """Create a new program. Returns the program ID or None on failure."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO tango.programs
                    (base_persona_id, name, description, system_prompt)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (base_persona_id, name) DO UPDATE
                    SET description = EXCLUDED.description,
                        system_prompt = EXCLUDED.system_prompt,
                        updated_at = NOW()
                RETURNING id
                """,
                persona_id,
                name,
                description,
                system_prompt,
            )
        program_id = str(row["id"]) if row else None
        logger.info(
            "Saved program persona_id=%s name=%s id=%s",
            persona_id,
            name,
            program_id,
        )
        return program_id
    except Exception:
        logger.exception(
            "Failed to save program persona_id=%s name=%s",
            persona_id,
            name,
        )
        return None


# ---------------------------------------------------------------------------
# Function tools for Control Mode
# ---------------------------------------------------------------------------

def build_program_tools(
    agent: Any, persona_id: str, pool: asyncpg.Pool
) -> list[Any]:
    """Build the function tools used for program management in Control Mode.

    Returns a list containing the ``create_program`` and ``list_programs``
    tools, which are bound to *agent* and *pool*/*persona_id*.
    """

    @function_tool
    async def create_program(
        name: str,
        description: str,
        system_prompt: str,
    ) -> str:
        """Create a new program for the current persona.

        A program is a derived profile that inherits the persona's voice, TTS,
        STT, and tools, but replaces the system prompt with a specialized one.
        The user can activate it later by saying "activate [name] program".

        Args:
            name: A short, memorable name for the program (e.g. "therapy",
                "coding", "study buddy"). Must be unique per persona.
            description: A brief human-readable description of what the program
                does and when to use it.
            system_prompt: The full system prompt for the program. This should
                be a complete persona definition that the LLM can follow.

        Returns:
            A confirmation message describing what was created.
        """
        name = name.strip()
        description = description.strip()
        system_prompt = system_prompt.strip()

        if not name:
            return "Program name cannot be empty."
        if not system_prompt:
            return "System prompt cannot be empty."

        program_id = await save_program(
            pool, persona_id, name, description, system_prompt
        )

        if program_id is None:
            return "Failed to save the program to the database."

        logger.info(
            "Program created via Control Mode persona_id=%s name=%s id=%s",
            persona_id,
            name,
            program_id,
        )
        return (
            f"Program '{name}' has been created successfully. "
            f"The user can activate it by saying 'activate {name} program'."
        )

    @function_tool
    async def list_programs() -> str:
        """List all available programs for the current persona.

        Returns a formatted list of programs that the user can activate
        by saying "activate [name] program".

        Returns:
            A formatted string listing all available programs.
        """
        programs = await load_programs(pool, persona_id)

        if not programs:
            return "No programs have been created yet for this persona."

        lines = [f"Available programs for {persona_id}:"]
        for prog in programs:
            desc = prog.get("description") or "No description"
            lines.append(f"- {prog['name']}: {desc}")
        lines.append(
            "\nTo activate a program, say 'activate [name] program'. "
            "To deactivate, say 'deactivate program' or 'return to default'."
        )
        return "\n".join(lines)

    return [create_program, list_programs]
