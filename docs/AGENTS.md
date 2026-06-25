# Project Tango Agent Guide

## Project Tango Framework: LiveKit Agents SDK

This project uses the LiveKit Agents SDK (`livekit-agents` PyPI package).
It does not use Pipecat. Do not install or import `pipecat-ai` or any
`pipecat.*` module.

- Pipeline container: `AgentSession`, not `Pipeline`.
- LLM plugin: `openai.LLM(base_url=..., api_key=..., model=...)`, not `OpenAILLMService`.
- TTS plugin: `elevenlabs.TTS(model=..., voice_id=..., api_key=...)`, not `ElevenLabsTTSService`.
- STT plugin: `deepgram.STT(model="nova-3", interim_results=True)`, not `DeepgramSTTService`.
- Agent class: subclass `livekit.agents.Agent` and set `instructions=` in `__init__`.
- Worker runner: `cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))`.
- Production backend service uses `run_production.py` to run both the FastAPI API and the LiveKit worker.
- All LLM calls proxy through LiteLLM at `localhost:4000` via `LITELLM_MASTER_KEY`.
- Do not call Ollama directly at `localhost:11434`.

Project Tango is adapted from the forked AURA repo at `https://github.com/theonlygeranium/AURA`.
Do not scaffold a replacement app. Preserve the AURA LiveKit orb experience while routing Tango
voice sessions through the provider and persona constraints below.

## Runtime Boundaries

- Target host: Schubert, Ubuntu 26.04, NVIDIA RTX Pro 4500, 32 GB VRAM.
- Backend target port: `8030`.
- Frontend target port: `3006`.
- `project-tango.schubert.life` already exists in the live Caddyfile and proxies to `3006`.
  Do not create a second frontend Caddy block.
- Create only the API Caddy append block for `tango-api.schubert.life -> 127.0.0.1:8030`.
- Use the already-running LiteLLM proxy at `http://localhost:4000`.
- Never deploy a new LiteLLM instance.
- Never call Ollama directly or hardcode `localhost:11434`.
- `ollama.service` already has `qwen3.6:latest` loaded. Do not re-pull it.
- `postgresql@18-main.service` already runs. Create only a `tango` database when database work begins.
- `caddy.service` already runs. Append only the API block; never overwrite the live Caddyfile.
- `cloudflared.service` owns public HTTPS. Do not manage certificates here.
- Do not change `polyglot-*`, `meetscribe-*`, or `project-foxtrot-*` services.
- Do not edit `/opt/polyglot/services/litellm/litellm_config.yaml`, Ollama overrides, or
  `OLLAMA_NUM_PARALLEL`.

## Verified Port Map

| Port | Service | Rule |
| --- | --- | --- |
| `3006` | `tango-web` frontend | Use for Project Tango frontend |
| `8030` | `tango-backend` API | Use for Project Tango backend after confirming it is free |
| `8010` | `asr-gateway` | Do not use |
| `3010` | Schubert homepage | Do not use |
| `3100` | MeetScribe frontend | Do not use |
| `8002` | MeetScribe API | Do not use |
| `3000` | Open WebUI / pumpkin | Do not use |
| `3005` | Watson | Do not use |
| `4000` | `polyglot-litellm` | Connect to it; do not redeploy |

Live inspection on 2026-06-22 showed Docker container `asr-gateway` listening on
`127.0.0.1:8010`; Tango must not reuse that port. Treat
`deploy/schubert-preflight.sh` as authoritative before install.

## Provider Rules

- LLM calls must use OpenAI-compatible routing through LiteLLM at `http://localhost:4000`.
- Tango authenticates to the proxy with `LITELLM_MASTER_KEY`.
- Do not add `WRITER_API_KEY` or `PALMYRA_API_KEY` to Tango env files.
- Deepgram STT must use Nova-3 with interim results enabled for live captions.
- ElevenLabs TTS must use `eleven_flash_v2_5`.
- Do not commit real API keys. Keep `.env.example` placeholders blank.

## LiteLLM Aliases

| Alias | Actual model | Use |
| --- | --- | --- |
| `local/qwen3-fast` | `ollama/qwen3.6:latest` | Therapy, Meditation, Pinoy Pride |
| `writer/palmyra-x5-voice` | Writer Palmyra X5 voice-tuned route | General Info |

Do not use `ollama/qwen3.6`, `ollama/qwen3.6:latest`, or `writer/palmyra` as Tango
`model_name` values; they are not registered LiteLLM aliases.

## Personas

| Persona | Display Name | ElevenLabs Voice ID | LiteLLM Alias |
| --- | --- | --- | --- |
| Therapy | Damian | `QF9HJC7XWnue5c9W3LkY` | `local/qwen3-fast` |
| General Info | Chris (British) | `HfRP3cIhYLmeNHeTvkWK` | `writer/palmyra-x5-voice` |
| Meditation | Nathaniel | `pFQStpMdprGFILRDrWR2` | `local/qwen3-fast` |
| Pinoy Pride | Tita | `smYFzUb4yrSqprnml7n5` | `local/qwen3-fast` |

Persona selection starts in the frontend, is sent to `/api/connection-details`, and is encoded in
the LiveKit token metadata, participant attributes, and generated room name. The backend worker must
use that persona to choose the ElevenLabs voice, LiteLLM model string, and system prompt.

## Validation Floor

Run these before marking the bootstrap complete:

1. `cd backend && uvicorn main:app --host 127.0.0.1 --port 8030 --reload`
2. `cd frontend && npm run dev -- --port 3006`
3. Open `http://localhost:3006` and confirm all four personas are selectable.
4. Select Damian, connect, and confirm LiveKit reaches the listening state.
5. Speak and confirm interim Deepgram captions render.
6. Confirm ElevenLabs audio playback and speaking animation.
7. Confirm backend logs show `http://localhost:4000`, not `api.openai.com`.
8. Confirm Therapy logs show `local/qwen3-fast`.
9. Switch to Chris and confirm logs show `writer/palmyra-x5-voice`.
10. Confirm `deploy/tango-backend.service`, `deploy/tango-web.service`, and
    `deploy/Caddyfile.tango-api` exist and are deploy-safe.
11. Run `bash -n deploy/schubert-preflight.sh`.
