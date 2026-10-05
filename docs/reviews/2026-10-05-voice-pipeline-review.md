# Project Tango Voice Pipeline Review

**Date:** 2026-10-05
**Scope:** Tango voice agents (`backend/`), LiveKit platform integration, Next.js voice client (`frontend/`), and the audio-related docs/ADRs. The Discord fleet, Nexus, Fleet Command, and other non-Tango content in this repository are out of scope.
**Reviewer:** Claude Code (cloud session)
**Sources of truth:** Context7 documentation for LiveKit Agents (`/websites/livekit_io_agents`, `/livekit/agents`), ElevenLabs (`/websites/elevenlabs_io`), Deepgram (`/websites/developers_deepgram`), and the LiveKit JS client (`/livekit/client-sdk-js`, `/livekit/components-js`). API signatures were additionally verified against the installed SDK that the project's pin resolves to today.

---

## 1. Summary

The pipeline is structurally sound and follows the documented LiveKit Agents 1.x shape: `AgentSession` + `deepgram.STTv2` (Flux) / `deepgram.STT` (Nova-3 `tl`) + `elevenlabs.TTS` (Flash v2.5, US routing, `auto_mode`) + `openai.LLM` via LiteLLM, with explicit dispatch. The September fix (ADR-012, `sync_transcription=False`) addressed one real cutout path.

However, the review found four defects that directly affect audio behaviour, and several more that undermine the project's ability to diagnose audio issues at all:

| # | Finding | Severity | Effect on audio |
|---|---|---|---|
| F1 | Flux end-of-turn is silently ignored: the session uses the cloud audio `TurnDetector`, so `eot_threshold` / `eager_eot_threshold` / `eot_timeout_ms` never affect turn boundaries. ADR-002 and ADR-011 are not actually in effect. | High | Turn-taking is driven by Silero VAD (0.3 s silence) + cloud model, not Flux. Agent can cut in during natural pauses; eager EOT latency win is not realised. |
| F2 | The TTS fallback wrapper never engages on the streaming path, so an ElevenLabs outage still produces "no audio frames were pushed". Its warning log calls are also malformed and emit nothing. | High | Fallback is dead code in production. |
| F3 | 13 log calls use `pcts`/`pctd` instead of `%s`/`%d`. Python logging discards the record and prints a traceback to stderr. Control Mode, programs, and TTS-fallback events are invisible in `journalctl`. | High (observability) | Post-incident analysis of cutouts is missing exactly the events that mutate the session mid-turn. |
| F4 | The dependency pin `livekit-agents~=1.5` currently resolves to 1.8.4. Schubert's venv version is unknown from this repo. Behaviour differs across that range (turn handling, preemptive TTS default, RoomIO). **Resolved by pinning to 1.8.4 (see §2 F4).** | High (reproducibility) | Cannot reason about production behaviour without pinning. |
| F5 | Silero VAD is loaded inside every job instead of a worker prewarm. | Medium | Adds model-load time to every session start; VAD CPU contention is the likely source of the "inference is slower than realtime" warning in the 2026-09-11 incident. |
| F6 | Frontend dispatch is a separate authenticated round-trip after `room.connect()`, and the microphone is only enabled after dispatch succeeds. | Medium | 2 extra RTTs before the agent is even requested; pre-connect buffer gains little. |
| F7 | Tagalog personas get no ElevenLabs `language` hint and the Nova-3 `tl` path drops to plain VAD endpointing with no tuning. | Medium | Taglish pronunciation and turn-taking are worse than they need to be. |
| F8 | Transcription stop (DB write + `sendmail` subprocess) and vision frame description run inside `on_user_turn_completed`, blocking the reply. | Medium | Multi-second silence after "stop transcription" or any turn when vision is on. |
| F9 | Meditation track: nearest-neighbour "resampling", 1 s source queue, no ducking against agent speech. | Low | Audible aliasing on non-48 kHz sources; pause lags up to 1 s; agent talks over the track. |
| F10 | Documentation drift: AGENTS.md and README describe a pipeline that differs from `main.py` in several load-bearing details. | Medium | Future agents will "fix" toward the wrong target. |
| F11 | `web_search`, `search_wiki`, `get_wiki_document`, `search_docs`, `read_doc` make **synchronous** `httpx.Client` calls (15–30 s timeouts) inside `async` function tools. They block the job process's event loop, which also runs STT ingestion, VAD, TTS frame pushing, and the thinking sound. | High | The most likely mechanism behind the 68 s silence and "inference is slower than realtime" in the 2026-09-11 incident (Chris chained `search_docs` → `read_doc`). |
| F12 | Frontend auto-reconnect is dead code: the connect effect's cleanup sets `userInitiatedDisconnect` to true and nothing ever resets it, so every disconnect after the first token refresh is treated as user-initiated. | Medium | Any network blip ends the call instead of reconnecting. |
| F13 | Control Mode's `update_persona_behavior` rebuilds instructions from `agent._base_instructions`, which Control Mode never sets (it saves to `_control_mode_saved_instructions`). The live prompt becomes overrides-only, and "exit" restores the pre-override prompt. | Medium | Persona personality drops out mid-session while in Control Mode. |

**Status in this PR:** fixed: F1 (Flux turn detection, ADR-023), F2 (TTS fallback via `tts.FallbackAdapter`), F3 (log format strings), F4 (SDK pin), F11 (non-blocking tools), F12 (frontend auto-reconnect), F13 (Control Mode prompt loss), plus P0 items 3 and 4 (per-turn metrics, backend tests in CI) and two parts of F7/P2 (`language_code=fil` for Tagalog personas, `style=0` for all personas). Later in the same PR: F5 (VAD prewarm), F8 (transcript persistence off the reply path; vision encode off the event loop and preemptive generation kept on), and F9 (meditation on `BackgroundAudioPlayer` with ducking; thinking sound off for Damian and Nathaniel). Still open: F6 (needs owner authorization), the rest of F7 (Tagalog VAD tuning, keyterms on Nova-3), F10 (doc drift).

Section 3 gives the recommended changes in priority order. Section 4 lists what was checked and found correct, so it is not re-litigated.

---

## 2. Findings in detail

### F1. Flux end-of-turn events are discarded (High)

`backend/main.py:_turn_handling_for_session` sets:

```python
turn_handling["turn_detection"] = inference.TurnDetector()
```

for every English persona, while `entrypoint()` builds `deepgram.STTv2(model="flux-general-en", eot_threshold=..., eot_timeout_ms=..., eager_eot_threshold=...)`.

In the SDK, `AudioRecognition` sets `_turn_detection_mode = turn_detection if isinstance(turn_detection, str) else None`. Flux `END_OF_SPEECH` and `START_OF_SPEECH` events are only consumed when that mode is the string `"stt"`:

```python
elif ev.type == stt.SpeechEventType.END_OF_SPEECH and self._turn_detection_mode == "stt":
```

With a `TurnDetector` instance the mode is `None`, so Flux's phrase-endpointing model has no influence on turn boundaries. Turn end is decided by Silero VAD (`min_silence_duration=0.3`) gated by the cloud audio model with the SDK's defaults for that path (`min_delay=0.3`, `max_delay=2.5`).

LiveKit's documented configuration for Flux is:

```python
session = AgentSession(
    turn_handling=TurnHandlingOptions(turn_detection="stt"),
    stt=deepgram.STTv2(model="flux-general-en", eager_eot_threshold=0.4),
)
```

"Deepgram Flux includes a custom phrase endpointing model that uses both acoustic and semantic cues. To use this model for turn detection, set `turn_detection="stt"`… The session's bundled VAD continues to handle interruption detection."

Consequences:

- Per-persona `eot_threshold` values (0.7–0.8) and the therapy/meditation `eot_timeout_ms` of 4.5–5.5 s are inert. Damian and Nathaniel, which were tuned for long reflective pauses, actually get a 0.3 s VAD silence window plus the generic audio model. This is a plausible root cause for "the agent cuts in while I'm still thinking" reports.
- Eager EOT (ADR-011) can still fire a `PREFLIGHT_TRANSCRIPT` for preemptive LLM generation, but the turn is not committed on Flux's `EndOfTurn`, so the latency benefit is partial at best, and the extra LLM calls are still paid for.
- The in-code comment claims the TurnDetector change was made to eliminate the "stt end of speech received while vad is still in a speech segment" warning. That warning disappeared because Flux EOS is now ignored, not because the race was fixed. In `"stt"` mode that warning is benign: the SDK flushes VAD precisely so that VAD can correct a premature Flux EOT.
- The code also logs `flux_stt=nova-3-multi` for Tagalog personas; the string is never used for anything but logging and is wrong (the Tagalog path uses `nova-3` with `language="tl"`).

### F2. TTS fallback never engages on the streaming path (High)

`_build_fallback_tts` wraps the primary in a custom `FallbackTTS` whose `stream()` method is:

```python
def stream(self, *, conn_options=...):
    return self._primary.stream(conn_options=conn_options)
```

`AgentSession` uses `tts.stream()` whenever `capabilities.streaming` is true, which it is for ElevenLabs (the wrapper copies the primary's capabilities). So in production the fallback is only reachable for the F5-TTS adapter, which is non-streaming. For every ElevenLabs persona the "no audio frames were pushed" outage that motivated the wrapper is unchanged.

In addition the wrapper's two `logger.warning` calls use `pctpcts` instead of `%s` (see F3), so even on the F5 path a fallback would log nothing.

The SDK ships `livekit.agents.tts.FallbackAdapter(tts=[primary, fallback], max_retry_per_tts=2)`, which wraps both streaming and non-streaming paths, handles sample-rate mismatches, and emits `tts_availability_changed` events. The custom class should be deleted in favour of it. (`stt.FallbackAdapter` and `llm.FallbackAdapter` exist as well and are the right tool for the LiteLLM-timeout handling that is currently only a log message.)

### F3. Broken log format strings (High, observability)

```
backend/jarvis_agent.py: 11 occurrences
backend/main.py:          2 occurrences
```

Example (`jarvis_agent.py`):

```python
logger.info("Control Mode enabled persona=pcts tools=pctd", persona.id, len(control_mode_tools))
```

Verified behaviour: the handler emits nothing and Python prints `--- Logging error ---` plus `Arguments: ('jeremiah', 3)` to stderr. Affected events: legacy tool loading, Control Mode enable/activate/deactivate, program pre-activation/activation/deactivation/not-found, and both TTS-fallback warnings. These are exactly the mid-session mutations ADR-012 identified as cutout triggers ("chat context or tools have changed after on_user_turn_completed"), so the current logs cannot show when they happen.

This is a mechanical find-and-replace (`pcts` → `%s`, `pctd` → `%d`) and should be guarded by a test that imports each module with logging configured to raise on formatting errors.

### F4. Unpinned SDK version (High, reproducibility)

`requirements.txt` and `pyproject.toml` specify `livekit-agents[deepgram,elevenlabs,openai,silero]~=1.5`, which permits any 1.x ≥ 1.5. A fresh install today resolves to 1.8.4. Across 1.5 → 1.8 the SDK changed: `turn_detection` and all endpointing/interruption kwargs were moved under `turn_handling` (old kwargs deprecated, removed in 2.0); `preemptive_tts` default became `False`; `RoomInputOptions`/`RoomOutputOptions` were deprecated for `RoomOptions`; `inference.TurnDetector` replaced the turn-detector plugin; `WorkerOptions` became an alias of `ServerOptions`; session-level `metrics_collected` was deprecated for `session_usage_updated`.

The repository does not record which version is installed on Schubert (`/opt/Project-Tango/backend/venv`). AGENTS.md rule 2 ("never guess at Schubert's state") applies: the exact version must be captured (`venv/bin/pip freeze | grep livekit`) and pinned with `==` for all `livekit-*` packages, with a lockfile (`uv.lock` or `pip-compile` output) committed.

**Scope of the SDK-level findings.** This session could not query Schubert, so every finding that depends on SDK internals (F1, F2, F5, and the defaults quoted in §3) was verified against `livekit-agents` 1.8.4, the version `~=1.5` resolved to on 2026-10-05. They are statements about 1.8.4, not about whatever Schubert ran before. The same PR pins `livekit-agents` and its plugins to exactly 1.8.4 (commit `e3ec6f4`). Because `scripts/deploy.sh` runs `pip install -r requirements.txt`, the version analysed here is the version production runs after the next deploy. The worker now logs installed LiveKit versions at startup; check that line after deploy. The pre-deploy production version remains unrecorded. If anyone needs to know whether F1 or F2 affected a past incident on an older 1.x release, they should read `pip freeze` from a Schubert backup or the deploy log, not this document.

### F5. VAD loaded per job, not prewarmed (Medium)

`entrypoint()` calls `silero.VAD.load(min_silence_duration=0.3, prefix_padding_duration=0.3)` on every job. The documented pattern is a `prewarm_fnc` that stores the model in `proc.userdata["vad"]`. On Schubert, where the worker shares CPU with Ollama, LiteLLM, and the vision pipeline, a per-job ONNX load adds start-up latency and the 2026-09-11 log line `inference is slower than realtime` is the VAD's own CPU-starvation warning (`SLOW_INFERENCE_THRESHOLD` in the VAD stream). Prewarming removes the load cost; the contention itself argues for `num_idle_processes=1` (already set) plus `load_threshold` tuning, and for keeping vision off by default on that host.

Also: `min_silence_duration=0.3` is below the SDK default (0.55) and is the interruption/turn-end sensitivity for all personas once F1 is fixed. It should become a per-persona value.

### F6. Dispatch round-trip and microphone ordering (Medium)

`frontend/components/app.tsx` sequence: `room.connect()` → `fetch('/api/dispatch')` (auth + CSRF + DB grant update + LiveKit API call) → `setMicrophoneEnabled(true, …, { preConnectBuffer: true })`.

LiveKit supports dispatch-at-connect by embedding `RoomConfiguration(agents=[RoomAgentDispatch(agent_name=..., metadata=...)])` in the participant token (`AccessToken.with_room_config`). The backend already has the hook (`token.with_room_config(request.room_config)`) but only for a client-supplied value that the authenticated path never sets. Moving dispatch into the token:

- removes one authenticated HTTP round-trip and one LiveKit API call from the critical path;
- removes the `voice_room_grants.dispatched_at` race-guard logic and the `/api/dispatch` endpoint;
- lets the mic be enabled before `connect()` so the pre-connect buffer actually captures the user's first words while the agent is initialising (that is what `preConnectBuffer` is for);
- is consistent with ADR-006's intent (agent must not join before the user) because the dispatch fires on first participant join.

Two smaller client issues: `RoomAudioRenderer` is mounted conditionally on `canPlayAudio`, so remote audio elements are created late on browsers that block autoplay; the component is designed to be always mounted with `StartAudio` as the gate. And `new Room()` is created with no options, which is fine for audio, but `prepareConnection(url, token)` is not called, so the WebSocket/ICE warm-up starts only after the token fetch.

### F7. Tagalog path (Medium)

- `deepgram.STT(model="nova-3", language="tl", smart_format=True)` is correct per Deepgram (Nova-3 `tl` streaming is supported and received an improved model in the 2026-08-27 changelog; Flux does not support Tagalog). But `turn_handling.pop("turn_detection")` leaves the session with no mode, which the SDK resolves to `"vad"`. The SDK's own guidance for languages the turn model does not cover is `turn_detection="vad"` explicitly, with `endpointing.min_delay` tuned; today the Tagalog personas get VAD with `min_silence_duration=0.3` and the default 0.5 s `min_delay`, untuned.
- `keyterms` on the two Tagalog personas are defined but never passed to `deepgram.STT` (only the Flux branch forwards `keyterm`). Nova-3 keyterm support on `tl` is not confirmed in Deepgram docs; it should be tried and measured, not assumed.
- ElevenLabs: `eleven_flash_v2_5` supports Filipino (`fil`), but the plugin is never given `language="fil"`. Without `language_code` the model guesses per chunk, which is the classic cause of English-accented Tagalog and mis-normalised numbers in Taglish. Phoneme pronunciation dictionaries are English-only on Flash; alias rules are the only option for Tagalog words that still mispronounce.
- Flash v2.5 has text normalisation off by default; number/date normalisation must be done in the prompt or by the LLM.

### F8. Blocking work inside `on_user_turn_completed` (Medium)

`Jarvis.on_user_turn_completed` awaits, in order: transcription recorder (DB + `sendmail` subprocess on "stop"), Control Mode / program DB loads and `update_instructions`, meditation track start (file open + track publish), and `vision_context.describe_latest_frame` (a vision-LLM call with a configurable timeout). All of these delay the reply; the vision call in particular is an LLM round-trip inside the turn pipeline. Preemptive generation is disabled when vision is on, so that path pays full latency on every turn.

The documented pattern is: do the mutation that must precede the reply (instruction/context changes) inline; move side effects (DB write, email, memory) to `asyncio.create_task` or a shutdown callback; and for vision, inject the latest frame description from a background sampler rather than requesting it synchronously per turn.

*Correction (2026-10-05):* a background sampler is not recommended. In the default `auto` injection mode the vision model is only called on turns that refer to something visual, and those replies need the description, so a sampler would add continuous vision-model calls without shortening those turns. The real costs were the JPEG encode running on the event loop and preemptive generation being disabled for every turn whenever vision was enabled. Both are fixed: the encode runs in the worker thread with the request, and preemptive generation stays on because LiveKit discards a draft whose context changed.

### F9. Meditation player (Low)

`MeditationPlayer._resample` is nearest-neighbour index selection despite the docstring saying linear interpolation; for a 44.1 kHz source into 48 kHz it aliases audibly. `AudioSource(queue_size_ms=1000)` means pause/stop take up to a second to be heard. The track is published as a second LiveKit audio track with no ducking, so when Nathaniel speaks the two overlap at full volume. `BackgroundAudioPlayer.play()` in the SDK already handles file decoding, resampling, fade in/out and volume on a dedicated track; it is the simpler replacement (`await background_audio.play(path, volume=...)` returns a `PlayHandle` with `stop()`), and its `ambient_sound`/`thinking_sound` mixing is documented.

Separately, the keyboard-typing "thinking" sound is enabled by default for all personas, including the therapy and meditation personas whose ADR rationale is "presence over speed". That should be a per-persona setting.

### F10. Documentation drift (Medium)

| Doc says | Code does |
|---|---|
| AGENTS.md 3.4: `turn_detection="stt"` must be nested in `turn_handling` | `turn_handling["turn_detection"] = inference.TurnDetector()`; `"stt"` is never used |
| AGENTS.md 3.3: Flux via `deepgram.STT(model="flux-general-en")` | `deepgram.STTv2(...)` (correct for current plugin) |
| AGENTS.md 3.4: ADR-004 flag alone does not prevent pauses (correct) | — |
| ADR-002 / ADR-011: Flux native turn detection and eager EOT drive turns | Ignored at runtime (F1) |
| AGENTS.md 4: `backend/main.py`, `history.py` are the backend | 20+ modules; `jarvis_agent.py` owns the `Agent` subclass |
| README: project is "self-hosted on Schubert" | LiveKit is LiveKit Cloud (`*.livekit.cloud`); only the worker and web app are on Schubert |
| CHANGELOG `[Unreleased]` | Four separate `[Unreleased]` sections, three of them Fleet Command |
| ADR-012 "preemptive_tts defaults to false in current LiveKit Agents" | Correct for ≥ 1.7; unknown for Schubert's version (F4) |

### F11. Synchronous HTTP inside async tools (High)

| File | Call | Timeout |
|---|---|---|
| `backend/search_tools.py:63` | Serper search | 15 s |
| `backend/search_tools.py:122`, `:144` | Palmyra x6 / x5 summarisation | 30 s each |
| `backend/wiki_tools.py:44` | Outline API | 15 s |
| `backend/mintlify_tools.py:55`, `:128` | Mintlify MCP | 20 s, 15 s |

All are `with httpx.Client(...)` inside `def` helpers called directly from `async def` tool bodies, with no `asyncio.to_thread`. The comment at `search_tools.py:26-30` claims this "does not affect real-time voice latency"; the opposite is true. In the LiveKit job process the same event loop services the Flux WebSocket reader, Silero VAD inference, ElevenLabs frame pushing, `BackgroundAudioPlayer`, and `MeditationPlayer.capture_frame`. While a tool blocks, no audio frames are pushed (mid-speech cutout if the agent was speaking a filler), user audio accumulates unread (VAD then reports "slower than realtime"), and the thinking sound stalls. A single `web_search` can block for up to 75 s. `vision_context.py` already does this correctly with `asyncio.to_thread` (`:297`); `memory.py` uses `httpx.AsyncClient`.

Fix: switch all four modules to `httpx.AsyncClient` (one shared client per module, created lazily), or wrap the sync helpers in `asyncio.to_thread`. Add a lint rule or test asserting no `httpx.Client(` in `backend/*_tools.py`.

### F12. Dead auto-reconnect (Medium)

`frontend/components/app.tsx:146-160` has an "unexpected disconnect → refresh token and reconnect (3 attempts)" branch gated on `!userInitiatedDisconnect.current`. The connect effect's cleanup (`:265-269`) sets that ref to `true` whenever any dependency changes, including `connectionDetails`, which `refreshConnectionDetails()` itself changes. The ref is never set back to `false`. Net effect: the reconnect branch can run at most once, and in practice the first token refresh flips the flag permanently, so later disconnects end the session. The connect/dispatch failure paths also toast "Retrying..." but call `setSessionStarted(false)`, which stops rather than retries.

### F13. Control Mode drops the persona prompt (Medium)

`control_mode.py:276` reads `agent._base_instructions` as the base for `apply_overrides_to_prompt`. `jarvis_agent.py` only sets `_base_instructions` on program activation; entering Control Mode saves the prompt to `_control_mode_saved_instructions` instead (`:319`). So the first `update_persona_behavior` call rebuilds instructions from an empty base, and exiting Control Mode (`:333`) restores the saved prompt without the new override. The override is persisted to the DB and applies on the next session, which hides the bug.

### Other verified defects (not audio, recorded for completeness)

- `backend/sip.py` has no `jeremiah-v2` prefix, so SIP rooms for that persona resolve to `jeremiah`.
- `backend/tests/` is not run by `.github/workflows/test-gate.yml` (Nexus tests only). The voice-pipeline tests pass locally on 1.8.4 but never gate a merge.
- `.github/workflows/deploy.yml` runs on every push to `main` and `scripts/deploy.sh` restarts `tango-backend` with no worker drain, so every merge drops live calls. `WorkerOptions.drain_timeout` plus `systemctl reload`-style signalling or a deploy-time `/drain` would fix this.
- Both `.env.example` files ship `TANGO_VISION_ENABLED=true`, which disables preemptive generation; CHANGELOG says vision is off for audio-only sessions.
- Env vars used by code but absent from every `.env.example`: `TANGO_SESSION_TTL_MINUTES`, `TANGO_USER_AWAY_TIMEOUT`, `TANGO_ELEVENLABS_USE_PVC_AS_IVC`, `TANGO_MEDITATION_TRACK`, `TANGO_TRANSCRIPTION_ENABLED`, `TANGO_TRANSCRIPTION_EMAIL_FROM`, `TANGO_DB_POOL_MIN/MAX`, `TANGO_DB_SOCKET_DIR`, `LOG_LEVEL`, `LIVEKIT_LOG_LEVEL`.
- `frontend/hooks/useDebug.ts` sets the livekit-client log level to `debug` unconditionally in production.
- The Welcome screen's `MeditationTile` (plain `<audio>` element) stays mounted and can keep playing into the microphone during a voice session.
- ADR numbers 011, 012, 013, 014, 015, 016, 020 are each used by two or three files; "ADR-012" currently means three different decisions.
- Chris's LLM, Jeremiah's TTS backend, and the Tagalog personas' LLM are documented differently in `docs/architecture.md`, `docs/AGENTS.md`, `deploy/README.md`, and `frontend/lib/personas.ts` than they are set in `backend/personas.py`.

---

## 3. Recommendations (priority order)

### P0. Make the pipeline observable and reproducible first

1. **Pin the SDK.** Set `livekit-agents==X.Y.Z` and matching `livekit-plugins-*==X.Y.Z`, and log the installed versions at worker startup. Ideally capture `pip freeze` from Schubert's venv first so the pin matches production; failing that, pin to the version the analysis and tests used, so production converges on it at the next deploy. Until this is done, every other change is being tested against an unknown target. *(Done in this PR: pinned to 1.8.4 with a startup log line and a pin-drift test. No lockfile: only the LiveKit packages are pinned exactly.)*
2. **Fix the 13 `pcts`/`pctd` log calls** and guard them with a static check. A runtime test is not enough: importing a module does not execute the Control Mode, program, or fallback log calls, and `logging.raiseExceptions` only routes formatting errors to `Handler.handleError`, so such a test passes with the bug present. The check should parse every logger call and compare its `%` placeholder count with the number of arguments. *(Done in this PR: `backend/tests/test_logging_format.py`, which reports all 13 calls on the previous revision.)*
3. **Switch to `session_usage_updated` + `ChatMessage.metrics`** (already partly done) and log `stt_delay`, `llm_node_ttft`, `tts_node_ttfb`, `e2e_latency` per agent turn as structured fields. Add `tts_availability_changed` and `error` event handlers. This is what makes the next cutout report diagnosable.
4. **Add `backend/tests` to `test-gate.yml`** so the voice-pipeline guards actually gate merges.

### P1. Unblock the event loop and restore Flux-driven turn detection

5. **Convert the five tool helpers to `httpx.AsyncClient`** (F11). This is a contained change with no behavioural risk and is the single most likely fix for tool-turn cutouts and the 68 s silence. Pair it with a test that fails on `httpx.Client(` in `backend/*_tools.py`.

6. Replace `inference.TurnDetector()` with the documented Flux configuration:

   ```python
   turn_handling = TurnHandlingOptions(
       turn_detection="stt",
       endpointing={"mode": "fixed", "min_delay": persona.min_endpointing_delay, "max_delay": 3.0},
       interruption={"min_duration": 0.5, "min_words": 0},
       preemptive_generation={"enabled": preemptive_enabled, "preemptive_tts": False},
   )
   ```

   Keep Silero VAD for interruption detection (that is its documented role in `"stt"` mode). Note that `min_delay` is added on top of Flux's own EOT delay, so personas tuned for pauses should get a small `min_delay` and a high `eot_threshold`, not a large `min_delay`.
7. Re-validate per-persona Flux values against Deepgram's documented presets: conversational `eot_threshold=0.7–0.8`, tool-heavy/RAG personas (Chris) `eager_eot_threshold=0.4, eot_threshold=0.85, eot_timeout_ms=7000`. `eager_eot_threshold` must be ≤ `eot_threshold` or the plugin raises. Measure before and after with the per-turn metrics from P0 item 3; eager EOT roughly doubles LLM calls, and the ADR-011 cost/benefit claim has never been measured because the setting was inert.
8. For Tagalog personas set `turn_detection="vad"` explicitly with a persona-level `min_endpointing_delay` (start at 0.8 s; Taglish has longer intra-sentence pauses), forward `keyterms` to `deepgram.STT`, and record whether keyterms change accuracy on `tl`.
9. Move `silero.VAD.load()` into `WorkerOptions(prewarm_fnc=...)` and make `min_silence_duration` a persona field.

### P2. Fix TTS resilience and Taglish voice quality

10. Delete the custom `FallbackTTS` and use `tts.FallbackAdapter([elevenlabs_tts, deepgram_aura_tts])`. Add `stt.FallbackAdapter([flux, nova3_en])` for the English path and `llm.FallbackAdapter` for LiteLLM 504s instead of the current log-only handling.
11. Pass `language="fil"` to `elevenlabs.TTS` for `stt_language == "tl"` personas. Keep `eleven_flash_v2_5` (ElevenLabs recommends it for agents; Turbo is deprecated; v3/v4 are not available on the TTS WebSocket at all). Keep `auto_mode=True`. Set `style=0.0` on all personas: ElevenLabs documents that any non-zero `style` adds latency and recommends 0 for agents; Damian/Chris/Jeremiah use 0.15–0.25 and the Tagalog personas 0.25.
12. Try `sync_alignment=False` on the ElevenLabs plugin: Tango sets `use_tts_aligned_transcript=False`, so the alignment payload the plugin requests by default is never consumed.
13. Instruct the LLM to write out numbers, dates and times in words (add to `VOICE_LAYER_1_CONSTRAINTS`): Flash v2.5 ships with normalisation off, and that is the cheapest fix for "two thousand twenty six" being read as digits in Taglish.
14. Replace `MeditationPlayer` with `BackgroundAudioPlayer.play()`, duck or pause the track while the agent speaks (`agent_state_changed` → `speaking`), and make the thinking sound a persona flag defaulting to off for Damian and Nathaniel.

### P3. Shorten the connect path

15. **Requires the owner's authorization before any code change.** This reverses AGENTS.md §3.5 ("The frontend calls [`/api/dispatch`] **after** `room.connect()` succeeds"), which only the human owner may modify, and supersedes ADR-006. Until the owner approves and updates both, keep the current post-connect dispatch flow and the `dispatched_at` guard. The proposal, if approved: put `RoomAgentDispatch(agent_name=TANGO_AGENT_NAME, metadata=...)` into the participant token's `RoomConfiguration` in `authorized_connection_details`. Remove `/api/dispatch`, its frontend call, and the `dispatched_at` guard (the grant row still records the issuance). Enable the microphone with `preConnectBuffer: true` before `room.connect()`, and call `room.prepareConnection()` as soon as connection details arrive. Mount `RoomAudioRenderer` unconditionally. Update ADR-006 to record that dispatch-at-connect preserves "agent joins only after the user" because LiveKit dispatches on first participant join.

### P4. Take side effects out of the turn pipeline

16. In `on_user_turn_completed`, keep only instruction/context mutations inline. Move transcript DB writes and `sendmail`, memory generation, and meditation track start into background tasks. Convert vision to a background sampler that keeps "latest description" ready, so the turn only reads a string. Re-enable preemptive generation when vision is on once that is done.

### P5. Bring the docs back to reality

17. AGENTS.md is owner-only (§4 ownership table), so the AGENTS.md items here are proposals for the owner, not agent tasks. Proposed: update AGENTS.md 3.3/3.4 (STTv2, `turn_handling=TurnHandlingOptions(turn_detection="stt")`), the repository map in AGENTS.md 4, README's hosting description, and consolidate CHANGELOG `[Unreleased]`. Mark ADR-002 and ADR-011 as "Accepted — not in effect between <date of TurnDetector change> and <fix date>" with a pointer to this review. Add an ADR for the dispatch-in-token change (P3) and for the FallbackAdapter change (P2).
18. Fix F12 (reset `userInitiatedDisconnect` on connect; make the failure paths actually retry) and F13 (set `_base_instructions` on Control Mode entry, or have `update_persona_behavior` read the saved prompt).

### Deliberately not recommended

- **`noise_cancellation.BVC()`**: LiveKit Cloud-only, but Tango is on LiveKit Cloud so it is available. It is not in the list above because the user-side browser already applies echo cancellation, noise suppression and voice isolation (LiveKit JS defaults), and BVC adds server-side CPU on the worker. Worth a measured trial after P1, not before.
- **Switching Tagalog to Nova-3 `multi`**: Deepgram documents `multi` for code-switching, but Tagalog in the `multi` language set is not confirmed in the docs. Stay on `tl` until that is verified in a test session.
- **Moving to `AgentServer`/`@server.rtc_session`**: the documented 1.8 style, but `WorkerOptions` + `cli.run_app` is an alias and still supported; not worth churn until the version is pinned.

---

## 4. Verified as correct (no action)

- Flux is built with `deepgram.STTv2`, the correct class for the v2 endpoint; `eager_eot_threshold ≤ eot_threshold` is validated by the plugin.
- Nova-3 `language="tl"` with `smart_format=True` is the right Tagalog configuration; Flux does not support Tagalog on any model.
- `eleven_flash_v2_5` with `auto_mode=True` and `api.us.elevenlabs.io` routing matches ElevenLabs' latency guidance. `use_pvc_as_ivc` is a real ElevenLabs option for PVC latency; the plugin's `VoiceSettings` does not expose it, and the code handles that `TypeError` correctly.
- `RoomOptions(text_output=TextOutputOptions(sync_transcription=False))` is the documented way to disable playback-paced captions (ADR-012). The test `test_livekit_roomio_skips_synchronizer_when_sync_is_false` guards it.
- `preemptive_generation={"enabled": ..., "preemptive_tts": False}` is the documented shape and the right choice given mid-turn context mutation.
- `max_tool_steps=8` is reasonable for the search → read → read chains and is operator-tunable.
- `user_away_timeout=None` is the documented way to disable the 15 s away state.
- `ctx.add_shutdown_callback` for history flush, vision close, and transcription finalise; `session.on("close")` double-flush is guarded by a lock.
- Explicit dispatch with `agent_name` and `CreateAgentDispatchRequest(room=...)` is correct as written; P3 is an optimisation, not a bug fix.
- Token grants (`room_join`, `can_publish`, `can_subscribe`, `can_publish_data`) match LiveKit's frontend-auth example. 8 h TTL is generous but intentional (ADR for long sessions).
- All LLM traffic goes through LiteLLM; no direct Ollama calls; no forbidden env vars in `.env.example`.
- The eight tests in `backend/tests/test_voice_pipeline.py` pass against livekit-agents 1.8.4.

---

## 5. Suggested validation plan for the P1 change

1. Deploy P0 first and collect one week of per-turn metrics (`stt_delay`, `e2e_latency`, interruption count, `transcription_delay`) per persona as a baseline.
2. Deploy P1 behind `TANGO_TURN_DETECTION=stt|audio` (default `stt`) so it can be flipped without a code change.
3. For each English persona run a scripted conversation containing: a 1.5 s mid-sentence pause, a 3 s thinking pause after a question, and a barge-in during a long answer. Compare: false end-of-turn count, time from user speech end to agent audio start, and interruption recovery.
4. Confirm in `journalctl` that `EndOfTurn` events from Flux are now the committed turn source (the SDK logs `turn_detection_mode` and the `stt end of speech … flushing vad` line will reappear; it is expected in this mode).
5. Only after that, re-tune `eager_eot_threshold` per persona and decide whether the LLM-call cost is worth it per route (local Qwen is cheap; Palmyra is not).
