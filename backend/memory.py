from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import httpx

logger = logging.getLogger("project-tango.memory")

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000").rstrip("/")
MEMORY_MODEL = "local/qwen3-fast"
MAX_MEMORIES_PER_PERSONA = 10
MEMORY_MAX_AGE_DAYS = 90
CONTEXT_INJECTION_HEADER = "\n\n---\n[MEMORY - prior sessions with this user]\n"
CONTEXT_INJECTION_FOOTER = "\n[END MEMORY]\n---\n"
TRANSCRIPT_CHAR_LIMIT = 12000

SUMMARIZE_PROMPT = """\
You are a memory extractor for a voice AI assistant. Given a conversation transcript, \
extract the following in valid JSON with exactly these keys:

{
  "summary": "<2-3 sentence plain-language summary of what was discussed>",
  "user_profile_updates": ["<fact 1 about the user>", "<fact 2>"],
  "open_loops": ["<unresolved topic or follow-up item 1>", "<item 2>"],
  "emotional_tone": "<one word: positive|neutral|distressed|frustrated|reflective>",
  "key_topics": ["<topic 1>", "<topic 2>", "<topic 3>"]
}

Rules:
- user_profile_updates: stable facts about the user (name, job, location, relationships). Max 5 items.
- open_loops: things the user mentioned needing to do, follow up on, or revisit. Max 3 items.
- If any field has no content, return an empty list [] or empty string "".
- Output ONLY the JSON object. No prose, no markdown fences.

TRANSCRIPT:
{transcript}
"""


async def generate_session_memory(
    pool: asyncpg.Pool,
    session_id: str,
    persona: str,
    litellm_api_key: str,
) -> None:
    """Generate and store memory records for a completed session."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT speaker, text
                FROM tango.turns
                WHERE session_id = $1
                ORDER BY turn_index ASC, recorded_at ASC
                """,
                _session_uuid(session_id),
            )

        if not rows:
            logger.info("No transcript turns available for memory session_id=%s", session_id)
            return

        transcript = "\n".join(f"{row['speaker'].upper()}: {row['text']}" for row in rows)
        memory_data = await _call_litellm_summarize(transcript, litellm_api_key)
        if not memory_data:
            return

        await _write_memory_records(pool, session_id, persona, memory_data)
        logger.info("Wrote memory records session_id=%s persona=%s", session_id, persona)
    except Exception:
        logger.exception("Memory generation failed session_id=%s persona=%s", session_id, persona)


async def load_context_for_session(pool: asyncpg.Pool, persona: str) -> str:
    """Return formatted prior-session context for a persona, or an empty string."""
    try:
        resolution_filter = ""
        if await _has_resolution_columns(pool):
            resolution_filter = "AND (memory_type <> 'open_loop' OR resolved_at IS NULL)"

        query = f"""
            SELECT memory_type, content, created_at
            FROM tango.memories
            WHERE persona = $1
              AND (expires_at IS NULL OR expires_at > now())
              AND created_at >= now() - ($2::text::interval)
              {resolution_filter}
            ORDER BY created_at DESC
            LIMIT $3
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                query,
                persona,
                f"{MEMORY_MAX_AGE_DAYS} days",
                MAX_MEMORIES_PER_PERSONA,
            )

        if not rows:
            return ""

        now = datetime.now(UTC)
        lines = []
        for row in rows:
            created_at = row["created_at"]
            age_days = (now - created_at).days if created_at else 0
            content = _display_content(row["memory_type"], row["content"])
            lines.append(f"[{row['memory_type']} - {age_days}d ago] {content}")

        logger.info("Loaded %d memory records persona=%s", len(rows), persona)
        return CONTEXT_INJECTION_HEADER + "\n".join(lines) + CONTEXT_INJECTION_FOOTER
    except Exception:
        logger.exception("Memory context load failed persona=%s", persona)
        return ""


async def _call_litellm_summarize(transcript: str, api_key: str) -> dict[str, Any] | None:
    prompt = SUMMARIZE_PROMPT.format(transcript=transcript[:TRANSCRIPT_CHAR_LIMIT])
    payload = {
        "model": MEMORY_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{LITELLM_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"].strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _parse_json_object(content)

    if isinstance(parsed, dict):
        return parsed

    logger.warning("LiteLLM memory output was not a JSON object: %s", content[:240])
    return None


async def _write_memory_records(
    pool: asyncpg.Pool,
    session_id: str,
    persona: str,
    data: dict[str, Any],
) -> None:
    session_uuid = _session_uuid(session_id)
    records: list[tuple[str, uuid.UUID, str, str, str | None]] = []

    summary = _clean_string(data.get("summary"))
    if summary:
        summary_content = json.dumps(
            {
                "summary": summary,
                "key_topics": _clean_string_list(data.get("key_topics"), max_items=5),
                "emotional_tone": _clean_string(data.get("emotional_tone")) or "neutral",
            },
            ensure_ascii=True,
        )
        records.append((persona, session_uuid, "session_summary", summary_content, f"{MEMORY_MAX_AGE_DAYS} days"))

    for fact in _clean_string_list(data.get("user_profile_updates"), max_items=5):
        records.append((persona, session_uuid, "user_profile", fact, None))

    for loop in _clean_string_list(data.get("open_loops"), max_items=3):
        records.append((persona, session_uuid, "open_loop", loop, f"{MEMORY_MAX_AGE_DAYS} days"))

    if not records:
        logger.info("Memory extractor returned no storable records session_id=%s", session_id)
        return

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO tango.memories (persona, session_id, memory_type, content, expires_at)
            VALUES ($1, $2, $3, $4, CASE WHEN $5::text IS NULL THEN NULL ELSE now() + ($5::text::interval) END)
            """,
            records,
        )


async def _has_resolution_columns(pool: asyncpg.Pool) -> bool:
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'tango'
                      AND table_name = 'memories'
                      AND column_name = 'resolved_at'
                )
                """
            )
        )


def _display_content(memory_type: str, content: str) -> str:
    if memory_type != "session_summary":
        return content

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content

    if not isinstance(payload, dict):
        return content

    summary = _clean_string(payload.get("summary"))
    topics = _clean_string_list(payload.get("key_topics"), max_items=3)
    tone = _clean_string(payload.get("emotional_tone"))
    details = []
    if topics:
        details.append(f"topics: {', '.join(topics)}")
    if tone:
        details.append(f"tone: {tone}")
    return summary + (f" ({'; '.join(details)})" if summary and details else "")


def _parse_json_object(content: str) -> Any:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_string_list(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []

    cleaned = []
    for item in value:
        text = _clean_string(item)
        if text:
            cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned


def _session_uuid(session_id: str | uuid.UUID) -> uuid.UUID:
    return session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(session_id)
