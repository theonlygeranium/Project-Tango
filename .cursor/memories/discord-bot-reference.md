# Discord Bot Quick Reference

## Bot Ecosystem Map

```
Admiral Schubert (Main)
    ├── Architect Bot (architecture & design)
    ├── Cartographer Bot (codebase mapping)
    ├── Quartermaster Bot (resources)
    ├── Dr. Voss Bot (debugging)
    └── Proctor Bot (meta-development)

Tango Operations
    ├── Tango Discord Bot (simple commands)
    └── Tango Discord Agent (autonomous LLM)
```

## File Locations

```
/opt/Project-Tango/scripts/
├── schubert-bot-v2.py          # Main bot (4000+ lines)
├── tango-discord-bot.py        # Simple bot (646 lines)
├── tango-discord-agent.py      # Autonomous agent (1339 lines)
├── architect-bot.py            # Specialist (184KB)
├── cartographer-bot.py         # Specialist (37KB)
├── quartermaster-bot.py        # Specialist (38KB)
├── dr-voss-bot.py              # Specialist (184KB)
├── proctor-bot.py              # Meta-bot (184KB)
├── mcp_client.py               # MCP connector
├── fleet_protocol.py           # Inter-bot delegation
├── memory_store.py             # pgvector memory
├── project_registry.py         # Channel mappings
├── session_manager.py          # Conversation history
└── ui_components.py            # Discord UI views
```

## Services Status

```bash
# Check all bot services
systemctl status schubert-bot.service
systemctl status tango-discord-bot.service

# View logs
journalctl -u schubert-bot.service -f
journalctl -u tango-discord-bot.service -f
```

## Database Access

```sql
-- Connect to PostgreSQL
psql -U tango_user -d tango

-- Check memory vectors
SELECT count(*) FROM memory_vectors;

-- Check project channels
SELECT * FROM project_channels;

-- Check recent sessions
SELECT * FROM sessions ORDER BY created_at DESC LIMIT 10;
```

## Common Commands

### Admiral Schubert (Main Bot)
```
!status              — Service health
!services            — List all services
!logs <service>      — View logs
!restart <service>   — Restart service (confirm)
!disk                — Disk usage
!mem                 — Memory usage
!procs               — Running processes
!net                 — Network stats
!join                — Join voice channel
!leave               — Leave voice channel
!project ...         — Project management
!session ...         — Session management
!memory ...          — Memory queries
!help                — Show all commands
```

### Tango Discord Bot (Simple)
```
!status              — Quick health check
!health              — Full 6-layer check
!logs                — Backend logs
!restart             — Restart tango-backend
!billing             — ElevenLabs subscription
!tts                 — Test TTS
!help                — Show commands
```

### Tango Discord Agent (Autonomous)
```
Natural language     — Trigger agent loop
!agent <request>     — Explicit invocation
!status              — Quick health check
!health              — Full health check
!logs                — Backend logs
!restart [service]   — Restart service
!billing             — ElevenLabs status
!tts                 — Test TTS
!help                — Show commands
```

## Architecture (5 Phases)

### Phase 1: MCP Integration
- 6+ MCP servers (GitHub, Gmail, Cloudflare, Linear, Slack, custom)
- 167+ tools available
- Runtime tool discovery

### Phase 2: Project & Session Management
- ProjectRegistry: Discord channels → project mappings
- SessionManager: Per-channel conversation history
- ContextBuilder: Assembles LLM context

### Phase 3: Persistent Memory
- pgvector in PostgreSQL (HNSW index)
- Vector embeddings with cosine distance (`<=>`)
- Entity graph
- Temporal index
- Database: `tango` schema

### Phase 4: UI Components
- Setup wizard (Discord views)
- Confirmation dialogs
- Project selection dropdowns
- Rich embeds with progress

### Phase 5: Advanced Features
- Coding assistant (file editing, git)
- Scheduler (recurring tasks)
- Webhook handler (GitHub events)
- Multi-agent coordination
- FLEET protocol (delegation)

## FLEET Protocol Flow

```
1. Admiral Schubert receives request
2. Determines specialist needed
3. Sends FLEET:DELEGATE message
   Format: FLEET:DELEGATE [task] chain_id=abc depth=1
4. Specialist bot receives delegation
5. Specialist executes task
6. Specialist sends FLEET:RESPONSE
   Format: FLEET:RESPONSE chain_id=abc
7. Admiral Schubert receives response
8. Admiral Schubert replies to user
```

**Chain Tracking:**
- Max depth: 3
- Timeout: 60 seconds
- Prevents circular delegation
- Tracks chain IDs

## Environment Variables

```bash
# Location
/opt/Project-Tango/.env

# Critical Variables
DISCORD_BOT_TOKEN=...           # Admiral Schubert
ARCHITECT_BOT_TOKEN=...         # Architect
CARTOGRAPHER_BOT_TOKEN=...      # Cartographer
QUARTERMASTER_BOT_TOKEN=...     # Quartermaster
DR_VOSS_BOT_TOKEN=...          # Dr. Voss
PROCTOR_BOT_TOKEN=...          # Proctor
DISCORD_ADMIN_USER_ID=...      # Admin user
DISCORD_BOT_CHANNEL_ID=...     # Bot channel
LITELLM_MASTER_KEY=...         # LLM proxy
DEEPGRAM_API_KEY=...           # STT
ELEVENLABS_API_KEY=...         # TTS
SERPER_API_KEY=...             # Web search
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tango
DB_USER=tango_user
DB_PASSWORD=...
```

## Guardrails (Discord Agent)

**Hard Blocks:**
- `rm -rf` on root/home
- `mkfs`, `dd`, fork bombs
- `shutdown`, `reboot`, `halt`
- `chmod 777`
- Package installs (`apt`, `pip`, `npm`)
- Git push to main
- Critical file overwrites

**Confirmation Required:**
- Git push (feature branches only)

**Rate Limits:**
- 10 commands/min per user
- 5 messages/5s per channel (Discord)

## MCP Tool Access

### Available MCP Servers
1. **GitHub** — Repos, issues, PRs, commits
2. **Gmail** — Email operations
3. **Cloudflare** — DNS, WAF, analytics
4. **Linear** — Issue tracking
5. **Slack** — Workspace operations
6. **Custom** — Project-specific tools

### Tool Discovery
```python
# Runtime discovery
mcp_client = await build_default_client()
tools = await mcp_client.list_tools()
```

## Memory System

### Vector Store (pgvector)
```sql
-- Table: memory_vectors
CREATE TABLE memory_vectors (
    id UUID PRIMARY KEY,
    content TEXT,
    embedding vector(1536),  -- OpenAI ada-002 size
    metadata JSONB,
    created_at TIMESTAMP
);

-- HNSW index for fast similarity search
CREATE INDEX ON memory_vectors 
USING hnsw (embedding vector_cosine_ops);

-- Query similar memories
SELECT content, embedding <=> query_vector AS distance
FROM memory_vectors
ORDER BY embedding <=> query_vector
LIMIT 10;
```

### Entity Graph
```sql
-- Table: memory_entities
CREATE TABLE memory_entities (
    id UUID PRIMARY KEY,
    entity_type TEXT,
    entity_name TEXT,
    properties JSONB,
    created_at TIMESTAMP
);
```

### Temporal Index
```sql
-- Table: memory_temporal
CREATE TABLE memory_temporal (
    id UUID PRIMARY KEY,
    event_type TEXT,
    timestamp TIMESTAMP,
    content TEXT,
    metadata JSONB
);
```

## Voice Channel Support

### Join Voice
```python
# Admiral Schubert joins voice channel
!join

# Bot connects to user's current voice channel
# Starts listening for audio
# Transcribes with Deepgram STT
# Responds with ElevenLabs TTS
```

### Audio Pipeline
```
User speaks
    ↓
Discord voice packets
    ↓
Custom AudioSink (discord-ext-voice-recv)
    ↓
PCM audio buffer
    ↓
Deepgram STT (streaming)
    ↓
Text transcript
    ↓
LLM processing (via LiteLLM)
    ↓
Response text
    ↓
ElevenLabs TTS
    ↓
Audio stream
    ↓
Discord voice channel
```

## Troubleshooting

### Bot Not Responding
```bash
# Check service
systemctl status schubert-bot.service

# Check logs
journalctl -u schubert-bot.service -n 100

# Common issues:
# - Discord token expired
# - LiteLLM proxy down
# - PostgreSQL connection failed
# - MCP server unreachable
```

### Memory Issues
```sql
-- Check memory store
SELECT count(*) FROM memory_vectors;

-- Check for orphaned embeddings
SELECT * FROM memory_vectors 
WHERE metadata->>'session_id' NOT IN (SELECT session_id FROM sessions);

-- Clear old memories (if needed)
DELETE FROM memory_vectors WHERE created_at < NOW() - INTERVAL '90 days';
```

### FLEET Protocol Issues
```bash
# Check specialist bot logs
journalctl -u architect-bot.service -n 50

# Common issues:
# - Specialist bot offline
# - Chain depth exceeded (max 3)
# - Delegation timeout (60s)
# - Invalid FLEET message format
```

### Voice Channel Issues
```bash
# Check Opus library
python3 -c "import discord; discord.opus._load_default()"

# Common issues:
# - Opus library not installed
# - Voice channel permissions
# - Audio sink not receiving packets
# - Deepgram API key invalid
```

## Development Workflow

### Making Changes
1. Edit bot file in `/opt/Project-Tango/scripts/`
2. Test manually: `python3 scripts/schubert-bot-v2.py`
3. Update CHANGELOG.md
4. Commit with Conventional Commits format
5. Restart service: `sudo systemctl restart schubert-bot.service`
6. Check logs: `journalctl -u schubert-bot.service -f`

### Adding a New Specialist Bot
1. Copy template from existing specialist (e.g., `architect-bot.py`)
2. Update bot token in `.env`
3. Modify system prompt and specialization
4. Add to FLEET protocol routing in Admiral Schubert
5. Create systemd service file
6. Test delegation flow
7. Document in `discord-bot-fleet.md`

### Adding New MCP Tools
1. Install MCP server (if external)
2. Add server config to MCP client initialization
3. Update tool discovery in `mcp_client.py`
4. Add tool handlers if custom logic needed
5. Update system prompt to mention new tools
6. Test tool execution
7. Document in ADR

## Performance Metrics

### Typical Response Times
- Simple command (!status): < 1 second
- Agent loop (1 tool call): 2-5 seconds
- Agent loop (3-5 tool calls): 10-20 seconds
- MCP tool execution: 1-10 seconds (varies by tool)
- Voice transcription: 1-3 seconds
- Voice synthesis: 2-5 seconds

### Resource Usage
- Memory: ~500MB per bot (idle), ~1-2GB (active)
- CPU: < 5% (idle), 20-40% (LLM processing)
- PostgreSQL: ~200MB for memory store
- Disk: ~5GB for all bots + dependencies

## Related Files

- **Main documentation:** `discord-bot-fleet.md`
- **AGENTS.md:** Top-level rules (read-only)
- **README.md:** Project overview
- **CHANGELOG.md:** All changes
