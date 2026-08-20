# ADR: DeepGram Flux Eager End-of-Turn

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Project Tango's v1 voice pipeline uses DeepGram Flux STT with LiveKit's audio-based
`TurnDetector` for end-of-turn detection. While this provides ~260ms end-of-turn detection
at p50, the agent still waits for the full `EndOfTurn` event before beginning LLM generation.

DeepGram's Flux model supports an `EagerEndOfTurn` event that fires at medium transcript
confidence — before the user finishes speaking. When combined with LiveKit's existing
`preemptive_generation` flag (already enabled in Tango), this allows the agent to begin
speculative LLM generation on partial transcripts, cutting hundreds of milliseconds from
end-to-end response time.

The `eager_eot_threshold` parameter (range 0.3–0.9) controls when `EagerEndOfTurn` fires.
Lower values trigger earlier but with more false starts. If the user continues speaking,
a `TurnResumed` event cancels the speculative draft.

## Decision

Enable `eager_eot_threshold` per-persona, tuned to each persona's conversational style:

| Persona | Threshold | Rationale |
|---------|-----------|-----------|
| therapy (Damian) | None (disabled) | Empathetic listener; interruptions feel rude |
| general-info (Chris) | 0.6 | Conversational Q&A; balanced speed/accuracy |
| jeremiah | 0.6 | Conversational, direct; balanced |
| jeremiah-v2 | 0.55 | Witty, fast-paced; most aggressive |
| jacob | 0.65 | Methodical; conservative |
| meditation (Nathaniel) | None (disabled) | Meditative, unhurried; interruptions break flow |
| mama-lulu | None | Tagalog; uses Nova-3 (no eager EOT support) |
| pinoy-pride | None | Tagalog; uses Nova-3 (no eager EOT support) |

Add an optional global override (`TANGO_EAGER_EOT_THRESHOLD`) that supersedes per-persona
values when set, allowing operators to tune or disable eager EOT without code changes.

## Rationale

- Therapy and meditation personas prioritize presence over speed; a speculative
  interruption would feel jarring and break the therapeutic/meditative atmosphere.
- Jeremiah V2's fast-paced wit benefits from the most aggressive threshold (0.55),
  as his persona is designed for snappy, irreverent exchanges.
- Jacob's methodical style warrants a conservative threshold (0.65) to avoid
  premature responses during thoughtful pauses.
- Tagalog personas cannot use eager EOT because Nova-3 does not support it.
- The global override provides operational flexibility: if LLM cost becomes a concern,
  operators can disable eager EOT globally without a code deploy.

## Alternatives Considered

1. **Global eager EOT for all English personas** — rejected because therapy and
   meditation personas would suffer from premature interruptions.
2. **Very low threshold (0.3) for all conversational personas** — rejected because
   the 50–70% increase in LLM calls from false starts would be excessive for personas
   that don't benefit from maximum aggressiveness.
3. **Dynamic threshold tuning based on conversation context** — deferred; would require
   real-time confidence metrics and adds complexity without clear benefit over static tuning.
4. **No eager EOT (status quo)** — rejected because the latency improvement is the
   highest-impact optimization in the v2 spec and is easily tunable/revertible.

## Consequences

- **Positive:** Conversational English personas (Chris, Jeremiah, Jeremiah V2, Jacob)
  will respond noticeably faster, with hundreds of milliseconds saved on each turn.
- **Negative:** LLM calls increase by ~50–70% for personas with eager EOT enabled,
  because speculative drafts are discarded when `TurnResumed` fires. This is an
  acceptable trade-off for the latency improvement.
- **Operational:** The `TANGO_EAGER_EOT_THRESHOLD` env var allows global override
  without code changes. Per-persona values can be adjusted in `personas.py`.

## References

- SPEC-005: Project Tango v2 — Voice Pipeline Optimization
- ADR-002: Deepgram Flux STT (2026-06-26)
- DeepGram Flux documentation (Context7, August 2026)
- LiveKit Agents SDK `preemptive_generation` configuration
