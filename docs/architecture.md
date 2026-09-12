# Project Tango — System Architecture

> Keep this document in sync with the actual state of Schubert. Do not add aspirational content.
> Last updated: 2026-08-20 — Nexus Fleet Model rebuild (v3)

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
        │     Native end-of-turn detection + eager EOT (per-persona threshold)
        │     EagerEndOfTurn → speculative LLM generation (hundreds of ms saved)
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
        │  use_tts_aligned_transcript=False
        │  RoomIO sync_transcription=False  (disables SegmentSynchronizer)
        │  max_tool_steps=8  (wiki/docs/MCP chains)
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
- **Admin inventory:** `/admin` renders its persona/model map from the
  admin-only catalog, including source defaults, allowlisted providers, and the
  current TTS/STT pipeline for every persona. The chart is informational;
  account policy remains editable through the account controls.
- **Persona model controls:** the main interface shows model labels and an
  allowlisted per-persona session dropdown only when the authenticated user is
  an admin. The label always identifies the source default returned by
  FastAPI; a locally remembered selection is sent only as an admin session
  override. Regular users receive neither the controls nor a browser-selected
  model override.
- **Session flow:**
  1. The server validates the opaque session and loads the user's persona catalog.
  2. The user selects only from assigned personas; an admin may additionally
     select an allowlisted model for the chosen persona's next session.
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

## Discord Fleet Bots (configuration)

Discord fleet bots under `scripts/` load tunables from
`/opt/Project-Tango/config/fleet-config.json` (override with `FLEET_CONFIG_PATH`)
via `scripts/fleet_config_loader.py`. Missing or corrupt config falls back to
each script's previous hardcoded defaults — bots must not crash.

Per-bot sections live under `bots.<bot_id>` (e.g. `architect`, `admiral`,
`cortex`). Shared sections: `fleet_protocol`, `conversation`, `context_builder`,
`scheduler`. The JSON file is owned by the Fleet Command API; this repository
does not modify it.

---

## Voice Agent MCP Knowledge Access

Voice personas may access the Schubert MCP servers (the same servers used by the
Discord fleet) via `backend/mcp_tools.py`. The bridge reuses
`scripts/mcp_client.py` and connects at worker startup. Per-persona scoping via
`Persona.enabled_mcp_servers`; a read-only tool allowlist is enforced by
default. Write/destructive tools and the `schubert` shell server are excluded
for end-user-facing personas. Master switch: `TANGO_MCP_TOOLS` (default true).

MCP-enabled personas also receive a product-manager summarization guidance
section in their system prompt, ensuring tool results are reported as
qualitative summaries rather than raw technical output.

| Persona | `enabled_mcp_servers` |
|---------|----------------------|
| Damian (therapy) | `()` — no MCP access |
| Chris (general-info) | `("github", "postgres", "redis")` |
| Jeremiah | `("github", "postgres", "redis")` |
| Jeremiah V2 | `("github", "postgres", "redis")` |
| Jacob | `("github", "postgres")` |
| Nathaniel (meditation) | `()` — no MCP access |
| Mama Lulu | `("postgres",)` |
| Tita Baby | `()` — no MCP access |

See ADR-012 and SPEC-006 for full details.

---

## Control Mode — Voice-Driven Administrative Override

Control Mode lets the user say "Control Mode" mid-conversation to enter an
administrative state where they can adjust the persona's behavior, tone, or
system prompt. Changes persist to PostgreSQL and apply to all future sessions
with that persona. Saying "Exit Control Mode" returns the agent to normal
conversation.

### How It Works

1. **Phrase detection**: The `on_user_turn_completed` hook in `Jarvis`
   inspects each user turn. If the transcribed text matches "Control Mode"
   (case-insensitive, with STT fuzzy variants), the agent enters Control Mode.
   "Exit Control Mode" returns to normal.
2. **Mode switch**: `agent.update_instructions()` swaps the system prompt to
   an administrative prompt. The agent acknowledges the switch and asks what
   to change.
3. **Change application**: The `update_persona_behavior` function tool accepts
   a `change_type` (`tone`, `instruction_addition`, `instruction_replacement`,
   `behavior_rule`) and content. It calls `agent.update_instructions()` for the
   live session and persists to `tango.persona_overrides` for future sessions.
4. **Persistence**: At session start, `get_persona()` loads active overrides
   from PostgreSQL and merges them into the system prompt before the session
   begins.

### Override Merge Strategy

- `instruction_replacement`: replaces the entire persona system prompt (last
  one wins if multiple exist).
- `tone`, `instruction_addition`, `behavior_rule`: appended to the base prompt
  as labeled sections, in creation order.

Master switch: `TANGO_CONTROL_MODE` (default true). See ADR-013.

---

## Programs — Voice-Created Derived Personas

Programs are derived personas that inherit a base persona's voice, TTS, STT,
and MCP tools but replace the system prompt with an LLM-generated one. They let
the user create specialized conversation modes (e.g., "therapy program",
"coding tutor program") without editing source code or restarting services.

### How It Works

1. **Creation**: While in Control Mode, the user asks the agent to create a
   program (e.g., "create a therapy program where you discuss emotional
   wellness"). The `create_program` function tool persists a named program
   with an LLM-generated system prompt to PostgreSQL. Program names are unique
   per base persona (case-insensitive).
2. **Activation**: During normal conversation, the user says "activate [name]
   program". The `on_user_turn_completed` hook detects the activation phrase,
   loads the program from the database, and calls `agent.update_instructions()`
   to swap in the program's prompt (merged with the base persona's
   non-persona-specific preamble). The agent acknowledges the switch.
3. **Deactivation**: The user says "deactivate program" or "return to default"
   to restore the base persona's original instructions.
4. **Listing**: The user can ask "what programs do you have?" and the agent
   uses a `list_programs` function tool to enumerate available programs.
5. **Persistence**: Programs are stored in `tango.programs` and survive
   restarts. They apply to all future sessions with that base persona.

### Activation Flow

```
User: "activate therapy program"
        │
        ▼
on_user_turn_completed hook
        │  detect_program_activation() → ("activate", "therapy")
        ▼
Load program from tango.programs by name + base_persona_id
        │
        ▼
agent.update_instructions(base_preamble + program.system_prompt)
        │
        ▼
Agent acknowledges switch, continues with program prompt
```

### Frontend Program Library

The frontend displays all active programs in a Program Library panel on the
welcome screen, below the PersonaSelector. Programs are grouped by base persona
and rendered as tappable cards showing the program name, description, and base
persona. Tapping a card starts a conversation with the program pre-activated by
passing `program_name` in the connection-details request.

The Program Library is read-only — creation and editing are voice-only via
Control Mode. This keeps the UI simple and avoids needing a complex prompt
editor.

### Database Table

`tango.programs` (migration 007):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, auto-generated |
| `base_persona_id` | VARCHAR(50) | FK to base persona (e.g., `general-info`) |
| `name` | VARCHAR(100) | Unique per persona, case-insensitive |
| `description` | TEXT | User-facing description |
| `system_prompt` | TEXT | LLM-generated prompt replacing the persona prompt |
| `active` | BOOLEAN | Default true; set false to retire a program |
| `created_at` | TIMESTAMPTZ | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | Last modification timestamp |

Index: `idx_programs_persona` on `(base_persona_id, active, created_at DESC)`.

### Key Design Decisions

- **Programs inherit base persona config**: Voice, TTS, STT, MCP tools, and
  EOT settings all come from the base persona. Only the system prompt changes.
- **One program active at a time**: Activating a program deactivates the
  previous one.
- **Creation in Control Mode only**: The `create_program` tool is only
  available in Control Mode, ensuring the user is in an administrative state.
- **Activation by voice AND UI**: Both paths use the same underlying mechanism.

Master switch: `TANGO_PROGRAMS` (default true). See ADR-014.

---

## Nexus Fleet Model Architecture

The Nexus Fleet Model is a rebuild of the Discord bot fleet from individual
scripts into a unified framework under `src/nexus/`. It introduces a shared
FleetBot base class, Redis Streams-based inter-bot communication, a
self-healing foundation, deterministic task routing, GitOps configuration
management, a data flywheel for self-learning, and an autonomous testing
agent.

### Framework Structure

```
src/nexus/
├── manifest/          # Fleet manifest schema and loader (NX-SPEC-01)
├── bus/               # Nexus Bus — Redis Streams event transport (NX-SPEC-02)
├── healing/           # Self-healing foundation — 9 modules (NX-SPEC-03)
├── bots/              # FleetBot base class + 7 bot implementations (NX-SPEC-04, 05)
├── orchestrator/      # Deterministic routing + hierarchy (NX-SPEC-06)
├── deployment/        # GitOps update propagation pipeline (NX-SPEC-07)
├── flywheel/          # Data flywheel & self-learning (NX-SPEC-08)
├── sentinel/          # Autonomous testing agent (NX-SPEC-10)
└── tests/             # Integration tests (NX-SPEC-09)
```

### Fleet Manifest — Single Source of Truth

`fleet-manifest.yaml` is the GitOps single source of truth for all bot
configuration. It defines bot identity, tier, system prompt, tool palette,
LLM route, Discord credentials, and health check endpoints. The manifest
loader validates the file against a Pydantic v2 schema with 17 models.
All config changes flow through the manifest — no bot reads configuration
from scattered files.

### Bots and Tiers

| Bot | Tier | Role |
|---|---|---|
| Admiral | 0 | Sole fleet commander; issues fleet-wide directives |
| Architect | 1 | Implementation and code changes |
| Cartographer | 1 | Documentation and knowledge mapping |
| Cortex | 1 | Research and analysis |
| Quartermaster | 1 | Resource provisioning and inventory |
| Dr. Voss | 1 | Health monitoring and escalation |
| Sentinel | 1 | Autonomous testing and validation |

All bots inherit from `FleetBot`, which provides a 10-phase startup
sequence, protected agent loop with circuit breaker wrapping, Discord
handler fixing 5 production bugs, LLM client routing through LiteLLM,
session manager, and tool registry.

### Nexus Bus (Redis Streams)

Inter-bot communication uses Redis Streams as the event transport layer.
The Nexus Bus provides:

- `NexusEvent` dataclass with 20 typed event types
- JSON serializer/deserializer
- `ConsumerManager` with consumer groups and dead-letter routing
- `NexusBus` async client with publish/subscribe and automatic reconnection

Bots publish events to Redis Streams instead of sending Discord messages.
Other bots subscribe via consumer groups and process events asynchronously.
This eliminates Discord rate limits, ensures durable ordered delivery, and
keeps fleet coordination traffic out of user-facing channels.

### Self-Healing Foundation (9 Modules)

The self-healing foundation provides automated detection, recovery, and
escalation for fleet failures:

| Module | Function |
|---|---|
| Crash-loop detector | Monitors systemd restart frequency; masks crashing services |
| Circuit breakers | CLOSED/OPEN/HALF_OPEN state machine for LLM, tools, Discord |
| Health monitor | Periodic health checks for bots and dependencies |
| Recovery engine | Retry/fallback/escalate ladder for failed operations |
| Checkpoint manager | Redis-backed state checkpointing for crash recovery |
| Semantic breaker | Detects and breaks repeated identical tool call loops |
| Health registry | Fleet-wide aggregation of bot health states |
| Remediation actions | Concrete recovery actions (restart, clear, reload, switch) |
| Runtime supervisor | Orchestrates detection, recovery, and escalation |

### Orchestrator Router and Hierarchy

Admiral is the sole Tier 0 leader. The orchestrator uses a deterministic
routing table (defined in `fleet-manifest.yaml`) to map task types to
specific bots, replacing the previous keyword-based scoring approach.

Task delegation follows a 30-second acknowledgment protocol with 2 retries.
If a bot does not acknowledge within 30 seconds, the task is retried. After
2 failed retries, the monotonic escalation ladder activates:
retry → reroute → Dr. Voss (health check) → human notification.

### GitOps Update Pipeline

Configuration changes flow through `fleet-manifest.yaml` via a GitOps
pipeline with:

1. Manifest diffing to identify changed bots and fields
2. Change severity classification (low/medium/high)
3. Canary-first deployment to the lowest-tier bot
4. 5 health gates after each restart: systemd_active, liveness_endpoint,
   llm_test_request, no_new_errors, sentinel_tests_passed
5. Automatic rollback if any health gate fails
6. Phased rollout: canary → ascending tier → Admiral last

### Data Flywheel

The data flywheel collects failure events (failure.logged,
recovery.executed, flywheel.llm_call) from the Nexus Bus and runs a weekly
analysis engine. Dr. Cortex performs statistical analysis and generates LLM
recommendations. The learning loop extracts insights and applies them to
bot configurations, creating a continuous improvement cycle.

### Sentinel Testing Agent

Sentinel replaces the Proctor bot with an autonomous testing agent that:

- Maintains a test recipe registry (7 YAML files, 20+ cases each)
- Evaluates responses using 6 structured rubrics with anchored scoring
- Runs conversations via the Nexus Bus
- Uses Agent-as-a-Judge LLM evaluation for quality assessment
- Auto-generates test cases from git diffs
- Repairs failures via a strategy ladder (prompt_fix → config_fix →
  code_fix → escalate)
- Tracks posteriors for adaptive test difficulty
- Enforces a universal testing policy via pre-commit hook and CI gate

---

## Key Architectural Decisions

See `docs/decisions/` for full ADRs.

| Decision | Rationale | ADR |
|---|---|---|
| LiveKit Agents SDK (not Pipecat) | Native WebRTC, active development | ADR-001 |
| Flux STT for English | Native EOT detection, lowest latency | ADR-002 |
| Nova-3 `tl` for Tagalog | Flux Multilingual doesn't support Tagalog | ADR-003 |
| `use_tts_aligned_transcript=False` | Do not feed ElevenLabs word timings into the transcription node | ADR-004 |
| `sync_transcription=False` | Do not construct `_SegmentSynchronizerImpl`; captions still publish, unsynced | ADR-012 |
| `max_tool_steps=8` | Tool-heavy Chris/wiki/docs/MCP turns finish before `tool_choice='none'` | ADR-012 |
| Cloudflare tunnel direct to localhost | Bypasses Caddy, prevents Error 522 | ADR-005 |
| POST /api/dispatch after room.connect() | Prevents agent timeout on empty rooms | ADR-006 |
| LiteLLM proxy for all LLM calls | Centralized credentials, model switching | ADR-007 |
| F5-TTS sidecar for Jeremiah pilot | Self-hosted TTS without disrupting other personas | ADR-008 |
| Groq Tagalog defaults + universal voice layer | Reproduce current live persona behavior | ADR-009 |
| Password accounts + server persona authorization | Protect every browser/API path and isolate account data | ADR-010 |
| Voice agent MCP knowledge access | Bridge Discord-fleet MCP servers into voice personas | ADR-012 |
| Control Mode — voice-driven admin override | Adjust persona behavior/tone/prompt mid-conversation, persisted to DB | ADR-013 |
| Voice-created programs (subroutines) | Derived personas with LLM-generated prompts, created via Control Mode, activated by voice or UI | ADR-014 |
| Discord fleet constants via `fleet-config.json` | Tunable without editing bot sources; missing file → defaults | 2026-08-20 fleet-config ADRs |
| Nexus Bus (Redis Streams) for inter-bot communication | Durable, ordered, no rate limits, decoupled from Discord | ADR-018 |
| Self-healing foundation (9 modules) | Defense-in-depth automated recovery for fleet failures | ADR-019 |
| Hierarchy collapse — Admiral as sole Tier 0 | Single point of authority, deterministic routing, clear escalation | ADR-020 |
| GitOps update propagation pipeline | Safe, automated, reversible deployments with canary-first health gates | ADR-021 |
| Sentinel autonomous testing agent | Continuous QA, adaptive test generation, automated repair | ADR-022 |

---

## Discord Fleet Bots (configuration)

All Discord fleet bots under `scripts/` load tunables from
`/opt/Project-Tango/config/fleet-config.json` (override with `FLEET_CONFIG_PATH`)
via `scripts/fleet_config_loader.py`. Missing or corrupt config falls back to
each script's previous hardcoded defaults — bots must not crash.

- Per-bot sections live under `bots.<bot_id>` (e.g. `architect`, `admiral`, `cortex`).
- Shared sections: `fleet_protocol`, `conversation`, `context_builder`, `scheduler`.
- Multi-agent thresholds live under `bots.<bot_id>.multi_agent` and are applied
  in `scripts/multi_agent_config.py`.
- The JSON file is owned by the Fleet Command API and is not committed to this repo.
- Do not restart Discord bot services as part of this change — operator restart
  after review.
