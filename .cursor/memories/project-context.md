# Project Tango — Project Context

## What is Project Tango?

Project Tango is a **proprietary, persona-driven AI voice companion** owned by EdStratum Labs. It provides real-time voice interactions with multiple AI personas using WebRTC technology.

**Owner:** EdStratum Labs  
**Deployment:** `https://project-tango.schubert.life`  
**Host:** Schubert Nexus (private Ubuntu workstation)  
**Live Config:** `/opt/Project-Tango/`

## Technology Stack

### Core Framework
- **LiveKit Agents SDK** (`livekit-agents` PyPI package)
  - NOT Pipecat (common confusion point)
  - Version: Compatible with LiveKit Agents 2.0 API

### Frontend
- **Framework:** Next.js 15
- **Port:** 3006
- **Service:** `tango-web.service`
- **URL:** `https://tango.schubert.life`
- **WebRTC:** LiveKit client SDK for browser

### Backend
- **Framework:** FastAPI
- **Port:** 8030
- **Service:** `tango-backend.service`
- **API URL:** `https://tango-api.schubert.life`
- **Responsibilities:**
  - Token generation for LiveKit rooms
  - Agent dispatch endpoint (`POST /api/dispatch`)
  - LiveKit worker process (same service)

### Speech Services
- **STT (English personas):** Deepgram Flux (`flux-general-en`)
- **STT (Tagalog personas):** Deepgram Nova-3 (`nova-3` with `language="tl"`)
- **TTS:** ElevenLabs Flash v2.5 (US geographic routing)

### LLM Infrastructure
- **Proxy:** LiteLLM (port 4000) — `polyglot-litellm.service`
- **Local models:** Ollama (port 11434) — `ollama.service`
  - Model: `qwen3.6:latest`
- **Routing:** All Tango LLM calls go through LiteLLM, never direct to Ollama

### Data Storage
- **Database:** PostgreSQL 18
- **Schema:** `tango`
- **Service:** `postgresql@18-main.service`
- **Purpose:** Conversation history (sessions, turns, transcripts)

### Infrastructure
- **Reverse Proxy:** Caddy
- **Remote Access:** Cloudflare Tunnel + Tailscale
- **OS:** Ubuntu (Schubert Nexus)

## Personas

### English Personas (Flux STT)
- Damian
- Chris
- Jeremiah
- Jacob
- Nathaniel

### Tagalog Personas (Nova-3 STT)
- Tita Baby
- Mama Lulu

Each persona has:
- Unique system prompt
- Voice ID (ElevenLabs)
- STT model configuration
- Personality traits and response patterns

## Architectural Decisions

### Why LiveKit Agents SDK?
- Purpose-built for real-time voice agents
- Native WebRTC integration
- Built-in STT/TTS plugin system
- Room-based architecture fits multi-persona model

### Why LiteLLM Proxy?
- Unified interface for multiple LLM providers
- Fallback routing and load balancing
- Shared across multiple Schubert projects
- Centralized token management and logging

### Why Separate Frontend/Backend Services?
- Independent scaling and restart cycles
- Frontend serves static Next.js build
- Backend handles stateful WebRTC worker processes
- Clear separation of concerns

### Why PostgreSQL for History?
- Reliable relational data for session/turn tracking
- ACID compliance for conversation integrity
- Existing PostgreSQL 18 instance on Schubert
- Rich query capabilities for conversation analytics

## Key Design Patterns

### Agent Dispatch Flow
1. User selects persona in frontend
2. Frontend requests LiveKit token from backend (`POST /api/token`)
3. Frontend connects to LiveKit room (`room.connect()`)
4. Frontend dispatches agent (`POST /api/dispatch` with persona)
5. Backend worker joins room as agent
6. Voice interaction begins

### Turn Detection
- STT-based turn detection (`turn_detection="stt"`)
- No VAD (Voice Activity Detection) preprocessing
- Deepgram handles end-of-speech detection
- `use_tts_aligned_transcript=False` to prevent race conditions

### Session Persistence
- Each conversation creates a database session
- Turns are logged with:
  - User transcript (STT output)
  - Agent response (LLM output)
  - Agent transcript (TTS input)
  - Timestamps
- Session ID passed in room metadata

## Current Stable Baseline

**Tag:** `v1.0-stable`  
**Commit:** `fdc9144`

See `REVERT.md` for rollback instructions.

## Known Issues and Quirks

### LiveKit Agents v2.0 API Change
- `turn_detection` must be nested inside `turn_handling` dict
- Old: `AgentSession(..., turn_detection="stt")`
- New: `AgentSession(..., turn_handling={"turn_detection": "stt"})`

### Deepgram Flux Tagalog Limitation
- Flux does not support Tagalog (causes phonetic fallback)
- Use Nova-3 with explicit `language="tl"` for Tagalog personas
- `smart_format=True` required for proper Taglish orthography

### Agent Dispatch Timing
- Agent must be dispatched AFTER room connection succeeds
- Premature dispatch causes room join failure
- Frontend handles this with sequential async calls

### TTS Alignment Race Condition
- `use_tts_aligned_transcript=True` causes mid-speech pauses
- Root cause: `_SegmentSynchronizerImpl` timing issue in LiveKit SDK
- Workaround: Set to `False` (slightly less accurate transcript timing)

## Related Documentation

- **AGENTS.md:** Full collaboration guide for AI agents
- **README.md:** Project overview and quick start
- **docs/architecture.md:** Detailed system architecture
- **docs/setup.md:** Deployment and configuration guide
- **docs/decisions/:** Architectural Decision Records (ADRs)
- **CHANGELOG.md:** All notable changes
- **REVERT.md:** Stable baseline and rollback guide
