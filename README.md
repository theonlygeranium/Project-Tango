# Project Tango

Project Tango adapts the forked AURA LiveKit voice interface into a Schubert-hosted,
persona-driven AI companion. The frontend keeps the orb-style WebRTC session UI, while
the backend routes all LLM traffic through the existing LiteLLM proxy on Schubert.

## Architecture

- `frontend/` - Next.js 15 LiveKit client on port `3006`.
- `backend/` - FastAPI token/session API plus persona-aware LiveKit voice worker on port `8030`.
- `deploy/` - systemd units plus the API-only Caddy append block.
- `docs/` - Codex agent constraints and bootstrap plan.

Project Tango assumes these Schubert services already exist:

- `polyglot-litellm.service` at `http://localhost:4000`
- `ollama.service` with `qwen3.6:latest`
- `postgresql@18-main.service`
- `caddy.service`
- `cloudflared.service`

Do not deploy new LiteLLM or Ollama services for this repo. LLM calls go through
`http://localhost:4000` only, authenticated with `LITELLM_MASTER_KEY`.

## Schubert Notes

- `project-tango.schubert.life` already proxies to frontend port `3006`; do not create a
  second frontend Caddy block.
- `deploy/Caddyfile.tango-api` is the only new Caddy append block and routes
  `tango-api.schubert.life` to backend port `8030`.
- Live inspection on 2026-06-22 showed `127.0.0.1:8010` is permanently owned by
  Docker container `asr-gateway`; Tango uses `8030`, which must remain free for
  the backend. Run `deploy/schubert-preflight.sh` before installing.
- Do not add `WRITER_API_KEY` or `PALMYRA_API_KEY` to Tango env files. LiteLLM already
  owns downstream provider credentials.

## Personas

| Persona | Display Name | Voice ID | LiteLLM Alias |
| --- | --- | --- | --- |
| Therapy | Damian | `QF9HJC7XWnue5c9W3LkY` | `local/qwen3-fast` |
| General Info | Chris (British) | `HfRP3cIhYLmeNHeTvkWK` | `writer/palmyra-x5-voice` |
| Meditation | Nathaniel | `pFQStpMdprGFILRDrWR2` | `local/qwen3-fast` |
| Pinoy Pride | Tita | `smYFzUb4yrSqprnml7n5` | `local/qwen3-fast` |

The frontend sends the selected persona to `/api/connection-details`. The backend encodes
that selection into LiveKit token metadata and room naming so the worker can load the
correct system prompt, ElevenLabs voice, and LiteLLM model.

## Local Setup

Backend:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8030 --reload
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev -- --port 3006
```

Open `http://localhost:3006`.

## Validation

1. `cd backend && uvicorn main:app --host 127.0.0.1 --port 8030 --reload`
2. `cd frontend && npm run dev -- --port 3006`
3. Confirm the persona selector shows all four personas.
4. Select Damian and connect.
5. Confirm Deepgram Nova-3 interim captions are visible.
6. Confirm ElevenLabs Flash v2.5 playback and speaking animation.
7. Confirm backend logs show `http://localhost:4000`, not `api.openai.com`.
8. Confirm Therapy uses `local/qwen3-fast`.
9. Switch to Chris and confirm model routing changes to `writer/palmyra-x5-voice`.
10. Confirm deploy artifacts exist in `deploy/`.
11. Run `bash -n deploy/schubert-preflight.sh`.

Read `docs/AGENTS.md` before making further changes.
