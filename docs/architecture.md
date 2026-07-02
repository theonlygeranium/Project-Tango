# Project Tango — System Architecture

> Keep this document in sync with the actual state of Schubert. Do not add aspirational content.
> Last updated: 2026-07-02 — Jeremiah local Qwen + F5-TTS routing

---

## Overview

Project Tango is a real-time AI voice agent platform. Users visit a web interface, select a persona, and have a live voice conversation. Audio flows through LiveKit's WebRTC infrastructure, speech is transcribed by Deepgram, the LLM generates a response through LiteLLM, and the configured persona TTS backend synthesizes the reply as speech.

All compute runs on Schubert, a privately owned AI workstation. No managed cloud inference is used — all LLM requests proxy through the existing LiteLLM service on Schubert.

---

## Network Topology

```
Internet User (browser)
        │  HTTPS
        ▼
Cloudflare Edge
        │  Cloudflare Tunnel (schubert-foxtrot)
        │  project-tango.schubert.life  →  localhost:3006
        │  tango-api.schubert.life      →  localhost:8030
        ▼
Schubert Nexus (192.168.86.77 / Tailscale)
        │
        ├── tango-web.service (port 3006)
        │     Next.js 15 standalone server
        │
        └── tango-backend.service (port 8030)
              FastAPI: /api/connection-details, /api/dispatch, /api/history/*
              LiveKit Agent Worker: voice pipeline per room
        └── tango-tts.service (127.0.0.1:8020)
              FastAPI F5-TTS sidecar for Jeremiah pilot only
```

---

## Voice Pipeline (per session)

```
User microphone
        │  WebRTC audio track
        ▼
LiveKit Cloud  (wss://project-tango-0xs3szq3.livekit.cloud)
        │  Audio frames
        ▼
Deepgram STT plugin (inside LiveKit Agent Worker on Schubert)
        ├── English personas → flux-general-en (Flux STTv2)
        │     Native end-of-turn detection, ~80ms latency
        └── Tagalog personas → nova-3, language="tl", smart_format=True
              Correct Taglish orthography and comprehension
        │  Transcribed text
        ▼
LiveKit AgentSession (turn_handling={"turn_detection": "stt"})
        │  User message
        ▼
LLM via LiteLLM proxy (localhost:4000)
        ├── local/qwen3-fast    →  Ollama qwen3.6:latest (GPU inference)
        └── writer/palmyra-x5-voice  →  WRITER Palmyra X5 (cloud API)
        │  LLM response text
        ▼
TTS routing
        ├── Jeremiah pilot → F5-TTS sidecar (127.0.0.1:8020)
        │     Reference voice: /opt/Project-Tango/tts-voices/jeremiah_reference.wav
        └── All other personas → ElevenLabs Flash v2.5 (api.us.elevenlabs.io)
        │  use_tts_aligned_transcript=False  (prevents race condition pauses)
        │  Audio stream
        ▼
LiveKit Cloud  (audio track back to browser)
        │
        ▼
User speakers
```

---

## Services on Schubert

### Project Tango Services

| Service | Unit | Port | Path |
|---|---|---|---|
| Backend | `tango-backend.service` | 8030 | `/opt/Project-Tango/backend/` |
| F5-TTS sidecar | `tango-tts.service` | 8020 localhost only | `/opt/Project-Tango/tts_server/` |
| Frontend | `tango-web.service` | 3006 | `/opt/Project-Tango/frontend/.next/standalone/` |

### Shared Schubert Services (do not modify)

| Service | Unit | Port | Notes |
|---|---|---|---|
| LiteLLM Proxy | `polyglot-litellm.service` | 4000 | Shared LLM gateway |
| Ollama | `ollama.service` | 11434 | GPU model serving — never call directly |
| PostgreSQL 18 | `postgresql@18-main.service` | 5432 | Tango uses schema `tango` |
| Caddy | `caddy.service` | 80/443 | Shared reverse proxy |
| Cloudflared | `cloudflared.service` | — | Tunnel manager |
| Tailscale | `tailscaled.service` | — | Remote access |

---

## Database Schema

Schema: `tango` (PostgreSQL 18)

### `tango.sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `persona` | TEXT | e.g. `therapy`, `general-info` |
| `room_name` | TEXT | LiveKit room name |
| `started_at` | TIMESTAMPTZ | Session start |
| `ended_at` | TIMESTAMPTZ | NULL for active/orphaned sessions |
| `duration_seconds` | INT | Computed on close |

### `tango.turns`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `session_id` | UUID | FK → `tango.sessions.id` |
| `role` | TEXT | `user` or `assistant` |
| `content` | TEXT | Transcript text |
| `created_at` | TIMESTAMPTZ | Turn timestamp |

**Orphan guard:** History API filters with `WHERE ended_at IS NOT NULL` to hide sessions that never properly closed.

---

## Personas

| Persona Key | Display Name | TTS Backend | LLM Alias | STT Model | Language |
|---|---|---|---|---|---|
| `therapy` | Damian | ElevenLabs `QF9HJC7XWnue5c9W3LkY` | `local/qwen3-fast` | Flux | `en-US` |
| `general-info` (Chris) | Chris (British) | ElevenLabs `HfRP3cIhYLmeNHeTvkWK` | `writer/palmyra-x5-voice` | Flux | `en-US` |
| `general-info` (Jeremiah) | Jeremiah | F5-TTS pilot, reference from `EqHdTYoEuDQCxN1CVbi0` | `local/qwen3-fast` | Flux | `en-US` |
| `general-info` (Jacob) | Jacob | ElevenLabs `qYwy2TckibCF9cBuhI46` | `local/qwen3-fast` | Flux | `en-US` |
| `meditation` | Nathaniel | ElevenLabs `pFQStpMdprGFILRDrWR2` | `local/qwen3-fast` | Flux | `en-US` |
| `pinoy-pride` (Mama Lulu) | Mama Lulu | ElevenLabs `LF1xMOq6fDVEBEkLP0HO` | `local/qwen3-fast` | Nova-3 | `tl` |
| `pinoy-pride` (Tita Baby) | Tita Baby | ElevenLabs `smYFzUb4yrSqprnml7n5` | `local/qwen3-fast` | Nova-3 | `tl` |

---

## Frontend Architecture

- **Framework:** Next.js 15 (App Router, standalone build)
- **LiveKit integration:** `@livekit/components-react`
- **Session flow:**
  1. User selects persona → stored in localStorage
  2. `useConnectionDetails` fetches `/api/connection-details` (gated by `personaStorageReady`)
  3. `room.connect()` establishes WebRTC session
  4. Frontend calls `POST /api/dispatch` to deploy agent into room
  5. Voice chat active — History drawer hidden during session
  6. User clicks End Call → `clearConnectionDetails()` → ready for next persona

---

## Backend Architecture

- **Framework:** FastAPI + `uvicorn`
- **Production runner:** `run_production.py` — starts both FastAPI and LiveKit worker
- **Key endpoints:**
  - `GET /healthz` — health check
  - `POST /api/connection-details` — generates LiveKit access token with persona metadata
  - `POST /api/dispatch` — dispatches LiveKit agent worker into the room
  - `GET /api/history/sessions` — paginated session list (ended sessions only)
  - `GET /api/history/sessions/{id}` — session detail with turns

---

## CI/CD Pipeline

```
git push → GitHub
        └── .github/workflows/deploy.yml  (workflow_dispatch trigger)
                        │  Tailscale SSH to Schubert
                        ▼
                Schubert (as z121532):
                  git pull origin main
                  venv/bin/pip install -r requirements.txt
                  npm run build (frontend)
                  cp static assets into standalone
                  systemctl restart tango-backend tango-web
```

---

## Key Architectural Decisions

See `docs/decisions/` for full ADRs.

| Decision | Rationale | ADR |
|---|---|---|
| LiveKit Agents SDK (not Pipecat) | Native WebRTC, active development | ADR-001 |
| Flux STT for English | Native EOT detection, lowest latency | ADR-002 |
| Nova-3 `tl` for Tagalog | Flux Multilingual doesn't support Tagalog | ADR-003 |
| `use_tts_aligned_transcript=False` | Prevents mid-speech pause race condition | ADR-004 |
| Cloudflare tunnel direct to localhost | Bypasses Caddy, prevents Error 522 | ADR-005 |
| POST /api/dispatch after room.connect() | Prevents agent timeout on empty rooms | ADR-006 |
| LiteLLM proxy for all LLM calls | Centralized credentials, model switching | ADR-007 |
| F5-TTS sidecar for Jeremiah pilot | Self-hosted TTS without disrupting other personas | ADR-008 |
