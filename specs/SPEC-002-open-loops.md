# SPEC-002 — Open Loops & Proactive Follow-Up
**Project:** Project Tango
**Priority:** 2 (Phase 1 — in-app continuity; Phase 3 — push delivery)
**Status:** Ready for implementation
**Spec Author:** WRITER Agent — June 27, 2026
**Codebase Ref:** `theonlygeranium/Project-Tango` @ `fdc9144` (v1.0-stable)
**Estimated Effort:** 2–3 days (Phase 1 scope only)
**Dependency:** SPEC-001 must be merged first (`tango.memories` table required)
**Risk Level:** Low — primarily additive; one new API endpoint and one frontend panel

---

## 1. Problem Statement

When a user ends a Tango session, any unresolved topics, pending intentions, or follow-up items ("I should research that", "remind me to call my doctor", "I want to revisit this with Damian") disappear completely. The next session has no awareness of what was left open.

Open loops are the connective tissue between sessions. Without them, Tango is a series of disconnected conversations rather than an ongoing relationship. With them, the persona can open a new session with: *"Last time we were talking about your sleep issues — did anything change?"*

**Phase 1 scope (this spec):** In-app open loop display on the home screen and agent voice reference at session start.
**Phase 3 scope (deferred):** PWA push notification delivery, time-triggered reminders.

---

## 2. Architecture Overview

```
Session End
    │  generate_session_memory() runs (SPEC-001)
    │  open_loops extracted from transcript by LLM
    ▼
tango.memories  (memory_type = 'open_loop')   ← already defined in SPEC-001
    │
    │  On next app load (frontend):
    ▼
GET /api/memory/open-loops?persona=<key>       ← NEW endpoint
    │  returns list of unresolved open loops
    ▼
LoopBanner component (frontend)               ← NEW component
    │  displays on home screen above persona grid
    │
    │  User dismisses → PATCH /api/memory/open-loops/<id>/resolve
    │
    │  User starts session → agent system prompt includes open loops
    ▼
AgentSession → persona greets with loop context (via SPEC-001 injection)
```

---

## 3. Backend Changes

### 3.1 Update `tango.memories` table

SPEC-001 creates `tango.memories` with `memory_type CHECK ('session_summary', 'user_profile', 'open_loop')`. This spec depends on that table being live.

Add one column to track resolution state. Create migration `003_open_loop_resolution.sql`:

```sql
-- Migration: 003_open_loop_resolution
-- Adds resolution tracking to open loop memory records

ALTER TABLE tango.memories
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS resolution_note TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_memories_unresolved
    ON tango.memories (persona, memory_type, created_at DESC)
    WHERE resolved_at IS NULL AND memory_type = 'open_loop';
```

### 3.2 New API endpoints in `backend/main.py`

Add the following FastAPI routes in the `/api/memory/` prefix group:

```python
# ─── Open Loop Endpoints ────────────────────────────────────────────────────

@app.get("/api/memory/open-loops")
async def get_open_loops(persona: str | None = None):
    """
    Returns unresolved open loop memory records.
    If persona is provided, filters to that persona only.
    Used by the frontend LoopBanner component on page load.
    """
    async with db_pool.acquire() as conn:
        if persona:
            rows = await conn.fetch(
                """
                SELECT id, persona, content, created_at
                FROM tango.memories
                WHERE memory_type = 'open_loop'
                  AND resolved_at IS NULL
                  AND (expires_at IS NULL OR expires_at > now())
                  AND persona = $1
                ORDER BY created_at DESC
                LIMIT 5
                """,
                persona,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, persona, content, created_at
                FROM tango.memories
                WHERE memory_type = 'open_loop'
                  AND resolved_at IS NULL
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY created_at DESC
                LIMIT 10
                """,
            )

    return {
        "open_loops": [
            {
                "id": str(r["id"]),
                "persona": r["persona"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@app.patch("/api/memory/open-loops/{loop_id}/resolve")
async def resolve_open_loop(loop_id: str, note: str | None = None):
    """
    Marks an open loop as resolved.
    Called when the user dismisses a loop banner or the agent explicitly closes it.
    """
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE tango.memories
            SET resolved_at = now(),
                resolution_note = $2
            WHERE id = $1
              AND memory_type = 'open_loop'
              AND resolved_at IS NULL
            """,
            loop_id,
            note,
        )

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Open loop not found or already resolved")

    return {"status": "resolved", "id": loop_id}
```

---

## 4. Frontend Changes

### 4.1 New TypeScript type: `OpenLoop`

Add to `frontend/lib/types.ts` (create if missing):

```typescript
export interface OpenLoop {
  id: string;
  persona: string;
  content: string;
  created_at: string;
}
```

### 4.2 New hook: `useOpenLoops.ts`

Create `frontend/hooks/useOpenLoops.ts`:

```typescript
"use client";
import { useState, useEffect } from "react";
import type { OpenLoop } from "@/lib/types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "https://tango-api.schubert.life";

export function useOpenLoops(persona?: string) {
  const [loops, setLoops] = useState<OpenLoop[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const url = persona
      ? `${BACKEND_URL}/api/memory/open-loops?persona=${encodeURIComponent(persona)}`
      : `${BACKEND_URL}/api/memory/open-loops`;

    fetch(url)
      .then((r) => r.json())
      .then((data) => setLoops(data.open_loops ?? []))
      .catch(() => setLoops([]))  // fail silently — loops are optional UX
      .finally(() => setLoading(false));
  }, [persona]);

  const resolveLoop = async (id: string) => {
    setLoops((prev) => prev.filter((l) => l.id !== id));  // optimistic remove
    await fetch(`${BACKEND_URL}/api/memory/open-loops/${id}/resolve`, {
      method: "PATCH",
    }).catch(() => {});  // fail silently
  };

  return { loops, loading, resolveLoop };
}
```

### 4.3 New component: `LoopBanner.tsx`

Create `frontend/components/LoopBanner.tsx`:

```tsx
"use client";
import { useOpenLoops } from "@/hooks/useOpenLoops";

/**
 * LoopBanner — displays unresolved open loops above the persona grid.
 * Shown only when loops exist. Each loop is dismissible.
 * Color: amber-400 accent (consistent with persona border palette).
 */
export function LoopBanner() {
  const { loops, resolveLoop } = useOpenLoops();

  if (loops.length === 0) return null;

  return (
    <div
      className="w-full max-w-2xl mx-auto mb-6 px-4"
      aria-label="Unresolved topics from previous sessions"
    >
      <div className="rounded-xl border border-amber-400/30 bg-amber-400/5 px-4 py-3 space-y-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-amber-400 mb-1">
          Picking up where you left off
        </p>
        {loops.slice(0, 3).map((loop) => (
          <div key={loop.id} className="flex items-start justify-between gap-3">
            <p className="text-sm text-white/80 leading-snug">{loop.content}</p>
            <button
              onClick={() => resolveLoop(loop.id)}
              aria-label={`Dismiss: ${loop.content}`}
              className="shrink-0 text-white/30 hover:text-white/70 transition-colors text-lg leading-none"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
```

### 4.4 Mount `LoopBanner` in home page component

Locate the component that renders the persona selector grid. Import and place `LoopBanner` immediately above the grid:

```tsx
import { LoopBanner } from "@/components/LoopBanner";

// Inside your JSX, above the persona grid:
<LoopBanner />
<PersonaGrid ... />
```

### 4.5 Voice reference at session start

Handled automatically by SPEC-001's context injection. When `load_context_for_session()` returns open loop records, they are appended to the system prompt. Add the following to `backend/personas.py` to explicitly guide persona greeting:

```python
OPEN_LOOP_INSTRUCTION = (
    "\n\nIf the [MEMORY] section includes any open_loop items, "
    "briefly acknowledge the most relevant one in your opening greeting — "
    "naturally, as a friend would, not as a formal reminder. "
    "Keep it to one sentence. Example: 'Oh, did you ever sort out that thing with your job interview?'"
)
```

Apply `OPEN_LOOP_INSTRUCTION` to therapy, general-info, and meditation personas. Do NOT apply to pinoy-pride personas — Tita Baby and Mama Lulu should reference loops organically in their Taglish style.

---

## 5. Codex Execution Order

1. **Verify SPEC-001 is deployed** — `tango.memories` table must exist:
   ```bash
   psql -U tango_user -d postgres -c "\d tango.memories"
   ```

2. **Run migration 003:**
   ```bash
   psql -U tango_user -d postgres \
     -f backend/migrations/003_open_loop_resolution.sql
   ```

3. **Add the two new endpoints to `backend/main.py`** (Section 3.2).

4. **Compile check:**
   ```bash
   python3 -m py_compile backend/main.py && echo "OK"
   ```

5. **Test the endpoint:**
   ```bash
   curl -s https://tango-api.schubert.life/api/memory/open-loops | jq .
   # Expected: {"open_loops": []}
   ```

6. **Create frontend files:**
   - `frontend/lib/types.ts` — add `OpenLoop` type
   - `frontend/hooks/useOpenLoops.ts` — new hook
   - `frontend/components/LoopBanner.tsx` — new component

7. **Mount `LoopBanner` in home page component.**

8. **Update `backend/personas.py`** — add `OPEN_LOOP_INSTRUCTION` to applicable personas.

9. **Build and deploy:**
   ```bash
   sudo systemctl restart tango-backend
   curl -s https://tango-api.schubert.life/healthz

   cd /opt/Project-Tango/frontend
   sudo -u z121532 npm run build
   sudo -u z121532 cp -r .next/static .next/standalone/.next/static
   sudo -u z121532 cp -r public .next/standalone/public
   sudo systemctl restart tango-web
   ```

10. **Generate test data:** Start a session with any persona. Have a conversation that includes an open-ended topic. End the session. Wait ~30s. Reload the home page and verify `LoopBanner` appears.

11. **Dismiss test:** Click `×` on a loop banner. Verify it disappears and PATCH returns `{"status": "resolved"}`.

12. **Commit:**
    ```
    git add backend/migrations/003_open_loop_resolution.sql \
            backend/main.py backend/personas.py \
            frontend/lib/types.ts \
            frontend/hooks/useOpenLoops.ts \
            frontend/components/LoopBanner.tsx \
            frontend/app/page.tsx
    git commit -m "feat(memory): add open loops banner and agent voice reference at session start"
    git push origin main
    ```

---

## 6. Acceptance Criteria

| ID | Criterion | How to Verify |
|---|---|---|
| AC-001 | `resolved_at` column exists on `tango.memories` | `\d tango.memories` |
| AC-002 | `GET /api/memory/open-loops` returns open loops for a persona | curl after test session |
| AC-003 | `PATCH .../resolve` marks loop as resolved, removes from API response | curl PATCH, then re-GET |
| AC-004 | `LoopBanner` renders on home page when loops exist | Manual browser test |
| AC-005 | `LoopBanner` is absent when no loops exist | Fresh user / resolved state |
| AC-006 | `×` dismiss button calls resolve endpoint and removes item from UI | Click test |
| AC-007 | Agent references an open loop in its greeting on subsequent session | Voice test |
| AC-008 | Backend restart does not clear loops — they persist across restarts | Restart + query |
| AC-009 | No console errors or layout shifts caused by `LoopBanner` | Browser devtools |
| AC-010 | `LoopBanner` is accessible: correct ARIA labels, keyboard dismissible | Tab + Enter test |

---

## 7. Phase 3 Deferred: Push Notifications

This spec intentionally excludes push notification delivery. When Phase 3 is scoped:

1. Register service worker and request notification permission via the existing `site.webmanifest` + PWA setup (commit `ddc8368`)
2. Add `tango.scheduled_loops` table with `notify_at TIMESTAMPTZ`
3. Add a background cron task (`apscheduler`) that checks for due notifications and sends via Web Push API (`pywebpush`)
4. Frontend service worker handles `push` event and displays system notification

Note: PWA push on iOS Safari requires iOS 16.4+ and home-screen installation.

---

## 8. References

- Deepgram `UpdateListen` for dynamic keyterm updates mid-session
- ElevenLabs `system__conversation_history` dynamic variable for agent context
- ElevenLabs Flash v2.5 multi-context WebSocket for interruptible speech
- Enhancement Review P2 analysis — `Project Tango_ENHANCEMENT_REVIEW_2026-06-28.md`
- SPEC-001: Real Memory Layer (required dependency)
