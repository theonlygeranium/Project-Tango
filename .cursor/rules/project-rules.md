# Project Tango — AI Agent Rules

## Framework Requirements

### LiveKit Agents SDK (NOT Pipecat)
- **Use:** `livekit-agents` PyPI package
- **Never use:** `pipecat-ai` or any `pipecat.*` modules
- **Pipeline container:** `AgentSession` (not `Pipeline`)
- **Agent class:** Subclass `livekit.agents.Agent`
- **Worker runner:** `cli.run_app(WorkerOptions(...))`

### Plugin Configuration
- **LLM:** `openai.LLM(base_url=..., ...)`
- **TTS:** `elevenlabs.TTS(model=..., ...)`
- **STT:** `deepgram.STT(model="flux-general-en", ...)`

## LLM Routing (Critical)

- **All LLM calls MUST go through LiteLLM** at `http://localhost:4000`
- Use `LITELLM_MASTER_KEY` for authentication
- **NEVER call Ollama directly** at `localhost:11434`
- **NEVER add** `WRITER_API_KEY` or `PALMYRA_API_KEY` to Tango's `.env`

## STT Model Selection

| Personas | STT Model | Configuration |
|----------|-----------|---------------|
| Damian, Chris, Jeremiah, Jacob, Nathaniel | `flux-general-en` | Native turn detection |
| Tita Baby, Mama Lulu | `nova-3` with `language="tl"` | `smart_format=True` |

**Critical:** Flux does not support Tagalog. Never change Tagalog personas to Flux.

## TTS Configuration

- Set `use_tts_aligned_transcript=False` in `AgentSession`
  - Prevents mid-speech pauses from `_SegmentSynchronizerImpl` race conditions
- `turn_detection="stt"` must be nested in the `turn_handling` dict (LiveKit Agents v2.0 API)

## Agent Dispatch

- Agents do NOT auto-join rooms in LiveKit Agents 1.x
- Backend exposes `POST /api/dispatch`
- Frontend calls this AFTER `room.connect()` succeeds
- Use `room=` (not `room_name=`) in `CreateAgentDispatchRequest`

## Code Modification Constraints

### No Line-Range Splicing
When editing existing code, you MUST provide the full old string to replace, not line ranges. Use the StrReplace tool with complete, exact matches.

### Environment Variables
- Real secrets go in `/opt/Project-Tango/backend/.env` (never committed)
- Template goes in `backend/.env.example` (committed, no real values)

### Service Interaction
**Safe to restart:**
- `tango-backend.service` (port 8030)
- `tango-web.service` (port 3006)
- `polyglot-litellm.service` (port 4000) — with caution

**NEVER touch:**
- `caddy.service` (reverse proxy)
- `cloudflared.service` (external access)
- `postgresql@18-main.service` (data loss risk)
- `tailscaled.service` (network access)
- `meetscribe-*` (port 8010 reserved)
- `foxtrot-*` (port 3010 reserved)
- `ollama.service` (shared GPU server)

## Port Reservations

| Port | Owner | Notes |
|------|-------|-------|
| 3006 | tango-web.service | Frontend |
| 8030 | tango-backend.service | Backend + LiveKit worker |
| 8010 | asr-gateway (Docker) | NEVER use |
| 3010 | Project Foxtrot | NEVER use |
| 4000 | polyglot-litellm.service | Shared LLM proxy |
| 11434 | ollama.service | Never call directly |

## Git Operations on Schubert

- Always run as user `z121532`: `sudo -u z121532 git ...`
- Never `sudo git pull` as root
- Python packages: use `/opt/Project-Tango/backend/venv/bin/pip`
- Path casing: `/opt/Project-Tango` (capital T) everywhere

## Documentation Requirements

Every commit MUST include:
1. **CHANGELOG.md** update under `[Unreleased]`
2. Clear commit message following Conventional Commits format
3. Impact statement (which services affected, restart required?)
4. Verification steps

### Commit Message Template
```
<type>(<scope>): <short summary>

<body — what changed and why>

Impact: <which Schubert services are affected>
Requires restart: <yes/no — if yes, specify which service>
Verification: <how to confirm it works>
```

### ADR Requirement
Create an ADR in `docs/decisions/` for any:
- Architectural decisions
- Technology choices
- Security decisions
- API design changes

## Testing Commands

```bash
# Verify services active
systemctl is-active tango-backend tango-web

# Backend health check
curl -s https://tango-api.schubert.life/healthz

# Confirm LiteLLM routing (not direct Ollama)
sudo journalctl -u tango-backend -n 50 --no-pager | grep "llm_base_url"

# Frontend build check
cd /opt/Project-Tango/frontend && npm run build 2>&1 | tail -5
```

## Schubert CLI Limit

The Schubert Nexus `run_command` tool has a **500-character limit**. Split complex commands into multiple calls or use scripts.

## Discord Bot Fleet

A fleet of 4 Discord bots run as systemd services on this server. They use a shared FLEET protocol for inter-agent delegation, connect to MCP tool servers, and use a local LiteLLM proxy for LLM access.

### Main Bots
- **Admiral Schubert** (`schubert-bot-v2.py`) — Main bot with MCP tools, memory, voice
- **Tango Discord Bot** (`tango-discord-bot.py`) — Simple command bot for Tango operations
- **Tango Discord Agent** (`tango-discord-agent.py`) — Autonomous LLM agent

### Specialist Bots (FLEET Protocol)
- **Architect Bot** (`architect-bot.py`) — Architecture and design
- **Cartographer Bot** (`cartographer-bot.py`) — Codebase mapping
- **Quartermaster Bot** (`quartermaster-bot.py`) — Resource management
- **Dr. Voss Bot** (`dr-voss-bot.py`) — Debugging and diagnostics
- **Proctor Bot** (`proctor-bot.py`) — Meta-developer for bot fleet

### Discord Bot Rules
- All bots share PostgreSQL `tango` schema for memory/sessions
- Vector store uses pgvector (NOT Redis)
- FLEET protocol for inter-bot delegation (max chain depth: 3)
- Discord message limit: 2000 chars
- Rate limit: 5 messages per 5 seconds per channel
- Bot tokens in `/opt/Project-Tango/.env` (separate from Tango voice tokens)

## Sister Projects (Do Not Interfere)

| Project | URL | Port/Path |
|---------|-----|-----------|
| Watson AI | https://watson.schubert.life | `/opt/watson-ai` |
| Pumpkin AI | https://pumpkin.schubert.life | `/opt/pumpkin-ai` |
| Project Foxtrot | https://foxtrot.schubert.life | Port 3010, `/opt/Project-Foxtrot` |
| MeetScribe | Internal | Port 8010, `/opt/meetscribe` |

All share `polyglot-litellm.service` and `ollama.service`. Never restart these without checking other project health.
---

# Schubert Bot V2 Fleet — Development Rules

## Fleet Overview

A fleet of 4 Discord bots run as systemd services on this server. They use a shared FLEET protocol for inter-agent delegation, connect to MCP tool servers, and use a local LiteLLM proxy for LLM access.

| Bot | Script | Service | Channel |
|---|---|---|---|
| Admiral Schubert | scripts/schubert-bot-v2.py | schubert-bot.service | #fleet-command |
| The Architect | scripts/architect-bot.py | schubert-architect.service | #architect |
| The Quartermaster | scripts/quartermaster-bot.py | schubert-quartermaster.service | #quartermaster |
| The Cartographer | scripts/cartographer-bot.py | schubert-cartographer.service | #cartographer |

Shared modules: scripts/fleet_protocol.py, scripts/mcp_client.py, scripts/memory_store.py, scripts/tool_descriptions.py

## Bot Patching — Critical Constraints

### 1. NEVER use line-range splicing

lines[start:end] = [new_method] will silently truncate the entire file if the end index is wrong. Always use content.replace(old_str, new_str, 1) instead.

### 2. ALWAYS backup before patching

cp file.py file.py.bak.$(date +%Y%m%d%H%M%S)

### 3. ALWAYS verify after patching

Run py_compile AND check wc -l AND verify the file ends with bot.run() or main(). py_compile can pass while the file is truncated.

### 4. Heredoc mangling

The Schubert connector command output pipeline transforms percent-sign to pct (display only) and backslash-n in Python string literals to literal newlines (this IS in the file and causes SyntaxError).

Workarounds:
- Use chr(10) instead of newline in Python string literals transferred via heredoc
- Use chr() for all Unicode characters (chr(0x23f9) for stop, chr(0x1f501) for regenerate, chr(0x274c) for cross)
- Verify file content with python3 -c repr(line) rather than trusting sed/cat output

### 5. Command size limit

SCHUBERT_RUN_COMMAND has an 8000-character command limit. Split large patch scripts into multiple smaller commands.

### 6. Binary file writes

SCHUBERT_WRITE_FILE (text) truncates files over ~2KB. Use SCHUBERT_WRITE_FILE_BINARY with content_b64 for larger files.

### 7. Inline base64 is corrupted in transit

Never paste base64 directly into connector arguments. Use the base64 path placeholder pattern instead.

## Bot Service Management

After patching any bot file:
1. Compile check: /opt/Project-Tango/backend/venv/bin/python -c "import py_compile; py_compile.compile('scripts/BOT.py', doraise=True); print('OK')"
2. Restart: sudo systemctl restart schubert-BOT.service
3. Verify: sleep 3 && systemctl is-active schubert-BOT.service
4. Check logs: journalctl -u schubert-BOT.service --no-pager -n 20

## FLEET Protocol

Inter-agent delegation uses FLEET tags:
- Delegation: [FLEET:chain=uuid:turn=int:from=agent:to=agent:status=task] task text
- Response: [FLEET:chain=uuid:turn=int:from=agent:to=agent:status=complete] response text

Constraints:
- MAX_CHAIN_DEPTH = 3 (anti-loop)
- DELEGATION_TIMEOUT = 300s
- max_chunk = 1800 chars (FLEET tag adds ~114 chars)
- Fleet agents only accept FLEET-tagged messages from SCHUBERT_BOT_ID
- Bots ignore their own messages — test using a different bots token

## Discord API Constraints

**Message Limits:**
- 2000 characters max per message
- Embeds: 6000 characters total
- Must chunk long responses

**Rate Limits:**
- 5 messages per 5 seconds per channel
- 50 messages per second global
- Bots implement 10 commands/min internal limit

**Interaction Timeouts:**
- Button clicks: 3 seconds to acknowledge
- Modal submissions: 15 minutes
- Confirmation dialogs: 60 seconds (custom)

## FLEET Protocol (Inter-Bot Communication)

When Admiral Schubert delegates tasks to specialist bots:
- Message format: `FLEET:DELEGATE [task] chain_id=xxx depth=N`
- Response format: `FLEET:RESPONSE chain_id=xxx`
- Max chain depth: 3 (prevents infinite loops)
- Delegation timeout: 60 seconds
- Track chain IDs to prevent circular delegation

## Discord Bot Code Patterns

- Message content limit: 2000 characters
- Rate limit for message edits: ~5 edits per 5 seconds per channel
- Streaming throttle: at least 1.2s between edits
- Bots ignore their own messages

## LLM Access

- Base URL: http://127.0.0.1:4000/v1 (LiteLLM proxy)
- Default model: writer/palmyra-x6 (general tasks)
- Coding model: writer/claude-sonnet-4.5 (auto-switched for coding tasks)
- Bots auto-route between models based on task type

## UI/UX Enhancements (Architect Bot)

5 enhancements implemented and verified:
1. Streaming/Typewriter — StreamingMessage class in fleet_protocol.py edits messages as tokens arrive
2. Interactive Buttons — ProgressView (Stop) + ResponseView (Regenerate) via _running_tasks/_last_inputs
3. Auto-Thread Creation — threads for responses over 500 chars or 3+ tool calls (skipped for FLEET)
4. Rich Embed — author field, color-coded states, structured footer
5. Typing Race Condition Fix — _typing_paused flag + pause-before-cancel pattern

## Brand Colors

- Architect: purple 0x9B59B6
- Quartermaster: orange 0xE67E22
- Cartographer: blue 0x3498DB

## Testing FLEET Delegation

Send a FLEET-tagged message from the Schubert bot token to the target agents channel, then check service logs.

Key log messages:
- FLEET delegation from Schubert — delegation received
- LLM stream complete: N chars, M tool calls — streaming working
- Agent final response: ... — response generated
- Sent FLEET response to Schubert — response sent back to Admiral

## Bot Services — Safe to Restart

- schubert-bot.service (Admiral Schubert)
- schubert-architect.service (The Architect)
- schubert-quartermaster.service (The Quartermaster)
- schubert-cartographer.service (The Cartographer)

All bot services use Restart=on-failure with RestartSec=10.