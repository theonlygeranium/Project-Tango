# Project Tango Bootstrap Plan

## BS-001 + BS-002

- Canonical deployment repo: `theonlygeranium/Project-Tango`.
- Fork baseline: `theonlygeranium/AURA`.
- Rename app/package identity to `project-tango`.
- Keep the AURA LiveKit orb frontend and add a session-start persona selector.
- Route backend LLM traffic through Schubert LiteLLM at `http://localhost:4000`.
- Use `LITELLM_MASTER_KEY` to authenticate to LiteLLM.
- Upgrade STT to Deepgram Nova-3 with interim results.
- Use ElevenLabs Flash v2.5 with persona-specific voice IDs.
- Ship deploy artifacts under `deploy/` for backend/web systemd units and an API-only Caddy append block.

## v1.2 Runtime Decisions

- Frontend local/deploy port: `3006`.
- Backend local/deploy port: `8030`.
- Existing frontend Caddy route: `project-tango.schubert.life -> 3006`; do not recreate it.
- New API Caddy route: `tango-api.schubert.life -> 8030`.
- Therapy, Jeremiah, Jacob, Mama Lulu, Meditation, Pinoy Pride model alias: `local/qwen3-fast`.
- Chris default model alias: `writer/palmyra-x5-voice`.
- Do not use unregistered aliases `ollama/qwen3.6`, `ollama/qwen3.6:latest`, or `writer/palmyra`.

## Current Status - 2026-06-22

- The private `Project-Tango` repo is the deployment source for Schubert.
- Public `AURA` is kept as the fork baseline / historical adaptation source.
- Work is on local branch `project-tango/bootstrap`.
- Backend and frontend persona maps are updated to the v1.2 LiteLLM aliases.
- `backend/.env.example` uses `LITELLM_MASTER_KEY` and does not include `WRITER_API_KEY`.
- Deploy artifacts now target `/opt/Project-Tango` and the Schubert user `z121532`.
- `deploy/Caddyfile.tango-api` contains only the API block.
- Goals 1 through 3 are locally implemented for the Phase 1 bootstrap surface:
  fork adaptation, persona routing, LiveKit Agents provider wiring, live caption
  UI, mobile polish, theme controls, and deployment artifacts.
- Goal 4, Schubert production deployment, is complete. The current worktree is
  synced to `/opt/Project-Tango`, `/opt/Project-Tango/.env` is preserved with
  mode `600`, backend and frontend production builds are installed,
  `tango-backend.service` and `tango-web.service` are active, and the existing
  legacy `project-tango-web` Docker container was stopped so systemd owns
  frontend port `3006`.
- `tango-api.schubert.life` now has a proxied Cloudflare CNAME to
  `project-tango.schubert.life`, the API Caddy block is loaded after a Caddy
  restart, and authoritative/Cloudflare resolver checks return
  `104.21.34.22` and `172.67.167.183`. Browser-side DNS on the local Mac had a
  stale negative cache, but the API was accepted as passing because
  `https://tango-api.schubert.life/healthz` responds correctly when resolved
  through both Cloudflare edge IPs.
- Goal 5, PostgreSQL conversation history, is complete on Schubert. The
  implementation adds the `tango` schema migration, raw `asyncpg` pool and
  history modules, rate-limited read endpoints, write-on-close LiveKit history
  collection, and a read-only frontend history drawer.
- Goal 5 history close handling is hardened so the close-path retry flag is set
  only after the database transaction succeeds. This prevents a LiveKit worker
  shutdown from leaving `ended_at` null if the first background flush task is
  cancelled before writing.
- Audio optimization pass from
  `/Users/jeffgeronimo/Downloads/Project Tango_VERIFICATION_AND_AUDIO_OPTIMIZATION.md`
  is applied for the supported LiveKit plugin settings: Deepgram Nova-3 now uses
  `endpointing_ms=300` and `smart_format=True`; ElevenLabs Flash v2.5 now uses
  per-persona `VoiceSettings`, `streaming_latency=3`, `auto_mode=True`, and
  `use_speaker_boost=False` for all personas. Deepgram Flux and unsupported
  `utterance_end_ms` remain deferred.
- Tita now uses persona-specific Deepgram Nova-3 Tagalog STT (`language="tl"`)
  for the current Tagalog/Filipino test pass. Damian, Chris, Jeremiah, Jacob, Mama Lulu, and Nathaniel
  remain on `en-US`.
- The welcome screen now has an allowlisted LLM switcher for `Persona default`,
  `local/qwen3-fast`, and `writer/palmyra-x5-voice`. The selected alias is
  included in token metadata/attributes, validated again by the worker, logged,
  and persisted in conversation history.
- Each agent prompt now receives the actual runtime LiteLLM alias, so personas
  answer model-identity questions from the routed alias instead of guessing.
- Follow-up log review on 2026-06-25 found that the latest long Tita session was
  intentionally routed through `writer/palmyra-x5-voice` by the frontend model
  override. Model overrides are now per-call only: the frontend starts on
  `Persona default` and resets the model selector to `Persona default` whenever
  the persona changes, so Tita returns to `local/qwen3-fast` unless explicitly
  overridden for that call.
- The same Tita review found occasional late Tagalog STT finals and split user
  phrases, so Pinoy Pride sessions now apply LiveKit endpointing
  `min_delay=0.7` while the other personas keep the SDK default.
- Chris/local-Qwen review on 2026-06-25 confirmed `general-info` can be routed
  through `local/qwen3-fast`, but the local route is slower than Palmyra for
  longer spoken answers and shares Ollama with other Schubert workloads. Tango
  now applies local-Qwen voice guidance that favors one or two short sentences
  and applies endpointing `min_delay=0.6` for non-Tagalog local-Qwen sessions.
  Do not fix local route contention by changing shared LiteLLM/Ollama config
  from this repo; coordinate shared infra changes separately.
- Jeremiah is added as a second General assistant with American English STT
  (`en-US`), ElevenLabs voice ID `EqHdTYoEuDQCxN1CVbi0`, and default route
  `local/qwen3-fast`; the allowlisted model switcher can still route him to
  Palmyra for comparison.
- Jacob is added as another General assistant with American English STT
  (`en-US`), ElevenLabs voice ID `qYwy2TckibCF9cBuhI46`, and default route
  `local/qwen3-fast`; the allowlisted model switcher can still route him to
  Palmyra for comparison.
- Mama Lulu is added as another General assistant with American English STT
  (`en-US`), ElevenLabs voice ID `LF1xMOq6fDVEBEkLP0HO`, and default route
  `local/qwen3-fast`; the allowlisted model switcher can still route her to
  Palmyra for comparison.
- Camera and screen-share controls now feed a LiveKit video-frame context path.
  The worker subscribes to video tracks, keeps the newest camera/screen frame,
  asks a vision-capable LiteLLM alias (`TANGO_VISION_MODEL`, default
  `openai/gpt-4o-mini`) for a compact visual summary on visually referential
  user turns, and injects that text into the persona's current voice-model turn.
  Grok can be tested by setting `TANGO_VISION_MODEL=xai/grok-4`, but the persona
  speaking model remains independently selected.
- The vision path disables LiveKit preemptive generation while visual context is
  enabled by setting `turn_handling.preemptive_generation.enabled=false`,
  preventing the persona model from racing ahead before the injected visual note
  is ready. Text-heavy visual turns use an OCR mode with larger 1536px
  high-detail frames, `TANGO_VISION_OCR_MODEL` (default `openai/gpt-4o`), and a
  prompt that preserves exact terminal/output/log/code text when readable.
  Software/app/editor/interface identification prompts also use OCR so small UI
  chrome, browser tabs, menu labels, and workspace titles are read before the
  speaking model answers. Optional `TANGO_VISION_DEBUG_SUMMARIES=true` logging
  records only the injected text summary for diagnostics, not screenshots.

Live inspection on 2026-06-22 confirmed the v1.2 LiteLLM aliases exist in
`/opt/polyglot/services/litellm/litellm_config.yaml`.

Live inspection also showed `127.0.0.1:8010` is permanently held by Docker
container `asr-gateway`, so Tango must not reuse that port. Backend port `8030`
is the v1.2 target and should stay free for `tango-backend.service`.

## Validation Snapshot - 2026-06-22

- `backend`: Python compile passes for `main.py`, `jarvis_agent.py`, and
  `personas.py`.
- `backend`: LiveKit Agents service construction passes for all seven personas with the
  expected LiteLLM aliases and ElevenLabs voice IDs.
- `frontend`: `corepack pnpm exec tsc --noEmit` passes.
- `frontend`: `corepack pnpm run build` passes without lint or metadata warnings.
- `deploy`: `bash -n deploy/schubert-preflight.sh` passes.
- Repo hygiene: `git diff --check` passes.
- Browser QA confirmed persona selection, mobile 375/390/430 layout, light/dark
  theme behavior, caption overlay placement, and caption toggle persistence.
- Browser QA confirmed a live Damian session reaches the connected/listening
  state, displays agent transcript captions, accepts a text chat turn, and shows
  the agent response in the transcript/caption surface.
- Worker QA confirmed the live session used `local/qwen3-fast`, the Damian
  ElevenLabs voice ID, and `http://127.0.0.1:4000/v1`; transcript IO was active.
- Manual browser QA confirmed the remaining audible playback path with a live
  Chris (General Info) session. Worker logs showed the real browser microphone
  stream attached as `SOURCE_MICROPHONE`, Deepgram transcripts for multiple
  spoken turns, `writer/palmyra-x5-voice`, the Chris ElevenLabs voice ID, and
  assistant responses; the browser console had no fresh warning/error logs
  during the test window.
- Legacy AURA desktop/web tool modules are disabled by default to avoid
  OS-specific optional dependency warnings. Set `TANGO_ENABLE_LEGACY_TOOLS=true`
  to opt back in.
- Browser QA confirmed Deepgram speech input by using a LiveKit synthetic
  microphone participant in controlled room `tango_therapy_deepgramqa3`; worker
  logs showed the transcript text, and the browser rendered the resulting live
  transcript/agent response text.
- Audio QA confirmed the app no longer mounts `RoomAudioRenderer` until LiveKit
  reports playback is unlocked, and the final manual test proved audible
  ElevenLabs/WebRTC playback from the user side.
- Schubert production deployment QA confirmed `tango-backend.service` and
  `tango-web.service` are active, `http://127.0.0.1:8030/health` returns OK,
  `http://127.0.0.1:3006` returns HTTP 200, `https://project-tango.schubert.life`
  returns HTTP 200, the LiveKit worker registers successfully, and browser QA
  shows the public frontend with all seven personas.
- Public API QA for Goal 4 is accepted: authoritative Cloudflare DNS resolves
  `tango-api.schubert.life`, and `curl --resolve` through both Cloudflare edge
  A records returns `ok` from `https://tango-api.schubert.life/healthz`.
- Goal 5 local syntax checks pass for the edited backend modules:
  `python3 -m py_compile backend/main.py backend/db.py backend/history.py
  backend/jarvis_agent.py backend/personas.py`.
- Goal 5 local and Schubert frontend production builds pass with the history
  drawer and same-origin history proxy routes.
- Goal 5 Schubert migration is applied: `tango.sessions` and `tango.turns`
  exist under the `tango` schema; `asyncpg` and `slowapi` are installed in the
  backend venv.
- Goal 5 service QA confirmed `tango-backend.service` initializes the DB pool,
  Uvicorn runs on `127.0.0.1:8030`, and the LiveKit worker registers.
- Goal 5 browser QA on `https://project-tango.schubert.life` confirmed the
  History drawer empty state, History button hidden during an active session,
  session list with persona/date/duration/tokens, and detail transcript view
  with ordered agent/user/agent turns.
- Goal 5 persistence QA recorded two Damian sessions and six turns in
  PostgreSQL. The latest session was
  `4dd109c1-c329-4989-8189-5f72fa8efff7`, duration `17s`, total tokens `189`,
  with the transcript turn "Please answer in one calm sentence about taking a
  pause."
- Goal 5 API QA confirmed `/api/history` and `/api/history/{session_id}` work
  on `127.0.0.1:8030` and through both Cloudflare edge IPs for
  `tango-api.schubert.life`.
- Goal 5 regression QA after the close-path hardening recorded and closed Chris
  session `f9be8d70-0dd1-49fd-b15f-c50a3f8d4edd`: browser QA showed the
  public app loaded, all seven personas were present, Chris/general-info started,
  the greeting transcript appeared, History was hidden while active and visible
  after End Call, and `/api/history/{session_id}` returned the ordered agent
  turn "Chris (British) is online. How can I help?"
- Audio optimization constructor QA on Schubert confirmed the deployed LiveKit
  plugin accepts the supported settings: `deepgram.STT` reports
  `endpointing_ms=300` and `smart_format=True`; `elevenlabs.TTS` constructs for
  Damian, Chris, Jeremiah, Jacob, Mama Lulu, Nathaniel, and Tita with `eleven_flash_v2_5`,
  `streaming_latency=3`, `auto_mode=True`, and `use_speaker_boost=False`.
- Goal 5 DB error QA temporarily renamed the `tango` schema; `/api/history`
  returned only `{"error":"Database error"}` with HTTP 500, then recovered after
  restoring the schema.

## Deferred

- iOS native app.
- User authentication/session ownership for history.
- Transcript search, filtering, export, and admin operations.
- Current-info retrieval tools for time-sensitive questions. Recommended shape:
  keep persona LLM routing stable, add small tools for live web/news/project
  facts, and optionally route those tools through Grok or another LiteLLM alias.
- New LiteLLM/Ollama service changes.
- Frontend Caddy block creation.
- Edits to `polyglot-*`, `meetscribe-*`, `project-foxtrot-*`, Ollama overrides, or
  `/opt/polyglot/services/litellm/litellm_config.yaml`.
