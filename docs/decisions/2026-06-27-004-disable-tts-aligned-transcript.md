# ADR-004: Disable `use_tts_aligned_transcript` in AgentSession

**Date:** 2026-06-27
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Users reported voice agents pausing mid-speech. Backend logs showed `_SegmentSynchronizerImpl` warnings indicating race conditions between ElevenLabs audio streaming events and the LiveKit Agents alignment metadata pipeline. The root cause was `use_tts_aligned_transcript=True` (the default), which waits for ElevenLabs word-timing alignment metadata before advancing the transcript.

## Decision

Set `use_tts_aligned_transcript=False` in the `AgentSession` constructor for all personas.

## Rationale

- Eliminates the `_SegmentSynchronizerImpl` race condition entirely
- Project Tango does not use word-level transcript highlighting
- User-perceived audio quality improved immediately — no more mid-speech pauses
- Recommended mitigation from LiveKit Agents documentation for ElevenLabs streaming integrations

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Keep enabled with increased timeout | Doesn't eliminate the race — changes when it manifests |
| Switch TTS provider | ElevenLabs Flash v2.5 is best-quality available |
| Downgrade ElevenLabs plugin | Issue exists across plugin versions |

## Consequences

- Word-level transcript highlighting unavailable (unused feature)
- Sentence-level transcripts still work correctly
- All personas benefit — no per-persona conditional needed
- Must be preserved in `backend/main.py` — do not re-enable without testing
