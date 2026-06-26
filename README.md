# Project Tango

Project Tango adapts the forked AURA LiveKit voice interface into a Schubert-hosted,
persona-driven AI companion. The frontend keeps the orb-style WebRTC session UI, while
the backend routes all LLM traffic through the existing LiteLLM proxy on Schubert.

The canonical deployment repo is `theonlygeranium/Project-Tango`. The public
`theonlygeranium/AURA` repo is the fork baseline and historical adaptation source only.

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
- Runtime credentials stay in `/opt/Project-Tango/.env` on Schubert and are not tracked
  in Git.

## Personas

| Persona | Display Name | Voice ID | LiteLLM Alias | STT Language |
| --- | --- | --- | --- | --- |
| Therapy | Damian | `QF9HJC7XWnue5c9W3LkY` | `local/qwen3-fast` | `en-US` |
| General Info | Chris (British) | `HfRP3cIhYLmeNHeTvkWK` | `writer/palmyra-x5-voice` | `en-US` |
| General Info | Jeremiah | `EqHdTYoEuDQCxN1CVbi0` | `local/qwen3-fast` | `en-US` |
| Meditation | Nathaniel | `pFQStpMdprGFILRDrWR2` | `local/qwen3-fast` | `en-US` |
| Pinoy Pride | Tita | `smYFzUb4yrSqprnml7n5` | `local/qwen3-fast` | `tl` |

The frontend sends the selected persona to `/api/connection-details`. The backend encodes
that selection into LiveKit token metadata and room naming so the worker can load the
correct system prompt, ElevenLabs voice, and LiteLLM model.
Tita uses Deepgram Nova-3 Tagalog transcription (`tl`) so spoken Tagalog and
Filipino are recognized during the current test pass; the other personas stay
on English (`en-US`).

The welcome screen also includes an allowlisted model switcher. `Persona default`
uses the persona table above; `Schubert Local Qwen3` forces `local/qwen3-fast`,
and `Writer Palmyra X5` forces `writer/palmyra-x5-voice`. The backend rejects
unknown model strings and never calls Ollama directly.

## Media Controls

The microphone, camera, and screen-share controls are inherited from the AURA LiveKit
interface. Microphone input drives the current audio-first Tango agent. Camera and
screen share publish local LiveKit video tracks, show compact local preview tiles, and
are sampled by the backend worker when the user asks a visually referential question.

Visual understanding uses a lightweight frame-summary step: the worker captures the
latest camera or screen-share frame, summarizes it through the LiteLLM alias in
`TANGO_VISION_MODEL` (`openai/gpt-4o-mini` by default), and injects the resulting
short text as context for the persona's normal voice model. Text-heavy requests such
as terminal output, command results, logs, code, or software/interface
identification automatically switch to an OCR path using larger high-detail frames
and `TANGO_VISION_OCR_MODEL` (`openai/gpt-4o` by default). This keeps Jeremiah,
Tita, Damian, Nathaniel, and Chris on their selected speaking model while allowing
screen/camera questions to work. Set `TANGO_VISION_MODEL=xai/grok-4` or
`TANGO_VISION_OCR_MODEL=xai/grok-4` to compare providers without changing persona
defaults. Set `TANGO_VISION_DEBUG_SUMMARIES=true` only during diagnostics to log
the short text summary injected into each visual turn; screenshots are not logged
by this toggle.

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
3. Confirm the persona selector shows all five personas.
4. Select Damian and connect.
5. Confirm Deepgram Nova-3 interim captions are visible.
6. Confirm ElevenLabs Flash v2.5 playback and speaking animation.
7. Confirm backend logs show `http://localhost:4000`, not `api.openai.com`.
8. Confirm Therapy uses `local/qwen3-fast`.
9. Switch to Chris and confirm model routing changes to `writer/palmyra-x5-voice`.
10. Select Chris with `Schubert Local Qwen3` and confirm backend logs show
    `model=local/qwen3-fast`.
11. Select Jeremiah with `Persona default` and confirm backend logs show
    `model=local/qwen3-fast`.
12. Confirm deploy artifacts exist in `deploy/`.
13. Run `bash -n deploy/schubert-preflight.sh`.

Read `docs/AGENTS.md` before making further changes.
