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
- F5-TTS sidecar target port: `8020` bound to `127.0.0.1` only.
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
| `8020` | `tango-tts` F5-TTS sidecar | Localhost-only Jeremiah pilot; do not expose publicly |
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
- Jeremiah may use the local F5-TTS sidecar when `tts_backend="f5-tts"` and
  `TANGO_F5_TTS_ENABLED=true`; all other personas remain on ElevenLabs.
- F5-TTS runs in `/opt/tts-lab/f5-venv` and serves only `127.0.0.1:8020`.
- Production LiveKit workers default to `LIVEKIT_NUM_IDLE_PROCESSES=1` to reduce
  Schubert memory pressure. Raise it only for expected concurrent voice-session starts.
- Camera/screen visual understanding must use LiveKit video track sampling and a
  vision-capable LiteLLM alias through `TANGO_VISION_MODEL`; do not call a vision
  provider directly outside LiteLLM.
- Do not commit real API keys. Keep `.env.example` placeholders blank.

## LiteLLM Aliases

| Alias | Actual model | Use |
| --- | --- | --- |
| `local/qwen3-fast` | `ollama/qwen3.6:latest` | Default for Damian, Jeremiah, Jeremiah V2, Jacob, and Nathaniel |
| `writer/palmyra-x5-voice` | Writer Palmyra X5 voice-tuned route | Chris default; selectable override for all personas |
| `groq/llama4-scout` | Groq Llama 4 Scout | Mama Lulu and Tita Baby defaults; selectable override |

Do not use `ollama/qwen3.6`, `ollama/qwen3.6:latest`, or `writer/palmyra` as Tango
`model_name` values; they are not registered LiteLLM aliases.

## Personas

| Persona | Display Name | ElevenLabs Voice ID | LiteLLM Alias | Deepgram STT Language |
| --- | --- | --- | --- | --- |
| Therapy | Damian | `QF9HJC7XWnue5c9W3LkY` | `local/qwen3-fast` | `en-US` |
| General Info | Chris (British) | `HfRP3cIhYLmeNHeTvkWK` | `writer/palmyra-x5-voice` | `en-US` |
| General Info | Jeremiah | `EqHdTYoEuDQCxN1CVbi0` via F5-TTS pilot | `local/qwen3-fast` | `en-US` |
| General Info | Jeremiah V2 | ElevenLabs | `local/qwen3-fast` | `en-US` |
| General Info | Jacob | `qYwy2TckibCF9cBuhI46` | `local/qwen3-fast` | `en-US` |
| General Info | Mama Lulu | `LF1xMOq6fDVEBEkLP0HO` | `groq/llama4-scout` | `tl` |
| Meditation | Nathaniel | `pFQStpMdprGFILRDrWR2` | `local/qwen3-fast` | `en-US` |
| Pinoy Pride | Tita Baby | `smYFzUb4yrSqprnml7n5` | `groq/llama4-scout` | `tl` |

Persona selection starts from the authenticated catalog returned by FastAPI. A
regular user can request only an assigned persona, and FastAPI—not the
browser—resolves its default or admin-configured model policy. The signed user
and persona are encoded in LiveKit metadata, participant attributes, and a
server-generated room grant. The worker uses that data to choose voice,
LiteLLM model, Deepgram language, prompt, and account-scoped memory.

If the user shares camera or screen video, the worker subscribes to video tracks and may inject a
short visual summary into the current turn. The default summary model is `openai/gpt-4o-mini`
through LiteLLM, configurable with `TANGO_VISION_MODEL`. This is separate from the persona's
speaking LLM route.

For text-heavy visual turns such as terminal output, logs, command results, or code, the worker
uses the OCR path: larger frames, high image detail, and `TANGO_VISION_OCR_MODEL`
(`openai/gpt-4o` by default). Software/app/editor/interface identification also uses this OCR
path because the relevant clues often live in small title, tab, menu, or workspace text.
`AgentSession` disables preemptive generation inside `turn_handling` while vision is enabled so
the visual/OCR context is injected before the persona model starts answering. Set
`TANGO_VISION_DEBUG_SUMMARIES=true` only for diagnostics when the injected visual summary text
must be visible in logs.

Only an admin session may request an interactive model override. Regular-user
requests ignore client model input and use the stored persona policy. Every
override must match the allowlist in `backend/personas.py`; never expose
arbitrary model names, provider URLs, or credentials to LiveKit or the OpenAI
plugin constructor.

Authentication is server-side. Do not add a frontend-only gate or reintroduce
direct browser calls to `tango-api.schubert.life`. Protected browser traffic
must use the Next.js same-origin route handlers, and FastAPI must validate the
opaque database session, CSRF token for mutations, role, and resource owner.

## Validation Floor

Run these before marking the bootstrap complete:

1. `cd backend && uvicorn main:app --host 127.0.0.1 --port 8030 --reload`
2. `cd frontend && npm run dev -- --port 3006`
3. Open `http://localhost:3006`, sign in, and confirm only the account's assigned personas are selectable.
4. Select Damian, connect, and confirm LiveKit reaches the listening state.
5. Speak and confirm interim Deepgram captions render.
6. Confirm ElevenLabs audio playback and speaking animation.
7. Confirm backend logs show `http://localhost:4000`, not `api.openai.com`.
8. Confirm worker startup logs show `num_idle_processes=1`.
9. Confirm Therapy logs show `local/qwen3-fast`.
10. Switch to Chris and confirm logs show `writer/palmyra-x5-voice`.
11. Assign Chris a local-model override in the admin dashboard and confirm logs
    show `local/qwen3-fast`; a regular user must not see a model switcher.
12. Select Jeremiah with Persona default and confirm logs show
    `local/qwen3-fast` plus voice ID `EqHdTYoEuDQCxN1CVbi0`.
13. Select Jacob with Persona default and confirm logs show
    `local/qwen3-fast` plus voice ID `qYwy2TckibCF9cBuhI46`.
14. Select Mama Lulu with Persona default and confirm logs show
    `groq/llama4-scout`, `stt_language=tl`, and voice ID `LF1xMOq6fDVEBEkLP0HO`.
15. Confirm `deploy/tango-backend.service`, `deploy/tango-web.service`, and
    `deploy/Caddyfile.tango-api` exist and are deploy-safe.
16. Run `bash -n deploy/schubert-preflight.sh`.
