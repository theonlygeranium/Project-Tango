# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Commit messages follow [Conventional Commits](https://www.conventionalcommits.com/).

---

## [Unreleased]

### Fixed
- Fixed Admiral Schubert voice bot DAVE encryption handling. Three root causes
  were identified and resolved:
  1. DAVE DecryptionFailed exception: At ~packet #23, DAVE transitions send
     unencrypted packets causing DecryptionFailed(UnencryptedWhenPassthroughDisabled).
     Now caught gracefully — returns raw data and continues processing instead of
     killing the audio pipeline.
  2. Opus decoder crash on invalid data: 3-byte DAVE transition markers and
     corrupted packets from DecryptionFailed fallbacks were fed directly to the
     Opus decoder, causing uncaught exceptions that killed the audio thread after
     1 frame. Added _safe_decode() wrapper that catches decode errors and returns
     silence PCM (3840 zero bytes) instead of crashing.
  3. VAD threshold too high: User speech measured at rms=173.0 but threshold was
     300, so speech was never detected. Lowered VAD_SPEECH_RMS_THRESHOLD from 300
     to 100. Confirmed working: speech at rms=6383-10963, silence at rms=44-94.
- Added diagnostic logging to VoiceAudioSink.write() — logs first 10 audio frames
  then every 100th frame with user, pcm_len, and state for pipeline debugging.

### Added
- Added scripts/patches/patch_dave_opus.py: reproducible patch script that
  applies the DAVE decryption fix to discord-ext-voice-recv's opus.py in the
  venv. Re-apply after venv rebuild or discord-ext-voice-recv reinstall.
  Patches _dave_decrypt(), _dave_log(), and _safe_decode() methods.

### Added
- Added Discord voice channel support to Admiral Schubert bot. The bot can
  now join voice channels via !join, receive speech with discord-ext-voice-recv,
  transcribe with Deepgram Nova-3, reason via writer/claude-sonnet-4-5, and
  respond with ElevenLabs Flash v2.5 TTS. Includes energy-based VAD for turn
  detection, PCM format conversion (48kHz stereo to 16kHz mono via ffmpeg),
  echo cancellation (bot stops listening while speaking), auto-disconnect when
  admin leaves, and !leave command. Installed PyNaCl 1.5.0 and
  discord-ext-voice-recv 0.5.3a180 (with DAVE encryption support).
- Added Admiral Schubert nautical personality to Schubert Bot. The system
  prompt now defines Admiral Schubert as a distinguished Maine Coon cat of
  high naval rank who commands the Schubert server as a ship. The bot
  addresses the user as "Captain", uses nautical terminology, and refers
  to services as "vessels" or "the fleet". Technical precision is
  preserved — the persona enhances communication without affecting
  diagnostic accuracy. Updated help text and on_ready log message to
  match the persona.
- Deployed Tango Health Guardian: a six-layer self-healing health monitor that
  runs as a systemd timer every 3 minutes. Checks service health, endpoint health,
  ElevenLabs billing status, TTS synthesis, log anomalies, and LiveKit worker
  registration. Auto-restarts inactive services (with 10-minute cooldown), alerts
  on billing issues, and verifies Deepgram Aura fallback is active. Log at
  /var/log/tango-healthcheck.log.
- Added Discord webhook notifications to the Health Guardian. Alerts for WARN
  and CRITICAL events are sent to the configured Discord channel via webhook.
  The webhook URL is stored in .env (DISCORD_WEBHOOK_URL), not committed to source.
- Added Tango Discord Bot: a Level 1 command bot that runs as a systemd service
  and responds to fixed commands (!status, !health, !logs, !restart, !billing,
  !tts, !help) from the configured admin user in the configured channel.
  Includes rate limiting, restart confirmation, and full audit logging.
  Bot token and credentials stored in .env, not committed to source.
- Added Schubert Bot: a Level 3 server-wide autonomous Discord agent with
  full access to all Schubert services and projects. Powered by
  writer/claude-sonnet-4-5 via LiteLLM. Includes server monitoring tools
  (!status, !services, !disk, !mem, !procs, !net), broader guardrails
  (critical service restarts require confirmation), and a new Discord bot
  application (Admiral Schubert#5041). Credentials stored in .env as
  SCHUBERT_BOT_*. Running as schubert-bot.service.
- Upgraded Tango Discord Bot to Level 3 autonomous agent. The bot now uses
  writer/claude-sonnet-4-5 via LiteLLM for reasoning, with a full agentic
  tool-use loop (run_shell, write_file, health_check). Natural language
  messages trigger autonomous investigation, code fixes, service restarts,
  and git commits. Guardrails include hard blocks (rm -rf, mkfs, dd, forbidden
  services, AGENTS.md, .env, git push to main, package installs, shutdown),
  confirmation gates (git push only), loop safety (max 20 iterations, 5-min
  timeout), and full audit logging to /var/log/tango-discord-agent.log.
  Level 1 quick commands (!status, !health, etc.) remain available without
  LLM cost.

### Changed
- Switched turn detection from STT-based (turn_detection="stt") to LiveKit's audio
  TurnDetector (inference.TurnDetector()). The audio turn detector processes user
  audio directly - intonation, pitch, rhythm - for state-of-the-art end-of-turn
  accuracy without relying on STT transcript timing. This eliminates the recurring
  "stt end of speech received while vad is still in a speech segment" VAD/STT race
  condition that appeared on every user utterance. Tagalog personas (Mama Lulu,
  Tita Baby) remain on Nova-3 endpointing via the existing turn_detection pop.
- Disabled vision context for audio-only sessions (TANGO_VISION_ENABLED=false).
  The vision pipeline was initializing on every turn and requesting video frames
  that never arrive in audio-only sessions, wasting per-turn overhead on
  gpt-4o-mini calls that immediately fail with no video frame available.
- Tuned Silero VAD parameters to eliminate STT/VAD race condition:
  min_silence_duration reduced from 550ms to 300ms and prefix_padding_duration
  from 500ms to 300ms. Deepgram Flux fires end-of-speech before the VAD finishes
  its speech segment at the default 550ms silence threshold, causing the recurring
  stt end of speech received while vad is still in a speech segment warning.
- Stopped idle F5-TTS sidecar (tango-tts.service). All personas now route to
  ElevenLabs, so the F5-TTS sidecar was consuming 2GB RAM for no active work.
  The lazy-start mechanism will revive it if a persona is routed back to F5-TTS.
- Jeremiah now routes TTS back to ElevenLabs (tts_backend="elevenlabs") now
  that the ElevenLabs billing is resolved. The F5-TTS sidecar remains available
  as a lazy-start option via TANGO_F5_TTS_ENABLED, but is no longer the primary
  voice engine for any persona. All seven personas now use ElevenLabs Flash v2.5
  as their primary TTS engine, with Deepgram Aura remaining as the automatic
  fallback if ElevenLabs fails again.
- Jeremiah's system prompt updated to reference his ElevenLabs voice engine
  instead of self-hosted F5-TTS.

### Added
- Deepgram Aura TTS fallback: when the primary TTS engine (ElevenLabs or
  F5-TTS) fails to produce audio, the backend automatically retries the same
  text on Deepgram Aura using the existing DEEPGRAM_API_KEY. Each persona maps
  to a gender-appropriate Aura v2 voice so the fallback still sounds distinct.
  Controlled by `TANGO_TTS_FALLBACK` (default: enabled).
- F5-TTS lazy-start: the backend now auto-starts `tango-tts.service` on demand
  when a Jeremiah synthesis request arrives and the sidecar is stopped, instead
  of requiring it to run continuously. Controlled by `TANGO_F5_TTS_AUTO_START`
  (default: enabled) with `TANGO_F5_TTS_START_TIMEOUT_SECONDS` (default: 600).
- `scripts/tango-tts-idle-stop.sh`: a cron-friendly script that stops the
  F5-TTS sidecar after a configurable idle period (default 45 minutes) to
  conserve GPU memory. Tracks last-synthesis time via an activity stamp file.
- F5-TTS activity stamp: `tts_server/main.py` now touches an activity stamp
  file (`/tmp/tango-tts-last-synthesize`) at the start and end of each
  synthesis request so the idle-stop script can track real usage.
- The account administration dashboard now includes a responsive persona model
  map sourced from the live admin catalog, with allowlisted-model summaries,
  current default LLM/provider assignments, TTS/STT pipelines, and soft pulsing
  route glows.
- Admin-only persona model controls on the main Tango interface now show each
  persona's source default and offer every backend-allowlisted model in a
  compact dropdown with a soft, persona-colored pulsing glow.
- Password-only user accounts with Argon2id verification, keyed credential
  lookup, opaque database sessions, persistent login throttling, CSRF defense,
  and a one-time administrator bootstrap command.
- A responsive dark-mode `/admin` dashboard for regular-user provisioning,
  profile editing, account activation, generated-password reset, persona access,
  and per-persona default or allowlisted model policy.
- PostgreSQL migration `004` for accounts, persona policy, auth sessions,
  room grants, audit events, and account ownership on history and memory.
- Same-origin Next.js API routes for authentication, persona catalog, LiveKit
  tokens and dispatch, history, memory, and administration.
- Groq Llama 4 Scout is now a source-controlled LiteLLM alias for Tango, and a
  universal Layer 1 voice-interface prompt is prepended to every persona.
- SPEC-004 F5-TTS Jeremiah pilot: added a localhost-only `tango-tts.service`
  sidecar on `127.0.0.1:8020`, an F5-TTS FastAPI server, a Jeremiah reference
  audio extraction script, and an idempotent setup helper for Schubert's cu128
  PyTorch/F5-TTS venv. The helper defaults to PyTorch `2.9.1+cu128` for
  Schubert's Python 3.14 runtime.
- The Jeremiah reference extractor falls back to existing ElevenLabs voice
  sample audio when that voice is not fine-tuned for text-to-speech generation,
  and transcribes that sample with Deepgram before F5-TTS synthesis.

### Changed
- `scripts/deploy.sh` now disables `tango-tts.service` by default and leaves it
  stopped after deploy, relying on the backend's lazy-start mechanism. Set
  `TANGO_F5_TTS_START_ON_DEPLOY=true` to start it eagerly during deploy instead.
- Admin per-persona model choices are remembered in local browser storage and
  sent as session-specific overrides; regular users retain the simpler
  persona-only interface and server-resolved account policy.
- Conversation history, open loops, and injected memories are now isolated by
  authenticated account ID. LiveKit tokens and dispatch grants bind the same
  account, persona, and effective model server-side.
- Regular users now see only assigned personas and cannot choose models. Admin
  policy resolves every default or override against the backend LiteLLM
  allowlist.
- Deployment now refuses dirty Schubert checkouts, uses the correct self-hosted
  runner label, serializes deploys without interrupting in-progress migrations,
  fast-forwards Git noninteractively, applies checksum-ledgered migrations, and
  builds only same-origin API config.
- Mama Lulu and Tita Baby now default to `groq/llama4-scout` while retaining
  Deepgram Nova-3 monolingual Tagalog speech recognition.
- Jeremiah now routes TTS through the local F5-TTS adapter when
  `TANGO_F5_TTS_ENABLED=true`; all other personas remain on ElevenLabs Flash
  v2.5, and Jeremiah can fall back to ElevenLabs by disabling the pilot env flag.
- Jeremiah now defaults to the local LiteLLM alias `local/qwen3-fast` while
  keeping F5-TTS for the self-hosted voice route.
- Jeremiah's voice-session prompt now avoids describing the live agent as
  text-only and keeps model answers grounded in the active LiteLLM route and
  F5-TTS voice engine.
- Jeremiah now passes Deepgram keyterms for his name and model vocabulary to
  improve recognition of phrases like `Jeremiah`, `Qwen`, and `Project Tango`.
- Deployment, preflight, setup, architecture, and recovery docs now include the
  `tango-tts.service` sidecar and localhost port `8020`.
- Generated `tts-voices/` F5-TTS reference artifacts are now ignored by git.
- The deploy script now builds and copies Next.js frontend artifacts as
  `z121532` so `.next` remains writable by the `tango-web.service` user.
- The Jeremiah reference extractor now saves a short, aligned reference clip
  instead of a long excerpt whose transcript can drift from F5-TTS preprocessing.

### Fixed
- Voice agents producing no audio when ElevenLabs billing is past_due or the
  F5-TTS sidecar is stopped: the new Deepgram Aura TTS fallback ensures every
  persona can still speak when its primary TTS engine fails, preventing the
  `APIError: no audio frames were pushed` error that previously silenced all
  voice agents.
- Long backend model names wrap inside the admin model summary rail instead of
  hiding their qualifier at desktop widths.
- Compact admin persona controls use readable short model names in the card
  while retaining full backend labels in the dropdown and accessible name.
- The admin footer now follows the expanded persona grid, and its decorative
  appreciation widget is omitted so neither can cover model controls on short
  viewports.
- Anonymous protected-page redirects now use Tango's configured public origin
  instead of Next.js's localhost listener origin behind Caddy and Cloudflare.
- Restored the GitHub deployment path by matching the runner's actual
  `schubert` label instead of its display name.
- Standalone deployment continues copying Next.js static and public assets so
  authenticated pages retain CSS and JavaScript after each build.
- Completed the persona grid's model-selection wiring and consolidated its model
  imports so the production frontend type-check passes cleanly.
- Formatted the persona selector's imports and utility classes so the
  production Next.js build passes Prettier validation.
- Restored Jeremiah's F5-TTS reference extractor after commit `a657411b`
  encoded it as non-executable Python, and now build the runtime reference from
  the uploaded ElevenLabs source sample with Deepgram transcript validation
  while respecting the deployed F5-TTS 12-second preprocessing limit.
- The F5-TTS sidecar now calls the installed `f5_tts.api.F5TTS.infer()`
  method instead of the unavailable sketch `generate()` method from the design
  spec.
- The F5-TTS sidecar now fails fast with a setup error when Jeremiah's reference
  transcript is missing instead of invoking F5-TTS's internal ASR path.
- The F5-TTS sidecar now shims local WAV loading through `soundfile` to avoid
  `torchaudio`/`torchcodec` requiring unavailable `libnvrtc.so.13` on Schubert.
- F5-TTS synthesis now passes a Python-compatible bounded seed to prevent
  spawned helper processes from inheriting an invalid `PYTHONHASHSEED`.
- Jeremiah F5-TTS output clarity now depends on a transcript matched to the
  actual short reference audio, preventing valid PCM output from sounding like
  garbled non-words.
- The LiveKit F5-TTS adapter now rejects unreadable WAV data instead of falling
  back to pushing container bytes as raw PCM.
- Preserved the live Schubert 0-token history flush guard by waiting briefly for
  final LiveKit usage events before closing a history session.

### Security
- All application APIs except `/healthz` now require a valid database session;
  admin and mutation routes add role, exact-origin, and double-submit CSRF
  enforcement.
- Plaintext generated passwords are returned only on create/reset, are never
  stored or audited, and a reset or deactivation revokes web sessions and voice
  grants, removes connected LiveKit participants, and is reinforced by periodic
  worker-side account checks.
- Argon2 verification concurrency is bounded, and failed-login counters now use
  atomic database increments so simultaneous attempts cannot lose throttle data.

---

## [1.0.0] - 2026-06-28 — Stable Baseline `v1.0-stable`

### Added
- Stable baseline tag `v1.0-stable` at commit `fdc9144` — first fully verified human-tested release (2026-06-28)
- `REVERT.md` — comprehensive rollback guide documenting stable baseline and recovery procedures (2026-06-28)
- `docs/architecture.md` — full system architecture documentation (2026-06-28)
- `docs/setup.md` — step-by-step deployment guide with verification commands (2026-06-28)
- `docs/decisions/` — Architectural Decision Records for all key technical decisions (ADR-001 through ADR-007) (2026-06-28)
- `docs/runbooks/` — operational runbooks: RB-01 rollback, RB-02 service recovery, RB-03 deploy new version (2026-06-28)
- AGENTS.md — full multi-agent collaboration contract with Schubert service boundaries (2026-06-28)

### Fixed
- Tagalog STT: switched Tita Baby and Mama Lulu from `nova-3-multi` (phonetic fallback) to `nova-3` monolingual `language="tl"` with `smart_format=True` for correct Taglish orthography (2026-06-28)
- Mid-speech pauses: disabled `use_tts_aligned_transcript` in `AgentSession` to resolve `_SegmentSynchronizerImpl` race conditions with ElevenLabs alignment events (2026-06-27)
- Turn detection deprecation: moved `turn_detection="stt"` into `turn_handling` dict to comply with LiveKit Agents v2.0 API (2026-06-27)
- Audio pipeline: migrated English STT to Deepgram Flux (`flux-general-en`) for native end-of-turn detection (2026-06-26)
- ElevenLabs TTS: added US geographic routing (`api.us.elevenlabs.io`) to reduce latency (2026-06-26)
- Keyterm boosting: added Taglish keyterms for Tita Baby and Mama Lulu (2026-06-26)

## [0.5.0] - 2026-06-25

### Added
- Tita Baby persona: renamed from "Tita" and assigned "Ultimate Filipina Tita" system prompt (2026-06-25)
- Jeremiah identity: hardcoded intro and biographical context (2026-06-25)
- Mobile/iOS optimization: viewport-fit=cover, theme-color, PWA manifest, apple-touch-icon, touchmove support, two-column persona grid (commit `ddc8368`) (2026-06-25)

### Fixed
- Persona switching: added `clearConnectionDetails` on session end to prevent stale LiveKit token reuse (2026-06-24)

## [0.4.0] - 2026-06-24

### Added
- Agent dispatch: added `POST /api/dispatch` backend endpoint; frontend calls dispatch after `room.connect()` (2026-06-24)
- Cloudflare tunnel routing: updated `schubert-foxtrot` ingress to route directly to `localhost:3006` and `localhost:8030`, bypassing Caddy (2026-06-23)
- DNS: set both subdomains as CNAME records pointing to Cloudflare tunnel address (2026-06-23)

### Fixed
- Notes duplication: three-part fix for phantom sessions — enabled gate in `useConnectionDetails.ts`, `personaStorageReady` gate in `app.tsx`, `WHERE ended_at IS NOT NULL` filter in `history.py` (2026-06-23)

## [0.3.0] - 2026-06-23

### Added
- Conversation history: PostgreSQL 18 schema `tango` with session and turn recording using `asyncpg` and FastAPI (2026-06-23)
- History drawer UI: session list and detail view in frontend (2026-06-23)

### Fixed
- CI/CD pipeline: removed `sudo` from `git pull` (git 2.35.2+ cross-owner rejection) (2026-06-22)
- CI/CD pipeline: replaced `docker compose` with `systemd` restarts in `deploy.sh` (2026-06-22)
- CI/CD pipeline: use venv pip instead of system pip (PEP 668) (2026-06-22)
- Backend: fixed `streaming_latency` kwarg in ElevenLabs TTS constructor (2026-06-22)

## [0.2.0] - 2026-06-22

### Added
- All 7 personas deployed: Damian, Chris, Jeremiah, Jacob, Mama Lulu, Nathaniel, Tita (2026-06-22)
- ElevenLabs Flash v2.5 TTS with per-persona VoiceSettings (2026-06-22)
- Deepgram Nova-3 STT with `endpointing_ms=300` and `smart_format=True` (2026-06-22)
- Caddy route: `tango-api.schubert.life` → backend port 8030 (2026-06-22)
- GitHub Actions CI/CD with Tailscale SSH deploy pipeline (2026-06-22)
- systemd units: `tango-backend.service` (port 8030), `tango-web.service` (port 3006) (2026-06-22)

## [0.1.0] - 2026-06-22

### Added
- Initial project scaffolding provisioned by WRITER Agent via Schubert Project Provisioning playbook (2026-06-22)
- Fork of AURA (`AppajiDheeraj/AURA`) as starting point (2026-06-22)
- Foundation files: README, CHANGELOG, AGENTS.md (2026-06-22)
- LiveKit Agents SDK (`livekit-agents`) integration — explicit rejection of Pipecat framework (2026-06-22)
- Backend: FastAPI token API + LiveKit worker on port 8030 (2026-06-22)
- Frontend: Next.js 15 WebRTC UI on port 3006 (2026-06-22)
- LiteLLM proxy integration at `localhost:4000` — no direct Ollama calls (2026-06-22)

---

[Unreleased]: https://github.com/theonlygeranium/Project-Tango/compare/v1.0-stable...HEAD
[1.0.0]: https://github.com/theonlygeranium/Project-Tango/releases/tag/v1.0-stable