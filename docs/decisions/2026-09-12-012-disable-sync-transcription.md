# ADR: Disable RoomIO transcript sync and raise the tool-step ceiling

**Date:** 2026-09-12
**Status:** Accepted
**Decided by:** Cursor Cloud Agent

## Context

Jeff reported agent audio cutting in and out, worse toward the end of a voice
chat. Session `62a4ab7c-3200-402b-8870-dc983b1fc4e9` (Chris / `general-info`,
`writer/palmyra-x6`, ~392s, 2026-09-11 23:53–23:59 UTC) showed:

1. `WARNING livekit.agents: inference is slower than realtime` during long replies
2. Tool-step ceiling: `maximum number of function calls steps reached, generating
   final response with tool_choice='none'` then `received a tool call with
   tool_choice set to 'none', ignoring` for `read_doc`
3. `preemptive generation enabled but chat context or tools have changed after
   on_user_turn_completed` when transcription started
4. **21×** `_SegmentSynchronizerImpl.on_playback_started called after start_fut
   is set` clustered late in the session — the mid-speech pause/cutout signature

ADR-004 already set `use_tts_aligned_transcript=False`. That flag only skips
ElevenLabs word-timing as the transcription-node input. It does **not** stop
RoomIO from constructing `TranscriptSynchronizer` / `_SegmentSynchronizerImpl`
to pace captions with playback. LiveKit Agents docs state the default is
word-paced sync, and the official way to disable that path is
`TextOutputOptions(sync_transcription=False)`.

LiveKit's `max_tool_steps` default is 3. Chris routinely chains
`search_docs` → `read_doc` (and wiki/MCP follow-ups). Hitting the ceiling forces
`tool_choice='none'`; Palmyra still emits ignored `read_doc` calls, then a slow
final generation — matching the ~68s silence after tool-heavy work.

## Decision

1. Start every `AgentSession` with
   `room_options=RoomOptions(text_output=TextOutputOptions(sync_transcription=False))`.
   Captions still publish to the frontend (`useTranscriptions`); they are no
   longer word-paced against audio. Override with `TANGO_SYNC_TRANSCRIPTION=true`
   only for caption-debug.
2. Keep `use_tts_aligned_transcript=False` (ADR-004).
3. Set `max_tool_steps=8` (override `TANGO_MAX_TOOL_STEPS`) so lookup → read →
   follow-up read can complete before the SDK disables tools.
4. Keep speculative LLM generation for latency, but set
   `preemptive_generation.preemptive_tts=False` so a later
   `on_user_turn_completed` mutation (transcription start, Control Mode, vision)
   cannot cancel in-flight speech. Vision still disables preemptive generation
   entirely. Operators can force it off with `TANGO_PREEMPTIVE_GENERATION=false`.

## Rationale

- LiveKit documents `sync_transcription=False` as the switch that emits captions
  as soon as they are available instead of synchronizing them to speech. The
  Python RoomIO source only constructs `TranscriptSynchronizer` when
  `sync_transcription is not False`.
- Tango does not need word-level caption highlighting. Frontend chat already
  merges `lk.transcription` streams as they arrive.
- Raising the tool-step ceiling is the documented LiveKit recommendation for
  agents that legitimately chain lookup + action. Thinking audio
  (`BackgroundAudioPlayer`) already covers the wait; chatty spoken fillers are
  not added.
- `preemptive_tts` defaults to false in current LiveKit Agents; setting it
  explicitly protects older 1.5 builds that may have started TTS speculatively.

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Rely on ADR-004 alone | Production still fired 21 SegmentSynchronizer warnings |
| Disable text output entirely | Frontend captions and MeetScribe-adjacent UX would break |
| Keep `max_tool_steps=3` and add spoken fillers | Prioritize audio continuity; thinking sound already exists |
| Disable preemptive generation globally | Would regress ADR-011 eager-EOT latency for simple turns |
| Faster TTS model / chunking | Flash v2.5 + `auto_mode=True` already in use; sync was the stall |

## Consequences

- Agent captions may appear slightly ahead of audio (acceptable).
- Longer tool chains cost more LLM tokens; 8 steps is an operator-tunable cap.
- Re-enabling `TANGO_SYNC_TRANSCRIPTION` will reconstruct SegmentSynchronizer
  and can restore late-session cutouts.
- Schubert `tango-backend.service` must restart to pick up the change.

## References

- LiveKit Agents: [Text and transcription](https://docs.livekit.io/agents/multimodality/text/)
- LiveKit Agents: [Agent session — max_tool_steps](https://docs.livekit.io/agents/logic/sessions/)
- LiveKit Agents RoomIO: `TextOutputOptions.sync_transcription`
- ADR-004: Disable `use_tts_aligned_transcript`
- Production session `62a4ab7c-3200-402b-8870-dc983b1fc4e9`
