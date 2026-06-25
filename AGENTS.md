# Project Tango Framework: LiveKit Agents SDK

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

# Project Tango

Read `docs/AGENTS.md` before changing this repo. It contains the Project Tango runtime,
provider, persona, deployment, and validation constraints for future Codex sessions.
