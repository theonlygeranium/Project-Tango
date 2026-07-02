# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

---

## [Unreleased]

### Added
- SPEC-004 F5-TTS Jeremiah pilot: added a localhost-only `tango-tts.service`
  sidecar on `127.0.0.1:8020`, an F5-TTS FastAPI server, a Jeremiah reference
  audio extraction script, and an idempotent setup helper for Schubert's cu128
  PyTorch/F5-TTS venv. The helper defaults to PyTorch `2.9.1+cu128` for
  Schubert's Python 3.14 runtime.
- The Jeremiah reference extractor falls back to existing ElevenLabs voice
  sample audio when that voice is not fine-tuned for text-to-speech generation,
  and transcribes that sample with Deepgram before F5-TTS synthesis.

### Changed
- Jeremiah now routes TTS through the local F5-TTS adapter when
  `TANGO_F5_TTS_ENABLED=true`; all other personas remain on ElevenLabs Flash
  v2.5, and Jeremiah can fall back to ElevenLabs by disabling the pilot env flag.
- Deployment, preflight, setup, architecture, and recovery docs now include the
  `tango-tts.service` sidecar and localhost port `8020`.
- Generated `tts-voices/` F5-TTS reference artifacts are now ignored by git.
- The deploy script now builds and copies Next.js frontend artifacts as
  `z121532` so `.next` remains writable by the `tango-web.service` user.
- The Jeremiah reference extractor now saves a short, aligned reference clip
  instead of a long excerpt whose transcript can drift from F5-TTS preprocessing.

### Fixed
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
