# AGENTS.md — Project Tango Agent Collaboration Guide

> **This file is mandatory reading for every AI agent that touches this repository.**
> Read it in full before making any change. No exceptions.

---

## 1. What This Repository Is

`Project-Tango` is a **proprietary, persona-driven AI voice companion** owned by Jeffrey Geronimo (Geronimo AI). It runs on a private Ubuntu workstation called **Schubert Nexus** and is deployed at `https://project-tango.schubert.life`.

The stack is:
- **LiveKit Agents SDK** (`livekit-agents` PyPI package — not Pipecat)
- **Next.js 15** (frontend WebRTC UI on port 3006)
- **FastAPI** (backend token API + LiveKit worker on port 8030)
- **Deepgram Flux** (STT for English personas) + **Deepgram Nova-3 `tl`** (STT for Tagalog personas)
- **ElevenLabs Flash v2.5** (TTS, US geographic routing)
- **LiteLLM** (unified LLM proxy, already running on Schubert at port 4000)
- **Ollama** (local model serving: `qwen3.6:latest`)
- **PostgreSQL 18** (conversation history, schema `tango`)
- **Caddy** (reverse proxy)
- **Cloudflare Tunnel + Tailscale** (remote access)

All live configuration lives on Schubert at `/opt/Project-Tango/`. This repo contains the full application source, deployment configs, and documentation applied to Schubert.

---

## 2. Prime Directives for All Agents

1. **Document everything.** Every change — no matter how small — must be documented before it is committed. This is non-negotiable.
2. **Never guess at Schubert's state.** If you need to know the current state of a service, file, or configuration on Schubert, query it via the Schubert Nexus connector before acting. Assumptions cause outages.
3. **No silent changes.** Any modification to a config, script, or deployment file must update the relevant documentation in the same commit.
4. **Preserve existing services.** Schubert runs production-adjacent services (LiteLLM, Ollama, PostgreSQL, Caddy, Cloudflared, MeetScribe, Project Foxtrot). Do not restart, reconfigure, or interfere with any service outside the `Project-Tango` scope without explicit authorization.
5. **Commit atomically.** One logical change per commit. Never bundle unrelated changes.
6. **Leave a trail.** Future agents — and the human owner — must be able to reconstruct exactly what was done, why, and what the state was before and after.

---

## 3. Critical Framework Rules

### 3.1 LiveKit Agents SDK — NOT Pipecat

This project uses **`livekit-agents`**. Never install or import `pipecat-ai` or any `pipecat.*` module.

| Concern | Correct | WRONG |
|---|---|---|
| Pipeline container | `AgentSession` | `Pipeline` |
| LLM plugin | `openai.LLM(base_url=..., ...)` | `OpenAILLMService` |
| TTS plugin | `elevenlabs.TTS(model=..., ...)` | `ElevenLabsTTSService` |
| STT plugin | `deepgram.STT(model="flux-general-en", ...)` | `DeepgramSTTService` |
| Agent class | subclass `livekit.agents.Agent` | any Pipecat agent |
| Worker runner | `cli.run_app(WorkerOptions(...))` | Pipecat pipeline runner |

### 3.2 LLM Routing Rules

- All LLM calls **must** go through LiteLLM at `http://localhost:4000` using `LITELLM_MASTER_KEY`.
- **Never** call Ollama directly at `localhost:11434`.
- **Never** add `WRITER_API_KEY` or `PALMYRA_API_KEY` to Tango's `.env`.

### 3.3 STT Model Selection

| Personas | STT Model | Deepgram Config |
|---|---|---|
| Damian, Chris, Jeremiah, Jacob, Nathaniel | `flux-general-en` (Flux STTv2) | Native turn detection |
| Tita Baby, Mama Lulu | `nova-3`, `language="tl"` | `smart_format=True` |

**Flux does not support Tagalog.** Do not change Tagalog personas to Flux.

### 3.4 TTS Configuration

- Use `use_tts_aligned_transcript=False` in `AgentSession` — prevents mid-speech pauses from `_SegmentSynchronizerImpl` race conditions.
- `turn_detection="stt"` must be nested in the `turn_handling` dict (LiveKit Agents v2.0 API requirement).

### 3.5 Agent Dispatch

- Agents do **not** auto-join rooms in LiveKit Agents 1.x.
- The backend exposes `POST /api/dispatch`. The frontend calls this **after** `room.connect()` succeeds.
- Use `room=` (not `room_name=`) in `CreateAgentDispatchRequest`.

---

## 4. Repository Structure and Ownership

```
Project-Tango/
├── AGENTS.md                   ← YOU ARE HERE — do not modify without authorization
├── README.md                   ← Project overview — update when architecture changes
├── CHANGELOG.md                ← All notable changes — update on every commit
├── REVERT.md                   ← Stable baseline and rollback guide
├── backend/
│   ├── main.py                 ← FastAPI app + LiveKit worker — primary backend file
│   ├── history.py              ← PostgreSQL session/turn history
│   ├── requirements.txt
│   └── .env.example            ← Non-secret env var template — never put real values here
├── frontend/
│   ├── app/
│   ├── components/
│   └── public/
├── deploy/
│   ├── tango-backend.service
│   ├── tango-web.service
│   └── schubert-preflight.sh
├── scripts/
│   └── deploy.sh
├── docs/
│   ├── AGENTS.md               ← Runtime constraints for Codex sessions
│   ├── PLAN.md
│   ├── architecture.md         ← Full system architecture — keep current
│   ├── setup.md                ← Step-by-step deploy guide
│   ├── decisions/              ← Architectural Decision Records (ADRs)
│   └── runbooks/               ← Operational runbooks
└── .github/
    └── workflows/
        └── deploy.yml
```

### File Ownership Rules

| File/Directory | Who Can Modify | Notes |
|---|---|---|
| `AGENTS.md` | Human owner only | Requires explicit authorization |
| `README.md` | Any agent | Must reflect reality — no aspirational content |
| `CHANGELOG.md` | Any agent | Required on every commit |
| `REVERT.md` | Any agent | Update whenever a new stable tag is created |
| `backend/main.py` | Any agent | Core file — document all changes in CHANGELOG |
| `backend/.env.example` | Any agent | Real secrets NEVER go here |
| `docs/architecture.md` | Any agent | Must stay in sync with actual Schubert state |
| `docs/decisions/` | Any agent | New ADR required for every architectural decision |
| `docs/runbooks/` | Any agent | Add runbook when introducing new operational procedure |

---

## 5. Mandatory Documentation Standards

### 5.1 Every Commit Must Include

- **What changed**: Every file modified and what was altered.
- **Why it changed**: The reason or requirement that motivated the change.
- **Impact on Schubert**: Which services are affected, and whether a restart is required.
- **Verification steps**: How to confirm the change worked.

### 5.2 Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<body — what changed and why>

Impact: <which Schubert services are affected>
Requires restart: <yes/no — if yes, specify which service>
Verification: <how to confirm it works>
```

**Types:** `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `ci`

**Example:**

```
fix(backend): switch Tagalog STT from Flux to Nova-3 monolingual tl

Deepgram Flux Multilingual does not include Tagalog, causing phonetic
fallback. Switched Tita Baby and Mama Lulu to nova-3 language="tl"
with smart_format=True for correct Taglish orthography.

Impact: tango-backend.service
Requires restart: yes — sudo systemctl restart tango-backend
Verification: Speak Tagalog to Tita Baby; confirm correct spelling
```

### 5.3 CHANGELOG.md Format

Every commit must add an entry under `[Unreleased]` using [Keep a Changelog](https://keepachangelog.com/) format.

### 5.4 Architectural Decision Records (ADRs)

Whenever an architectural, technology, or security decision is made, create an ADR in `docs/decisions/`.

**Filename:** `docs/decisions/YYYY-MM-DD-short-title.md`

**Template:**

```markdown
# ADR: <Short Title>

**Date:** YYYY-MM-DD
**Status:** Accepted | Superseded | Deprecated
**Decided by:** <agent name or human>

## Context
## Decision
## Rationale
## Alternatives Considered
## Consequences
## References
```

---

## 6. Schubert Nexus Interaction Rules

### 6.1 Services You May Interact With (Project Tango Scope)

| Service | Port | Type | Safe to Restart |
|---|---|---|---|
| `tango-backend.service` | 8030 | systemd | Yes |
| `tango-web.service` | 3006 | systemd | Yes |
| `polyglot-litellm.service` | 4000 | systemd | Yes, with caution |

### 6.2 Services You Must NOT Touch

| Service | Why Off-Limits |
|---|---|
| `caddy.service` | Manages all reverse proxy routing |
| `cloudflared.service` | Manages external access |
| `postgresql@18-main.service` | Production database — data loss risk |
| `tailscaled.service` | Network access |
| `meetscribe-*` | Port 8010 permanently reserved |
| `foxtrot-*` | Port 3010 permanently reserved |
| `ollama.service` | Shared GPU model server |

### 6.3 Port Reservations

| Port | Owner |
|---|---|
| 3006 | `tango-web.service` |
| 8030 | `tango-backend.service` |
| 8010 | `asr-gateway` (Docker) — never use |
| 3010 | Project Foxtrot — never use |
| 4000 | `polyglot-litellm.service` |
| 11434 | `ollama.service` — never call directly |

### 6.4 Schubert CLI Limit

The Schubert Nexus `run_command` tool has a **500-character limit**. Split complex scripts.

### 6.5 Git Operations on Schubert

- Always run git as `z121532`: `sudo -u z121532 git ...`
- Never `sudo git pull` as root.
- Python packages: use venv `/opt/Project-Tango/backend/venv/bin/pip`
- Path casing: `/opt/Project-Tango` (capital T) everywhere.

---

## 7. Git Workflow Rules

- All work on `main`. Experimental changes: `feature/<description>` branch.
- Never force-push to `main` without explicit human authorization.
- Before committing: CHANGELOG updated, no secrets, `.env.example` updated if new vars added.

### Stable Versioning

Current stable baseline: **`v1.0-stable`** → commit `fdc9144`

When a release is verified stable:
1. `git tag -a vX.Y-stable -m "description"`
2. `git push origin vX.Y-stable`
3. Update `REVERT.md` with the new baseline.

---

## 8. Testing and Verification Requirements

```bash
# Services active
systemctl is-active tango-backend tango-web

# Backend health
curl -s https://tango-api.schubert.life/healthz

# LiteLLM routing (not direct Ollama)
sudo journalctl -u tango-backend -n 50 --no-pager | grep "llm_base_url"

# Frontend build
cd /opt/Project-Tango/frontend && npm run build 2>&1 | tail -5
```

---

## 9. Agent Collaboration Architecture

| Agent | Platform | Primary Role | GitHub Access |
|---|---|---|---|
| **Writer Agent** | WRITER (Writer.com) | Research, architecture, documentation, ADRs | GitHub v3 REST API + GitHub MCP connectors |
| **Codex** | OpenAI Codex CLI | Code implementation, execution, testing | GitHub MCP server (native client) |

**Coordination:** Writer Agent plans first → Codex implements → Writer Agent documents after. Read before write. One agent per logical unit of work.

---

## 10. Agent Identification

```
Committed by: Writer Agent (WRITER Agent platform)
Date: 2026-06-28T03:00:00Z
Task: Reformat repository to match watson-ai documentation standards
```

---

## 11. Contact and Authorization

**Human owner:** Jeffrey Geronimo (`jg@writer.com`) — Geronimo AI

For any action outside defined scope — modifying `AGENTS.md`, touching forbidden services, making architectural changes not covered by an ADR, or destructive operations — **stop and ask the human owner for explicit authorization**.

---

## 12. Sister Projects — Cross-Reference

| Project | URL | Schubert Path | Notes |
|---|---|---|---|
| Watson AI | `https://watson.schubert.life` | `/opt/watson-ai` | Personal coding agent (OpenHands) |
| Pumpkin AI | `https://pumpkin.schubert.life` | `/opt/pumpkin-ai` | Personal AI chat (Open WebUI) |
| Project Foxtrot | `https://foxtrot.schubert.life` | `/opt/Project-Foxtrot` | Port 3010 reserved |
| MeetScribe | Internal | `/opt/meetscribe` | Port 8010 reserved |

All projects share `polyglot-litellm.service` (port 4000) and `ollama.service` (port 11434). Never restart these during Tango deploys without checking other project health first.
