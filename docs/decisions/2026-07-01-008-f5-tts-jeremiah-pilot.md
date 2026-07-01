# ADR-008: Pilot F5-TTS as a Local Jeremiah TTS Sidecar

**Date:** 2026-07-01
**Status:** Accepted
**Decided by:** Codex (OpenAI Codex)

## Context

Project Tango currently uses ElevenLabs Flash v2.5 for all persona speech. SPEC-004 asks for a non-destructive self-hosted TTS pilot using Jeremiah's existing ElevenLabs voice as reference audio. Schubert has a Blackwell NVIDIA GPU, but existing services on ports 3006, 8030, 4000, 8010, and 3010 must remain undisturbed.

## Decision

Run F5-TTS as a dedicated FastAPI sidecar named `tango-tts.service`, bound only to `127.0.0.1:8020`. Jeremiah is the only persona with `tts_backend="f5-tts"`. All other personas continue to use ElevenLabs. The backend uses a LiveKit-compatible non-streaming TTS adapter that requests WAV audio from the sidecar and emits it through LiveKit's `AudioEmitter`.

## Rationale

- Keeps the experimental voice engine isolated from the main backend process.
- Preserves existing ElevenLabs behavior for every non-pilot persona.
- Keeps port 8020 private to localhost and avoids public Caddy/Cloudflare exposure.
- Allows rollback by disabling `TANGO_F5_TTS_ENABLED` or removing Jeremiah's `tts_backend` flag.
- Lets the F5-TTS venv use Blackwell-compatible cu128 PyTorch without changing the backend venv.

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Embed F5-TTS inside `tango-backend.service` | Model load and CUDA dependencies would make the core backend heavier and risk all personas |
| Expose F5-TTS through Caddy or Cloudflare | Not required; only Tango backend needs access |
| Switch all personas to F5-TTS | SPEC-004 is a Jeremiah-only pilot |
| Use Coqui XTTS or another engine | SPEC-004 explicitly selects F5-TTS |

## Consequences

- `tango-tts.service` must be installed and healthy for Jeremiah's F5 route.
- `/opt/tts-lab/f5-venv` is a new isolated runtime dependency on Schubert.
- `/opt/Project-Tango/tts-voices/jeremiah_reference.wav` must exist before enabling the pilot.
- If F5-TTS quality or latency is poor, Jeremiah can fall back to ElevenLabs without affecting other personas.

## References

- `docs/SPEC-004-F5TTS.md`
- `tts_server/main.py`
- `backend/main.py`
