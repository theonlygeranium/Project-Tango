# SPEC-001 — Real Memory Layer
**Project:** Project Tango
**Priority:** 1 (Phase 1)
**Status:** Ready for implementation
**Spec Author:** WRITER Agent — June 27, 2026
**Codebase Ref:** `theonlygeranium/Project-Tango` @ `fdc9144` (v1.0-stable)
**Estimated Effort:** 3–4 days
**Risk Level:** Low — additive only, no existing code modified until final injection step

---

## 1. Problem Statement

Every Project Tango session starts from zero. The agent has no memory of prior conversations, cannot build on what it learned about the user, and cannot reference previous topics, commitments, or emotional context. This makes every session feel like a first meeting, even with the same persona after dozens of conversations.

The raw material already exists: `tango.sessions` and `tango.turns` in PostgreSQL 18 on Schubert capture every conversation in full. What is missing is:

1. A **post-session summarizer** that distills each conversation into a structured memory record
2. A **`tango.memories` table** to store those records durably
3. A **context injector** that retrieves relevant memories at session start and appends them to the persona's system prompt before `session.start()` is called

This spec defines the complete build for all three components.

---

## 2. Architecture Overview

```
Session End
    │  flush_history() called in main.py
    ▼
generate_session_memory()          ← NEW async task
    │  calls LiteLLM (localhost:4000)
    │  structured JSON output
    ▼
tango.memories table               ← NEW PostgreSQL table
    │
    │  At next session start:
    ▼
load_context_for_session()         ← NEW function in memory.py
    │  queries tango.memories by persona
    │  returns formatted context string
    ▼
entrypoint() in main.py
    │  appends context to persona.instructions
    ▼
session.start() — agent now has prior context
```

---

## 3. Database Schema

### 3.1 Migration: `tango.memories`

Create file: `backend/migrations/002_create_memories.sql`

```sql
-- Migration: 002_create_memories
-- Creates the per-persona memory table for Project Tango
-- Run as: psql -U tango_user -d postgres -f 002_create_memories.sql

CREATE TABLE IF NOT EXISTS tango.memories (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    persona         TEXT        NOT NULL,
    session_id      UUID        REFERENCES tango.sessions(id) ON DELETE SET NULL,
    memory_type     TEXT        NOT NULL CHECK (memory_type IN ('session_summary', 'user_profile', 'open_loop')),
    content         TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ,                     -- NULL = permanent
    embedding_vec   vector(1536)                     -- reserved for future pgvector search
);

CREATE INDEX IF NOT EXISTS idx_memories_persona
    ON tango.memories (persona, memory_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_session
    ON tango.memories (session_id);
```

> **Note:** The `vector` column requires `pgvector` extension. If pgvector is not installed on Schubert's PostgreSQL 18, declare the column as `TEXT` (serialized JSON) for Phase 1 and migrate to `vector` when pgvector is available. Use `ALTER TABLE tango.memories ADD COLUMN embedding_vec TEXT;` as the fallback.

### 3.2 Check pgvector availability on Schubert

Before running the migration, verify:
```bash
psql -U postgres -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```
- If found: use `vector(1536)` column type as written
- If not found: replace `vector(1536)` with `TEXT` in the migration and add a `TODO: migrate to vector` comment

---

## 4. New File: `backend/memory.py`

Create `backend/memory.py`. This module owns all memory read/write logic.

```python
"""
memory.py — Project Tango session memory layer.

Responsibilities:
- Generate a structured memory record from a completed session's transcript
- Store memory records in tango.memories
- Retrieve relevant context for a new session start
- Inject context into a persona's system prompt string

Does NOT touch: main.py AgentSession lifecycle, personas.py, history.py turn writes.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

LITELLM_BASE_URL = "http://localhost:4000"
MEMORY_MODEL = "local/qwen3-fast"          # use fast local model for summarization
MAX_MEMORIES_PER_PERSONA = 10              # retrieved per session start
MEMORY_MAX_AGE_DAYS = 90                   # auto-expire old memories
CONTEXT_INJECTION_HEADER = (
    "\n\n---\n[MEMORY — prior sessions with this user]\n"
)
CONTEXT_INJECTION_FOOTER = "\n[END MEMORY]\n---\n"


# ---------------------------------------------------------------------------
# SUMMARIZATION PROMPT
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# CORE FUNCTIONS
# ---------------------------------------------------------------------------

async def generate_session_memory(
    pool: asyncpg.Pool,
    session_id: str,
    persona: str,
    litellm_api_key: str,
) -> None:
    """
    Called after flush_history() completes. Fetches the session transcript,
    runs LiteLLM summarization, and writes memory records to tango.memories.

    This runs as a fire-and-forget background task — it must not raise exceptions
    that bubble up to the call site.
    """
    try:
        # 1. Fetch transcript from tango.turns
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content
                FROM tango.turns
                WHERE session_id = $1
                ORDER BY created_at ASC
                """,
                session_id,
            )

        if not rows:
            logger.info("memory: no turns for session %s — skipping", session_id)
            return

        transcript = "\n".join(
            f"{r['role'].upper()}: {r['content']}" for r in rows
        )

        # 2. Call LiteLLM for structured summarization
        memory_data = await _call_litellm_summarize(transcript, litellm_api_key)
        if not memory_data:
            return

        # 3. Write memory records to tango.memories
        await _write_memory_records(pool, session_id, persona, memory_data)
        logger.info("memory: wrote memory records for session %s/%s", persona, session_id)

    except Exception as exc:  # noqa: BLE001
        # Never let memory failure break the call teardown
        logger.error("memory: generate_session_memory failed: %s", exc, exc_info=True)


async def load_context_for_session(
    pool: asyncpg.Pool,
    persona: str,
) -> str:
    """
    Retrieves the most recent memories for this persona and returns a
    formatted context string ready to be appended to the system prompt.

    Returns an empty string if no memories exist (first session behaviour
    is unaffected).
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT memory_type, content, created_at
                FROM tango.memories
                WHERE persona = $1
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY created_at DESC
                LIMIT $2
                """,
                persona,
                MAX_MEMORIES_PER_PERSONA,
            )

        if not rows:
            return ""

        lines = []
        for row in rows:
            age_days = (datetime.now(timezone.utc) - row["created_at"]).days
            lines.append(f"[{row['memory_type']} — {age_days}d ago] {row['content']}")

        context = CONTEXT_INJECTION_HEADER + "\n".join(lines) + CONTEXT_INJECTION_FOOTER
        logger.info("memory: injected %d memory records for persona %s", len(rows), persona)
        return context

    except Exception as exc:  # noqa: BLE001
        logger.error("memory: load_context_for_session failed: %s", exc, exc_info=True)
        return ""  # fail open — session proceeds without memory


# ---------------------------------------------------------------------------
# PRIVATE HELPERS
# ---------------------------------------------------------------------------

async def _call_litellm_summarize(
    transcript: str,
    api_key: str,
) -> Optional[dict]:
    """Calls LiteLLM with the summarization prompt; returns parsed dict or None."""
    prompt = SUMMARIZE_PROMPT.format(transcript=transcript[:12000])  # token guard

    payload = {
        "model": MEMORY_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{LITELLM_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("memory: LLM output was not valid JSON: %s", raw[:200])
        return None


async def _write_memory_records(
    pool: asyncpg.Pool,
    session_id: str,
    persona: str,
    data: dict,
) -> None:
    """Writes structured memory data to tango.memories."""
    records = []

    # Session summary (always written)
    if data.get("summary"):
        summary_content = json.dumps({
            "summary": data["summary"],
            "key_topics": data.get("key_topics", []),
            "emotional_tone": data.get("emotional_tone", "neutral"),
        })
        records.append((persona, session_id, "session_summary", summary_content))

    # User profile updates (one record per fact)
    for fact in data.get("user_profile_updates", []):
        if fact.strip():
            records.append((persona, session_id, "user_profile", fact.strip()))

    # Open loops (one record per item)
    for loop in data.get("open_loops", []):
        if loop.strip():
            records.append((persona, session_id, "open_loop", loop.strip()))

    if not records:
        return

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO tango.memories (persona, session_id, memory_type, content)
            VALUES ($1, $2, $3, $4)
            """,
            records,
        )
```

---

## 5. Modifications to `backend/main.py`

### 5.1 Import memory module

Add to the import block at the top of `main.py`:

```python
# Add after existing imports
from memory import generate_session_memory, load_context_for_session
```

### 5.2 Inject context in `entrypoint()`

Locate the `entrypoint()` function. Find the line where `persona.instructions` is used before `session.start()`. Insert the context load **before** `AgentSession` is created:

```python
async def entrypoint(ctx: JobContext) -> None:
    # ... existing room metadata parsing and persona loading ...

    # NEW: Load prior context for this persona
    prior_context = await load_context_for_session(db_pool, persona.key)
    if prior_context:
        augmented_instructions = persona.instructions + prior_context
    else:
        augmented_instructions = persona.instructions

    session = AgentSession(
        stt=_build_stt(persona),
        llm=_build_llm(persona),
        tts=_build_tts(persona),
        turn_handling=_turn_handling_for_session(persona),
        use_tts_aligned_transcript=False,
    )

    agent = TangoAgent(
        instructions=augmented_instructions,  # ← use augmented, not persona.instructions
        persona=persona,
    )

    # ... rest of entrypoint unchanged ...
```

### 5.3 Trigger memory generation after session close

Locate the `flush_history()` call or the `on_session_end` / `shutdown` hook in `main.py`. After the existing history flush completes, fire the memory task:

```python
# After flush_history() or equivalent teardown:
asyncio.create_task(
    generate_session_memory(
        pool=db_pool,
        session_id=current_session_id,
        persona=persona.key,
        litellm_api_key=os.environ["LITELLM_MASTER_KEY"],
    )
)
```

> **Critical:** Use `asyncio.create_task()` — this must fire-and-forget. The session teardown must not await the memory generation task. A failure in memory generation must never interrupt the session close path.

---

## 6. Environment Variables

No new environment variables required. `LITELLM_MASTER_KEY` and `DATABASE_URL` are already in `backend/.env`.

---

## 7. Dependencies

No new Python packages required. All dependencies are already in `requirements.txt`:
- `asyncpg` — PostgreSQL async driver (already present)
- `httpx` — async HTTP client for LiteLLM calls (already present)

---

## 8. Codex Execution Order

Execute these steps **in order**. Do not skip or reorder.

1. **Run migration on Schubert:**
   ```bash
   psql -U tango_user -d postgres -f backend/migrations/002_create_memories.sql
   ```
   Verify: `psql -U tango_user -d postgres -c "\d tango.memories"`

2. **Create `backend/memory.py`** with the full content in Section 4 above.

3. **Compile check:**
   ```bash
   python3 -m py_compile backend/memory.py
   echo "compile OK"
   ```

4. **Modify `backend/main.py`** per Section 5 (import, injection, task fire).

5. **Compile check again:**
   ```bash
   python3 -m py_compile backend/main.py
   echo "compile OK"
   ```

6. **Deploy to Schubert:**
   ```bash
   sudo systemctl restart tango-backend
   systemctl is-active tango-backend
   curl -s https://tango-api.schubert.life/healthz
   ```

7. **Run a test session** with any English persona. End the session normally.

8. **Verify memory write:**
   ```bash
   psql -U tango_user -d postgres -c \
     "SELECT persona, memory_type, left(content, 80) FROM tango.memories ORDER BY created_at DESC LIMIT 5;"
   ```
   Expected: at least one `session_summary` row for the persona used in the test.

9. **Run a second test session** with the same persona. Verify the agent references or acknowledges context from the first session.

10. **Commit:**
    ```
    git add backend/migrations/002_create_memories.sql backend/memory.py backend/main.py
    git commit -m "feat(memory): add three-tier memory layer with post-session summarizer and context injection"
    git push origin main
    ```

---

## 9. Acceptance Criteria

| ID | Criterion | How to Verify |
|---|---|---|
| AC-001 | `tango.memories` table exists with correct schema | `\d tango.memories` in psql |
| AC-002 | After session end, memory records are written within 30s | Query `tango.memories` after session |
| AC-003 | Memory generation failure does not crash the backend | Kill LiteLLM mid-session; backend stays active |
| AC-004 | Second session with same persona has prior context in system prompt | Check `tango-backend` logs for "injected N memory records" |
| AC-005 | First-ever session for a persona starts normally with no context injection | Test with a fresh persona that has no memories |
| AC-006 | `load_context_for_session` returns `""` on DB error (fail-open) | Temporarily revoke DB access; session still starts |

---

## 10. Per-Persona Behaviour Notes

| Persona | Context Injection Behaviour |
|---|---|
| Damian (therapy) | Inject: session_summary + emotional_tone + open_loops. Exclude if retention_policy=none |
| Nathaniel (meditation) | Inject: session_summary only. Emotional history is sensitive — limit to key_topics |
| Jeremiah | Inject: user_profile_updates + session_summary. User facts are most valuable |
| Chris | Inject: session_summary + key_topics. Conversational continuity is primary value |
| Tita Baby / Mama Lulu | Inject: session_summary. Include open_loops for family/life advice continuity |

---

## 11. References

- Deepgram Flux `Configure` for dynamic keyterm injection mid-stream
- ElevenLabs `system__conversation_history` dynamic variable
- Deepgram `UpdateListen` for live session configuration
- Enhancement Review P1 analysis — `Project Tango_ENHANCEMENT_REVIEW_2026-06-28.md`
- Current DB schema: `docs/architecture.md` (Section: Database Schema)
