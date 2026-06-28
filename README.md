# project-tango

> Persona-driven AI voice companion — self-hosted on Schubert, LiveKit-powered.

![Status](https://img.shields.io/badge/status-active-brightgreen)
![Stable](https://img.shields.io/badge/stable-v1.0--stable-blue)
![License](https://img.shields.io/badge/license-proprietary-red)
![LiveKit](https://img.shields.io/badge/powered%20by-LiveKit%20Agents-blueviolet)
![Deepgram](https://img.shields.io/badge/stt-Deepgram%20Flux-orange)
![ElevenLabs](https://img.shields.io/badge/tts-ElevenLabs%20Flash%20v2.5-ff69b4)

Project Tango is a real-time AI voice agent platform running on the **Schubert AI workstation**. It presents a selection of distinct persona-driven voice agents — each with a unique personality, voice, and language capability — powered by [LiveKit Agents](https://github.com/livekit/agents), [Deepgram](https://deepgram.com), and [ElevenLabs](https://elevenlabs.io), with all LLM traffic routed through the existing [LiteLLM](https://github.com/BerriAI/litellm) proxy on Schubert.

**This is a proprietary personal project by Geronimo AI. Not intended for multi-user or production deployment beyond its defined scope.**

---

## ⚡ Quickstart (first-time deploy)

> Prerequisites: Schubert running with Ollama, LiteLLM, PostgreSQL 18, Caddy, and Cloudflared already active.

```bash
# 1. Clone the repo
cd /opt && sudo -u z121532 git clone git@github.com:theonlygeranium/Project-Tango.git && cd Project-Tango

# 2. Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env — set LIVEKIT_*, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, LITELLM_MASTER_KEY, DATABASE_URL

# 3. Build and deploy
bash scripts/deploy.sh

# 4. Verify services
systemctl is-active tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
```

See [docs/setup.md](docs/setup.md) for the full step-by-step guide with verification commands.

---

## Architecture

```
Browser (https://project-tango.schubert.life)
    │  HTTPS
    ▼
Cloudflare Tunnel  (schubert-foxtrot tunnel)
    │  HTTP
    ▼
Next.js 15 Frontend  (port 3006, tango-web.service)
    │  REST + WebRTC signaling
    ▼
FastAPI Backend  (port 8030, tango-backend.service)
    │  POST /api/dispatch  →  LiveKit Agent Worker
    │  POST /api/connection-details  →  LiveKit token
    ▼
LiveKit Cloud  (wss://project-tango-0xs3szq3.livekit.cloud)
    │  Audio pipeline
    ├── Deepgram STT
    │     ├── flux-general-en  (English personas)
    │     └── nova-3 / language=tl  (Tita Baby, Mama Lulu)
    ├── LiteLLM Proxy @ localhost:4000  (polyglot-litellm.service)
    │     ├── local/qwen3-fast   →  Ollama qwen3 on Schubert GPU
    │     └── writer/palmyra-x5-voice  →  WRITER Palmyra
    └── ElevenLabs Flash v2.5 TTS  (api.us.elevenlabs.io)
          └── Per-persona Voice IDs
    │
    ▼
PostgreSQL 18  (schema: tango — session & turn history)
```

---

## Stack

| Component | Technology | Notes |
|---|---|---|
| Frontend | [Next.js 15](https://nextjs.org) + LiveKit React SDK | Standalone build, orb-style WebRTC UI |
| Backend | [FastAPI](https://fastapi.tiangolo.com) + LiveKit Agents 1.x | Token API + voice worker |
| Voice Framework | [LiveKit Agents SDK](https://github.com/livekit/agents) | `livekit-agents` PyPI — not Pipecat |
| STT (English) | [Deepgram Flux](https://deepgram.com) (`flux-general-en`) | Native turn detection, lowest latency |
| STT (Tagalog) | [Deepgram Nova-3](https://deepgram.com) (`nova-3`, `language=tl`) | Correct Taglish orthography |
| TTS | [ElevenLabs Flash v2.5](https://elevenlabs.io) | US routing, per-persona VoiceSettings |
| LLM Proxy | [LiteLLM](https://github.com/BerriAI/litellm) v1.88+ | Already running on Schubert at port 4000 |
| Local LLM | [Ollama](https://ollama.com) `qwen3.6:latest` | Already running on Schubert at port 11434 |
| Cloud LLM | WRITER Palmyra X5 | Via LiteLLM `writer/palmyra-x5-voice` alias |
| Database | PostgreSQL 18 | Schema `tango` — session/turn history |
| Reverse Proxy | Caddy | Already running on Schubert |
| External Access | Cloudflare Tunnel + Tailscale | Tunnel: `schubert-foxtrot` |
| CI/CD | GitHub Actions | `workflow_dispatch` + Tailscale SSH to Schubert |

---

## Personas

| Persona | Display Name | ElevenLabs Voice ID | LLM Alias | STT |
|---|---|---|---|---|
| Therapy | Damian | `QF9HJC7XWnue5c9W3LkY` | `local/qwen3-fast` | Flux EN |
| General Info | Chris (British) | `HfRP3cIhYLmeNHeTvkWK` | `writer/palmyra-x5-voice` | Flux EN |
| General Info | Jeremiah | `EqHdTYoEuDQCxN1CVbi0` | `local/qwen3-fast` | Flux EN |
| General Info | Jacob | `qYwy2TckibCF9cBuhI46` | `local/qwen3-fast` | Flux EN |
| Meditation | Nathaniel | `pFQStpMdprGFILRDrWR2` | `local/qwen3-fast` | Flux EN |
| Pinoy Pride | Mama Lulu | `LF1xMOq6fDVEBEkLP0HO` | `local/qwen3-fast` | Nova-3 TL |
| Pinoy Pride | Tita Baby | `smYFzUb4yrSqprnml7n5` | `local/qwen3-fast` | Nova-3 TL |

---

## Hardware (Schubert)

| Spec | Value |
|---|---|
| OS | Ubuntu 26.04 LTS |
| CPU | 24-core, performance governor |
| RAM | 32 GB |
| GPU | NVIDIA RTX PRO 4500 Blackwell, 32 GB VRAM |
| Disk | 1.8 TB NVMe |
| Hostname | `schubert.life` |

---

## Repository Structure

```
Project-Tango/
├── AGENTS.md                   ← Mandatory reading for all AI agents
├── CHANGELOG.md                ← All notable changes
├── README.md                   ← This file
├── REVERT.md                   ← Stable baseline & rollback guide
├── backend/
│   ├── main.py                 ← FastAPI app + LiveKit worker entrypoint
│   ├── history.py              ← PostgreSQL session/turn history
│   ├── requirements.txt
│   └── .env.example            ← Environment variable template (no secrets)
├── frontend/
│   ├── app/                    ← Next.js 15 app router
│   ├── components/             ← UI components (persona grid, orb, controls)
│   └── public/                 ← Static assets, PWA manifest
├── deploy/
│   ├── tango-backend.service   ← systemd unit for backend
│   ├── tango-web.service       ← systemd unit for frontend
│   └── schubert-preflight.sh   ← Pre-deploy port/service validation
├── scripts/
│   └── deploy.sh               ← Deployment helper
├── docs/
│   ├── AGENTS.md               ← Runtime constraints for Codex sessions
│   ├── PLAN.md                 ← Development plan and spec history
│   ├── architecture.md         ← Full system architecture
│   ├── setup.md                ← Step-by-step deploy guide
│   ├── decisions/              ← Architectural Decision Records (ADRs)
│   │   └── YYYY-MM-DD-*.md     ← One file per decision
│   └── runbooks/               ← Operational runbooks
│       ├── RB-01-rollback.md
│       ├── RB-02-service-recovery.md
│       └── RB-03-deploy-new-version.md
└── .github/
    └── workflows/
        └── deploy.yml          ← CI/CD pipeline
```

---

## For AI Agents

> If you are an AI agent reading this: **read [AGENTS.md](AGENTS.md) before touching anything.**

`AGENTS.md` is the mandatory collaboration contract for all agents (Writer Agent, Codex, etc.). It defines agent roles, documentation standards, Schubert service boundaries, prohibited actions, and coordination protocols. No agent may commit to this repo without following it.

---

## Stable Baseline

The current verified stable release is tagged **`v1.0-stable`** (commit `fdc9144`).

See [`REVERT.md`](REVERT.md) for full rollback instructions. If anything breaks after new development, revert to this tag first.

```bash
# Quick rollback on Schubert
cd /opt/Project-Tango && git fetch --tags && git checkout v1.0-stable
sudo systemctl restart tango-backend tango-web
```

---

## Roadmap

- [x] Fork AURA and adapt for LiveKit Agents SDK
- [x] Deploy backend (FastAPI + LiveKit worker) and frontend (Next.js) on Schubert
- [x] Implement PostgreSQL 18 conversation history (schema `tango`)
- [x] Configure Cloudflare tunnel routing and DNS for both subdomains
- [x] Implement GitHub Actions CI/CD with Tailscale SSH
- [x] Add all 7 personas with distinct voices and system prompts
- [x] Migrate English STT to Deepgram Flux for native turn detection
- [x] Switch Tagalog personas to Deepgram Nova-3 `tl` for correct orthography
- [x] Resolve mid-speech pauses (`use_tts_aligned_transcript=False`)
- [x] Mobile/iOS optimization (viewport-fit=cover, PWA manifest, two-column grid)
- [x] Tag `v1.0-stable` stable baseline with rollback documentation
- [ ] Add user authentication / session isolation for multi-user support
- [ ] Implement persistent per-user conversation memory
- [ ] Add vision/screen-share capability to all personas
- [ ] Explore custom wake-word detection

---

## License

Proprietary — Geronimo AI. All rights reserved. For authorized personal use only.
