# Proposed updates to AGENTS.md (needs owner approval)

**Date:** 2026-10-05
**Proposed by:** Claude Code, as part of the voice pipeline review (finding F10)
**Status:** Proposed. Not applied.

`AGENTS.md` may only be changed by the human owner (AGENTS.md §4). These edits would bring it in line
with the code after the 2026-10-05 fixes. Each item gives the current text, the proposed text, and why.
Apply any subset; the rest of the repository does not depend on these edits.

## 1. §3.1 Critical Framework Rules — STT plugin row

Current:

```
| STT plugin | `deepgram.STT(model="flux-general-en", ...)` | `DeepgramSTTService` |
```

Proposed:

```
| STT plugin | `deepgram.STTv2(model="flux-general-en", ...)` (Flux); `deepgram.STT(model="nova-3", language="tl", ...)` (Tagalog) | `DeepgramSTTService` |
```

Why: Flux is served by the plugin's `STTv2` class (the `/v2/listen` endpoint). `deepgram.STT` with a Flux
model does not work on the current plugin. The code has used `STTv2` since before this review.

## 2. §3.3 STT Model Selection — add turn detection

Append after the table:

```
English personas use `turn_detection="stt"` so Flux's EndOfTurn ends the user turn and the
per-persona `eot_threshold` / `eot_timeout_ms` / `eager_eot_threshold` apply (ADR-023).
`inference.TurnDetector()` makes LiveKit ignore Flux end-of-turn events; it is only a rollback
(`TANGO_TURN_DETECTION=audio`). Tagalog personas use `turn_detection="vad"` with
`min_delay=0.7` and Nova-3 `endpointing_ms=300`.
```

Why: from 2026-08-16 to 2026-10-05 the code used `inference.TurnDetector()`, which silently disabled the
Flux tuning in ADR-002 and ADR-024 (formerly ADR-011). Stating the rule here prevents a repeat.

## 3. §3.4 TTS Configuration — add three rules

Append:

```
- Wrap TTS in `tts.FallbackAdapter([elevenlabs, deepgram_aura])`. Do not hand-write a fallback:
  `AgentSession` uses `stream()`, and a wrapper that forwards `stream()` to the primary never fails over.
- Keep ElevenLabs `style` at 0 for every persona (ElevenLabs: non-zero style adds latency).
- Function tools run on the same event loop that pushes TTS audio. Use `httpx.AsyncClient` or
  `asyncio.to_thread`; never a synchronous HTTP client inside an async tool.
```

Why: each rule corresponds to a production defect fixed on 2026-10-05 (review F2, F7, F11).

## 4. §3.4 — ADR-004 wording

Current: "ADR-004's aligned-transcript flag alone does **not** prevent mid-speech pauses"

Proposed: add "(see ADR-028, formerly ADR-012)" after it.

Why: five Tango ADRs were renumbered on 2026-10-05 (index: `docs/decisions/README.md`).

## 5. §4 Repository Structure

The tree lists `backend/main.py` and `backend/history.py` only. Proposed additions under `backend/`:

```
│   ├── jarvis_agent.py         ← Agent subclass: instructions, tools, on_user_turn_completed
│   ├── personas.py             ← Persona definitions (voice, STT/TTS, turn tuning) — source of truth
│   ├── control_mode.py, programs.py, meditation_tools.py, transcription_tools.py
│   ├── search_tools.py, wiki_tools.py, mintlify_tools.py, mcp_tools.py, vision_context.py
│   └── tests/                  ← pytest suite, run in CI (test-gate.yml backend-tests)
```

and under `docs/`: `reviews/` and `decisions/README.md` (ADR index, next free number).

## 6. §7 Stable Versioning

Current: "Current stable baseline: **`v1.0-stable`** → commit `fdc9144`"

Proposed: "Current stable baseline: **`v2.0-stable`** (see `REVERT.md`)"

Why: `REVERT.md` already documents `v2.0-stable` as the current baseline. Note that this checkout
has no git tags; confirm the tag exists on the remote before relying on it.

## 7. §3.5 Agent Dispatch — no change proposed here

Moving dispatch into the participant token (review F6) would change this section and supersede ADR-006.
It is a separate decision for the owner and is not part of these documentation fixes.
