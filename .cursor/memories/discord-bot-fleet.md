# Discord Bot Fleet — Schubert Bot V2 and Specialists

## Overview

Project Tango contains a comprehensive Discord bot ecosystem running on Schubert Nexus. This is a **separate project** from the voice companion (Tango web/backend services).

The bot fleet consists of:
1. **Admiral Schubert** (main bot) — `schubert-bot-v2.py`
2. **Specialist bots** — Architect, Cartographer, Quartermaster, Dr. Voss, Proctor
3. **Tango Discord Bot** (simple) — `tango-discord-bot.py`
4. **Tango Discord Agent** (autonomous) — `tango-discord-agent.py`

## Admiral Schubert (Main Bot)

**File:** `/opt/Project-Tango/scripts/schubert-bot-v2.py`  
**Service:** `schubert-bot.service`  
**Persona:** Maine Coon cat with nautical personality

### Architecture (5 Phases)

**Phase 1: MCP Integration**
- Connects to 6+ MCP servers at runtime
- 167+ tools available (GitHub, Gmail, Cloudflare, etc.)
- Dynamic tool discovery via `mcp_client.py`

**Phase 2: Project & Session Management**
- `ProjectRegistry` maps Discord channels → projects
- `SessionManager` tracks per-channel conversation history
- `ContextBuilder` assembles LLM context
- Natural language project setup (no slash commands needed)

**Phase 3: Persistent Memory**
- Three-layer memory system
- Vector store in pgvector/PostgreSQL (HNSW index)
- Entity graph in PostgreSQL
- Temporal index in PostgreSQL
- Database: `tango` schema (NOT `memory_store`)
- **Note:** Migrated from Redis to pgvector

**Phase 4: UI Components**
- Setup wizard with Discord UI views
- Confirmation dialogs
- Project selection dropdowns
- Rich embeds with progress tracking
- Implemented in `ui_components.py`

**Phase 5: Advanced Features**
- **Coding assistant** (`coding_assistant.py`) — code editing, file operations
- **Scheduler** (`scheduler.py`) — recurring tasks, reminders
- **Webhook handler** (`webhook_handler.py`) — GitHub webhooks, event processing
- **Multi-agent coordination** (`multi_agent.py`) — parallel task execution
- **FLEET protocol** (`fleet_protocol.py`) — delegation to specialist bots

### Voice Support
- **STT:** Deepgram (same as Tango voice personas)
- **TTS:** ElevenLabs (same as Tango voice personas)
- Join/leave voice channels with `!join` / `!leave`
- Real-time voice transcription and synthesis

### Key Features
- MCP tool integration (GitHub, Gmail, Cloudflare, etc.)
- Persistent memory across conversations
- Per-channel project context
- Voice channel support
- Autonomous agent mode
- Coding assistance (file editing, git operations)
- Task scheduling
- Webhook processing

## FLEET Protocol (Inter-Bot Communication)

**Purpose:** Admiral Schubert delegates specialized tasks to specialist bots

**File:** `fleet_protocol.py`

**Mechanism:**
- Admiral Schubert sends delegation messages to specialist bots
- Specialists respond with results
- Chain tracking prevents infinite loops
- Max chain depth: configurable (default 3)
- Delegation timeout: configurable (default 60s)

**Message Format:**
```
FLEET:DELEGATE [task_type] chain_id=xxx depth=N
[task description]
---
[context data]
```

**Response Format:**
```
FLEET:RESPONSE chain_id=xxx
[response content]
```

## Specialist Bots

### 1. Architect Bot
**File:** `architect-bot.py`  
**Service:** `architect-bot.service` (if deployed)  
**Specialization:** System architecture, design decisions, technical planning  
**Persona:** Technical architect

### 2. Cartographer Bot
**File:** `cartographer-bot.py`  
**Specialization:** Codebase mapping, documentation, file structure analysis  
**Persona:** Code navigator and mapper

### 3. Quartermaster Bot
**File:** `quartermaster-bot.py`  
**Specialization:** Resource management, dependencies, configuration  
**Persona:** Supply and resource manager

### 4. Dr. Voss Bot
**File:** `dr-voss-bot.py`  
**Specialization:** Debugging, error diagnosis, health checks  
**Persona:** Medical/diagnostic specialist

### 5. Proctor Bot
**File:** `proctor-bot.py`  
**Service:** May be deployed  
**Specialization:** Development and administration of Schubert Bot itself  
**Persona:** Meta-developer (develops the bot fleet)

**Special capabilities:**
- Self-healing system monitoring
- Bot performance optimization
- Code quality assessment
- Auto-remediation (restart services, reconnect MCP, clean disk)
- Escalation to Discord channel after 3 failed auto-fix attempts

## Tango Discord Bot (Simple)

**File:** `tango-discord-bot.py`  
**Service:** `tango-discord-bot.service`  
**Purpose:** Simple command bot for Tango voice service management

**Commands:**
- `!status` — service health snapshot
- `!health` — full 6-layer health check
- `!logs` — recent tango-backend logs
- `!restart` — restart tango-backend (with confirmation)
- `!billing` — ElevenLabs subscription status
- `!tts` — test TTS synthesis
- `!help` — show commands

**Security:**
- Admin allowlist (only `DISCORD_ADMIN_USER_ID`)
- Channel lock (only `DISCORD_BOT_CHANNEL_ID`)
- Command allowlist (fixed commands only)
- Confirmation for destructive actions
- Rate limiting (10 commands/min)

## Tango Discord Agent (Autonomous)

**File:** `tango-discord-agent.py`  
**Service:** `tango-discord-bot.service` (shares service with simple bot)  
**Purpose:** LLM-powered autonomous agent for Tango operations

**Model:** `writer/claude-sonnet-4-5` via LiteLLM

**Capabilities:**
- Natural language task understanding
- Autonomous investigation and fixes
- Code patching with `write_file` tool
- Shell command execution with `run_shell` tool
- Health check execution
- Web search via Serper.dev API
- Git operations (as user z121532)
- Service restarts

**Guardrails (Hard Blocks):**
- `rm -rf` on root/home
- `mkfs`, `dd`, fork bombs
- `shutdown`, `reboot`, `halt`
- `chmod 777`
- Package installs (`apt`, `pip`, `npm`)
- Git push to main branch
- Critical file overwrites (`/etc/passwd`, `/etc/shadow`, etc.)

**Confirmation Required:**
- Git push operations (to feature branches only)

**Safety Limits:**
- Max 20 iterations per agent loop
- 5-minute total timeout
- 120-second shell command timeout
- 4000-char tool output limit

## Shared Infrastructure

### MCP Servers (All Bots)
- GitHub MCP server (repo operations, issues, PRs)
- Gmail MCP server (email operations)
- Cloudflare MCP server (DNS, WAF, analytics)
- Linear MCP server (issue tracking)
- Slack MCP server (workspace operations)
- Custom MCP servers (project-specific)

### LLM Access
- All bots use LiteLLM proxy at `http://127.0.0.1:4000`
- Model: `writer/claude-sonnet-4-5` (primary)
- Fallback models available via LiteLLM routing
- Authentication: `LITELLM_MASTER_KEY`

### Database (PostgreSQL 18)
- Schema: `tango`
- Tables:
  - `memory_vectors` — pgvector embeddings (HNSW index)
  - `memory_entities` — entity graph
  - `memory_temporal` — temporal index
  - `sessions` — conversation sessions
  - `turns` — conversation turns
  - `project_channels` — channel → project mappings
  - `scheduled_tasks` — recurring tasks

### Environment Variables

All bots share `.env` at `/opt/Project-Tango/.env`:

```bash
# Discord
DISCORD_BOT_TOKEN=...           # Main bot token
ARCHITECT_BOT_TOKEN=...         # Architect specialist
CARTOGRAPHER_BOT_TOKEN=...      # Cartographer specialist
QUARTERMASTER_BOT_TOKEN=...     # Quartermaster specialist
DR_VOSS_BOT_TOKEN=...          # Dr. Voss specialist
PROCTOR_BOT_TOKEN=...          # Proctor meta-bot
DISCORD_ADMIN_USER_ID=...      # Admin user ID
DISCORD_BOT_CHANNEL_ID=...     # Bot channel ID
AUTHORIZED_AGENT_IDS=...       # Comma-separated agent IDs

# LLM
LITELLM_MASTER_KEY=...         # LiteLLM proxy auth

# External APIs
DEEPGRAM_API_KEY=...           # STT for voice
ELEVENLABS_API_KEY=...         # TTS for voice
SERPER_API_KEY=...             # Web search (Serper.dev)

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tango
DB_USER=tango_user
DB_PASSWORD=...

# MCP Servers (tokens for external services)
GITHUB_TOKEN=...
GMAIL_TOKEN=...
CLOUDFLARE_API_TOKEN=...
LINEAR_API_KEY=...
SLACK_TOKEN=...
```

## Discord API Constraints

**Message Length:**
- 2000 characters max per message
- Embeds: 6000 characters total across all fields
- Code blocks must fit within message limit

**Rate Limits:**
- 5 messages per 5 seconds per channel
- 50 messages per second global
- Bots implement internal rate limiting (10 commands/min)

**Interaction Timeouts:**
- Button clicks: 3 seconds to acknowledge
- Modal submissions: 15 minutes
- Confirmation dialogs: 60 seconds (custom)

## Bot Deployment

### Systemd Services

```bash
# Main bot
sudo systemctl status schubert-bot.service
sudo systemctl restart schubert-bot.service

# Tango management bots
sudo systemctl status tango-discord-bot.service

# Specialist bots (if deployed as services)
sudo systemctl status architect-bot.service
sudo systemctl status proctor-bot.service
```

### Running Manually (Development)

```bash
# Main bot
cd /opt/Project-Tango
source backend/venv/bin/activate
python3 scripts/schubert-bot-v2.py

# Tango Discord Bot
python3 scripts/tango-discord-bot.py

# Tango Discord Agent
python3 scripts/tango-discord-agent.py

# Specialist bots
python3 scripts/architect-bot.py
python3 scripts/cartographer-bot.py
# etc.
```

### Log Locations

```bash
# Systemd service logs
sudo journalctl -u schubert-bot.service -f
sudo journalctl -u tango-discord-bot.service -f

# Application logs (if file logging enabled)
/var/log/tango-discord-bot.log
/var/log/tango-discord-agent.log
```

## Module Dependencies

### Core Modules (Admiral Schubert)
```
scripts/
├── schubert-bot-v2.py          # Main bot file
├── mcp_client.py               # MCP server connector
├── cloudflare_api.py           # Cloudflare tool wrapper
├── project_registry.py         # Channel → project mapping
├── session_manager.py          # Conversation history
├── context_builder.py          # LLM context assembly
├── memory_store.py             # Persistent memory (pgvector)
├── ui_components.py            # Discord UI views/embeds
├── coding_assistant.py         # Code editing tools
├── scheduler.py                # Task scheduling
├── webhook_handler.py          # GitHub webhooks
├── multi_agent.py              # Multi-agent coordination
├── fleet_protocol.py           # Inter-bot delegation
└── response_scoring.py         # Response relevance scoring
```

### Python Dependencies
```
discord.py                      # Discord API
discord-ext-voice-recv         # Voice receiving
aiohttp                        # HTTP client
psycopg2-binary                # PostgreSQL
pgvector                       # Vector extension
numpy                          # Vector operations
```

## Key Differences: Discord Bots vs Tango Voice

| Aspect | Discord Bots | Tango Voice |
|--------|--------------|-------------|
| **Purpose** | Text/voice chat on Discord | WebRTC voice companions |
| **Framework** | discord.py | LiveKit Agents SDK |
| **Transport** | Discord Gateway | WebRTC (LiveKit) |
| **STT** | Deepgram (shared) | Deepgram (shared) |
| **TTS** | ElevenLabs (shared) | ElevenLabs (shared) |
| **LLM** | LiteLLM (shared) | LiteLLM (shared) |
| **Persistence** | PostgreSQL `tango` schema | PostgreSQL `tango` schema |
| **Port** | N/A (Discord API) | 8030 (backend), 3006 (frontend) |
| **Services** | `schubert-bot.service`, etc. | `tango-backend.service`, `tango-web.service` |

## Common Pitfalls

### 1. Bot Token Confusion
- Each bot needs its own Discord token
- Tokens are in `/opt/Project-Tango/.env` (not in Tango `.env`)
- Never commit tokens to git

### 2. Database Schema
- Database name is `tango` (NOT `memory_store`)
- Vector extension is `pgvector` (NOT Redis)
- Use `<=>` operator for cosine distance in pgvector

### 3. FLEET Protocol
- Max chain depth prevents infinite delegation loops
- Always include chain_id in delegation messages
- Track response timeouts (default 60s)

### 4. Discord Rate Limits
- Implement backoff/retry for 429 responses
- Chunk long messages (2000 char limit)
- Use embeds for structured data

### 5. MCP Tool Timeouts
- Some MCP tools can be slow (GitHub API, etc.)
- Set appropriate timeouts in agent loop
- Provide progress updates to Discord channel

### 6. Voice Channel Issues
- Bot must be in voice channel to receive audio
- Opus library must be loaded (`discord.opus._load_default()`)
- Voice packets need custom `AudioSink` implementation

## Future Enhancements

### Planned Features (from codebase comments)
- **Phase 6:** Advanced analytics and reporting
- **Phase 7:** Cross-project knowledge sharing
- **Phase 8:** Autonomous learning and improvement
- **Phase 9:** External integration framework
- **Phase 10:** Production deployment architecture

### Known TODOs
- Voice channel reconnection handling
- Memory pruning/archival strategy
- Rate limit backoff optimization
- Cross-bot shared context
- Persistent task queue for scheduler

## Related Documentation

- Main bot README (if exists): `/opt/Project-Tango/scripts/README.md`
- FLEET protocol spec: See `fleet_protocol.py` docstring
- MCP client usage: See `mcp_client.py` docstring
- Memory store schema: See `memory_store.py` docstring

## Contact and Authorization

**Owner:** EdStratum Labs (`founder@edstratumlabs.ai`)

For bot modifications:
- Code changes: Follow same rules as Tango (CHANGELOG, ADRs, etc.)
- New specialist bots: Requires architecture review
- FLEET protocol changes: Requires testing across all bots
- Database schema changes: Requires migration script and backup
