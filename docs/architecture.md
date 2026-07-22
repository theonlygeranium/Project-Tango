# Project Tango — System Architecture

> Keep this document in sync with the actual state of Schubert. Do not add aspirational content.
> Last updated: 2026-07-22 — account authentication, persona authorization, and Groq Tagalog routing

---

## Overview

Project Tango is a real-time AI voice agent platform. Users visit a web interface, select a persona, and have a live voice conversation. Audio flows through LiveKit's WebRTC infrastructure, speech is transcribed by Deepgram, the LLM generates a response through LiteLLM, and the configured persona TTS backend synthesizes the reply as speech.

The application services and local model route run on Schubert, a privately
owned AI workstation. Approved hosted model routes are also available, but all
LLM requests—local or hosted—must pass through Schubert's LiteLLM service.

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
        │     Login + admin UI + authenticated same-origin API routes
        │
        └── tango-backend.service (port 8030)
              FastAPI: accounts, policy, tokens, dispatch, history, memory
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
        ├── local/qwen3-fast         → Ollama qwen3.6:latest (GPU inference)
        ├── writer/palmyra-x5-voice  → WRITER Palmyra X5
        └── groq/llama4-scout        → Groq Llama 4 Scout
        │  LLM response text
        ▼
TTS routing
        ├── Jeremiah pilot → F5-TTS sidecar (127.0.0.1:8020)
        │     Reference voice: /opt/Project-Tango/tts-voices/jeremiah_reference.wav
        │     Runtime reference: short source-sample clip plus matched transcript
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
| `user_id` | UUID | Owning account; FK to `tango.users` |
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

### Account and authorization tables

| Table | Purpose |
|---|---|
| `tango.users` | Profile, role, Argon2id hash, keyed password lookup, active state |
| `tango.user_persona_access` | Enabled personas and optional allowlisted LLM override per user |
| `tango.auth_sessions` | Digests of opaque session and CSRF tokens with idle/absolute expiry |
| `tango.auth_rate_limits` | Persistent failed-login throttling by network and credential digest |
| `tango.voice_room_grants` | Short-lived account/persona/model binding for LiveKit dispatch |
| `tango.admin_audit_log` | Non-secret account administration audit events |
| `tango.schema_migrations` | Applied migration filename and checksum ledger |

`tango.memories.user_id` and `tango.sessions.user_id` are mandatory for new web
voice sessions. History, open loops, and prompt memory are filtered by that
owner. Legacy rows are adopted by the initial admin during bootstrap.

---

## Personas

| Persona Key | Display Name | TTS Backend | LLM Alias | STT Model | Language |
|---|---|---|---|---|---|
| `therapy` | Damian | ElevenLabs `QF9HJC7XWnue5c9W3LkY` | `local/qwen3-fast` | Flux | `en-US` |
| `general-info` (Chris) | Chris (British) | ElevenLabs `HfRP3cIhYLmeNHeTvkWK` | `writer/palmyra-x5-voice` | Flux | `en-US` |
| `jeremiah` | Jeremiah | F5-TTS pilot, short source-sample reference from `EqHdTYoEuDQCxN1CVbi0` | `local/qwen3-fast` | Flux | `en-US` |
| `jeremiah-v2` | Jeremiah V2 | ElevenLabs | `local/qwen3-fast` | Flux | `en-US` |
| `jacob` | Jacob | ElevenLabs `qYwy2TckibCF9cBuhI46` | `local/qwen3-fast` | Flux | `en-US` |
| `meditation` | Nathaniel | ElevenLabs `pFQStpMdprGFILRDrWR2` | `local/qwen3-fast` | Flux | `en-US` |
| `mama-lulu` | Mama Lulu | ElevenLabs `LF1xMOq6fDVEBEkLP0HO` | `groq/llama4-scout` | Nova-3 | `tl` |
| `pinoy-pride` | Tita Baby | ElevenLabs `smYFzUb4yrSqprnml7n5` | `groq/llama4-scout` | Nova-3 | `tl` |

Every resolved persona receives the universal Layer 1 voice constraints before
its identity-specific prompt. The account policy may retain the default above
or choose another source-allowlisted LiteLLM alias.

---

## Frontend Architecture

- **Framework:** Next.js 15 (App Router, standalone build)
- **LiveKit integration:** `@livekit/components-react`
- **Browser security boundary:** the browser calls only same-origin `/api/*`
  route handlers. Server code forwards the host-only auth cookies to FastAPI.
- **Routes:** `/login` has one password field; `/` hosts Tango; `/admin` is
  server-gated to the admin role.
- **Session flow:**
  1. The server validates the opaque session and loads the user's persona catalog.
  2. The user selects only from assigned personas.
  3. `POST /api/connection-details` checks CSRF and asks FastAPI for a signed,
     account-bound LiveKit token and short-lived room grant.
  4. `room.connect()` establishes the WebRTC session.
  5. `POST /api/dispatch` atomically consumes the same user's room grant.
  6. Voice history and memory are recorded under the signed account ID.

---

## Backend Architecture

- **Framework:** FastAPI + `uvicorn`
- **Production runner:** `run_production.py` — starts both FastAPI and LiveKit worker
- **Password verification:** Argon2id plus keyed HMAC lookup for the one-field login
- **Web session:** opaque random token; only its SHA-256 digest is stored
- **Cookies:** host-only, `HttpOnly` session plus JS-readable CSRF token;
  `Secure`, `SameSite=Strict`, `Path=/` in production
- **Authorization:** admin dependency for provisioning and server-authoritative
  persona/model policy for token issuance
- **Key endpoints:**
  - `GET /healthz` — health check
  - `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`
  - `/api/admin/*` — admin-only account and policy management
  - `GET /api/personas` — authenticated user's permitted catalog
  - `POST /api/connection-details` — generates LiveKit access token with persona metadata
  - `POST /api/dispatch` — consumes an authenticated room grant and dispatches the worker
  - `GET /api/history` and `GET /api/history/{id}` — owner-scoped ended sessions and turns
  - `/api/memory/open-loops/*` — owner-scoped memory operations

---

## CI/CD Pipeline

```
git push main → GitHub
        └── .github/workflows/deploy.yml
                        │  self-hosted Schubert runner
                        │  Tailscale SSH fallback on explicit request
                        ▼
                Schubert (as z121532):
                  refuse dirty worktree
                  git pull --ff-only origin main
                  venv/bin/pip install -r requirements.txt
                  npm run build (frontend)
                  cp static assets into standalone
                  python backend/migrate.py
                  systemctl restart tango-backend tango-web
```

Production deploys serialize through one concurrency group. An in-progress
deployment is never cancelled during artifact replacement, migration, or
restart; the next queued run fast-forwards to the newest `main`.

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
| Groq Tagalog defaults + universal voice layer | Reproduce current live persona behavior | ADR-009 |
| Password accounts + server persona authorization | Protect every browser/API path and isolate account data | ADR-010 |
