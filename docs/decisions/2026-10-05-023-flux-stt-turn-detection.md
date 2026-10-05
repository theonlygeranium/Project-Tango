# ADR: Restore Deepgram Flux as the turn-detection source

**Date:** 2026-10-05
**Status:** Accepted
**Decided by:** Claude Code (on request of the human owner)

## Context

ADR-002 chose Deepgram Flux for English personas because of its built-in
end-of-turn model. ADR-011 then tuned `eot_threshold`, `eot_timeout_ms` and
`eager_eot_threshold` per persona (for example 4.5 s and 5.5 s timeouts for
Damian and Nathaniel, so reflective pauses are not cut off).

Commit `48dd55c` (2026-08-16) switched `AgentSession` to
`turn_handling={"turn_detection": inference.TurnDetector()}`, the LiveKit
Inference audio turn model. The aim was to silence the warning
`stt end of speech received while vad is still in a speech segment`.

In LiveKit Agents, `AudioRecognition` only consumes STT `END_OF_SPEECH` and
`START_OF_SPEECH` events when `turn_detection == "stt"`. With a
`TurnDetector` instance the mode is `None`, so Flux's end-of-turn events are
discarded. Turn boundaries were therefore decided by Silero VAD
(`min_silence_duration=0.3`) plus the audio model. None of the per-persona
Flux settings had any effect. Because `48dd55c` predates ADR-011, eager
end-of-turn was never in effect as designed. The warning went away because
Flux was ignored, not because a race was fixed. In `"stt"` mode that warning
is expected: LiveKit flushes VAD so that a VAD start-of-speech can correct a
premature Flux end-of-turn.

LiveKit's documentation gives this configuration for Flux:

```python
AgentSession(
    turn_handling=TurnHandlingOptions(turn_detection="stt"),
    stt=deepgram.STTv2(model="flux-general-en", eager_eot_threshold=0.4),
)
```

"To use this model for turn detection, set `turn_detection="stt"`… The
session's bundled VAD continues to handle interruption detection."

Full analysis: `docs/reviews/2026-10-05-voice-pipeline-review.md`, finding F1.

## Decision

1. English (Flux) personas use `turn_detection="stt"` by default. Flux's
   `EndOfTurn` commits the user turn, and Silero VAD stays in the session for
   barge-in.
2. `TANGO_TURN_DETECTION=audio` restores the previous `inference.TurnDetector()`
   behaviour without a code change (rollback). Unknown values log a warning
   and use `stt`.
3. Tagalog personas (`stt_language="tl"`, Nova-3) use `turn_detection="vad"`
   explicitly, whatever `TANGO_TURN_DETECTION` says. Neither Flux nor the
   LiveKit turn model supports Tagalog. This is the mode LiveKit auto-selected
   before, so their behaviour does not change.
4. Endpointing stays at the LiveKit defaults (`min_delay=0.5`,
   `max_delay=3.0`). `min_delay` is a floor measured from the end of user
   speech, not an extra delay after Flux fires, so it adds little or nothing
   once Flux has reached its threshold.
5. The worker's "Starting Tango agent" log line records `stt=` and
   `turn_detection=` for every session.

## Rationale

- It is the vendor-documented configuration for Flux on LiveKit.
- It makes the tuning in ADR-002 and ADR-011 real, which is the only way to
  give therapy and meditation personas long pause tolerance.
- The env switch makes the change reversible within one service restart.

## Alternatives Considered

| Option | Rejected because |
|---|---|
| Keep `inference.TurnDetector()` | Per-persona Flux tuning stays inert; reflective personas keep a 0.3 s VAD silence window |
| `turn_detection="stt"` with `min_delay=0` | Removes LiveKit's guard against very short Flux turns; defaults first, tune with metrics later |
| Turn-detector plugin `MultilingualModel` | Deprecated in favour of `inference.TurnDetector`; still ignores Flux events |
| Per-persona env overrides | Not needed until per-turn metrics show which personas need different values |

## Consequences

- Turn-taking changes for all English personas. Pauses shorter than a
  persona's Flux threshold no longer end the turn. Damian and Nathaniel will
  wait noticeably longer before replying, which is what ADR-011 intended.
- Eager end-of-turn now drives preemptive LLM generation. ADR-011 estimates
  50–70% more LLM calls on personas with `eager_eot_threshold` set (Chris,
  Jeremiah, Jeremiah V2, Jacob).
- The `stt end of speech received while vad is still in a speech segment,
  flushing vad` warning will reappear. It is informational in this mode.
- `TANGO_TURN_DETECTION=audio` reverts to the previous behaviour.
- Requires `sudo systemctl restart tango-backend`.

## Verification

1. `journalctl -u tango-backend | grep "Starting Tango agent"` shows
   `turn_detection=stt` for English personas and `turn_detection=vad` for
   Mama Lulu and Tita Baby.
2. With Damian, pause about 2 s mid-sentence. The agent should not reply until
   you finish or about 4.5 s of silence passes.
3. Compare `Turn metrics ... end_of_turn_delay_ms` before and after deploy.

## References

- `docs/reviews/2026-10-05-voice-pipeline-review.md` (F1)
- ADR-002 `2026-06-26-002-deepgram-flux-stt.md`
- ADR-011 `2026-08-20-011-flux-eager-eot.md`
- LiveKit Agents: Deepgram Flux turn detection, `TurnHandlingOptions`
- Deepgram Flux: `eot_threshold`, `eager_eot_threshold`, `eot_timeout_ms`
