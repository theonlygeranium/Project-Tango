# .cursor/ Directory — AI Context for Project Tango

This directory provides comprehensive context for AI agents working on Project Tango.

## Directory Structure

```
/opt/Project-Tango/.cursor/
├── rules/
│   └── project-rules.md           # AI behavior rules, coding constraints, bot protocols
├── memories/
│   ├── project-context.md         # Tango voice companion architecture
│   ├── coding-patterns.md         # Code patterns, common pitfalls
│   ├── device-specifics.md        # Schubert server environment
│   ├── discord-bot-fleet.md       # Discord bot ecosystem (Admiral Schubert)
│   └── discord-bot-reference.md   # Quick reference for bot commands & architecture
└── settings.json                  # Cursor editor preferences
```

## File Descriptions

### `rules/project-rules.md`
**Purpose:** Mandatory rules and constraints for AI agents

**Contents:**
- LiveKit Agents SDK requirements (NOT Pipecat)
- LLM routing rules (must use LiteLLM proxy)
- STT model selection (Flux for English, Nova-3 for Tagalog)
- TTS configuration (ElevenLabs Flash v2.5)
- Service interaction constraints (safe vs forbidden)
- Port reservations (8030, 3006, 8010, 3010, etc.)
- Git operation guidelines (always as user z121532)
- Documentation requirements (CHANGELOG, ADRs, commit format)
- Discord bot fleet protocols (FLEET delegation, rate limits)
- Discord API constraints (message limits, rate limits, timeouts)

**Key Rules:**
- All LLM calls MUST go through LiteLLM at port 4000
- NEVER call Ollama directly at port 11434
- Flux STT does not support Tagalog (use Nova-3 with `language="tl"`)
- NEVER touch forbidden services (caddy, cloudflared, postgresql, etc.)
- Always document changes in CHANGELOG.md

### `memories/project-context.md`
**Purpose:** Architecture and technology decisions for Tango voice companion

**Contents:**
- Project overview (voice companion with personas)
- Technology stack (LiveKit, FastAPI, Next.js, Deepgram, ElevenLabs)
- Personas (English: Damian, Chris, etc.; Tagalog: Tita Baby, Mama Lulu)
- Agent dispatch flow (frontend → backend → LiveKit room)
- Turn detection patterns (STT-based)
- Session persistence (PostgreSQL tango schema)
- Current stable baseline (v1.0-stable, commit fdc9144)
- Known issues and quirks

**Key Insights:**
- LiveKit Agents SDK v2.0 API changes (turn_handling dict)
- Deepgram Flux Tagalog limitation (why we use Nova-3)
- Agent dispatch timing (must be AFTER room connection)
- TTS alignment race condition (use_tts_aligned_transcript=False)

### `memories/coding-patterns.md`
**Purpose:** Code patterns, anti-patterns, and best practices

**Contents:**
- Code modification rules (read before write, no line-range splicing)
- Python patterns (LiveKit agent, database, env vars)
- Frontend patterns (LiveKit room connection, error handling)
- Configuration patterns (persona dictionaries)
- Testing patterns (service checks, manual voice testing)
- Common pitfalls to avoid (calling Ollama directly, using Pipecat, etc.)
- Dependency management (pinned versions)
- Documentation requirements

**Key Patterns:**
- Always use StrReplace with exact string matching
- Environment variables via python-dotenv
- LiveKit Agent class pattern with on_session_start
- Database operations via psycopg2 with context managers
- Sequential API calls (connect room THEN dispatch agent)

### `memories/device-specifics.md`
**Purpose:** Schubert Nexus server environment details

**Contents:**
- Hardware information (Ubuntu Linux, x86_64, GPU)
- File system paths (/opt/Project-Tango/, exact casing)
- User accounts (z121532, service users)
- Git configuration (always run as z121532)
- Service architecture (systemd units, dependencies)
- Network configuration (localhost services, Caddy reverse proxy)
- Database configuration (PostgreSQL 18, tango schema)
- Python environment (venv, package installation)
- Node.js environment (v20+, npm, build process)
- Shared services (LiteLLM, Ollama, PostgreSQL — multi-project)
- Port reservations (8010 MeetScribe, 3010 Foxtrot — never use)
- Deployment workflow (pull, install, build, restart, verify)
- Environment variables (.env location, required vars)
- Monitoring and logs (journalctl, health checks)
- CLI command length limit (500 chars for Schubert Nexus connector)
- Backup and recovery (git tags, database dumps)
- Remote access (Cloudflare Tunnel, Tailscale)
- Performance considerations (GPU usage, concurrent conversations)
- Known device quirks (GPU OOM, service restarts, file permissions)

**Critical Details:**
- Path casing matters: `/opt/Project-Tango/` (capital T)
- Always `sudo -u z121532 git ...` (never `sudo git`)
- Python venv: `/opt/Project-Tango/backend/venv/bin/pip`
- Schubert CLI limit: 500 characters (split complex commands)
- Shared services affect multiple projects (check before restart)

### `memories/discord-bot-fleet.md`
**Purpose:** Comprehensive documentation of Discord bot ecosystem

**Contents:**
- Overview of bot fleet (Admiral Schubert + specialists + Tango bots)
- Admiral Schubert architecture (5 phases: MCP, project/session, memory, UI, advanced)
- Voice support (Deepgram STT, ElevenLabs TTS, join/leave commands)
- FLEET protocol (inter-bot delegation, chain tracking)
- Specialist bots (Architect, Cartographer, Quartermaster, Dr. Voss, Proctor)
- Tango Discord Bot (simple command bot for Tango operations)
- Tango Discord Agent (autonomous LLM agent with guardrails)
- Shared infrastructure (MCP servers, LLM access, PostgreSQL database)
- Environment variables (Discord tokens, API keys)
- Discord API constraints (message limits, rate limits, timeouts)
- Bot deployment (systemd services, manual running, log locations)
- Module dependencies (core modules, Python packages)
- Key differences: Discord bots vs Tango voice
- Common pitfalls (token confusion, database schema, FLEET protocol, etc.)
- Future enhancements (planned phases 6-10)

**Key Architecture:**
- Phase 1: MCP Integration (6+ servers, 167+ tools)
- Phase 2: Project/Session Management (channel mappings, history)
- Phase 3: Persistent Memory (pgvector, entity graph, temporal index)
- Phase 4: UI Components (Discord views, embeds)
- Phase 5: Advanced Features (coding, scheduling, webhooks, multi-agent, FLEET)

**FLEET Protocol:**
- Admiral Schubert delegates to specialists
- Message format: `FLEET:DELEGATE [task] chain_id=xxx depth=N`
- Response format: `FLEET:RESPONSE chain_id=xxx`
- Max chain depth: 3 (prevents loops)
- Timeout: 60 seconds

### `memories/discord-bot-reference.md`
**Purpose:** Quick reference for bot commands, architecture, and troubleshooting

**Contents:**
- Bot ecosystem map (visual hierarchy)
- File locations (all bot scripts and modules)
- Services status commands (systemctl, journalctl)
- Database access (SQL queries for memory, sessions)
- Common commands (Admiral Schubert, Tango bots, agent)
- Architecture summary (5 phases)
- FLEET protocol flow (step-by-step)
- Environment variables (complete list)
- Guardrails (hard blocks, confirmation patterns)
- MCP tool access (available servers, tool discovery)
- Memory system (pgvector schema, entity graph, temporal index)
- Voice channel support (audio pipeline)
- Troubleshooting (bot not responding, memory issues, FLEET issues, voice issues)
- Development workflow (making changes, adding bots, adding MCP tools)
- Performance metrics (response times, resource usage)

**Use Cases:**
- Quick command lookup
- Service status checks
- Database queries
- Troubleshooting guide
- Development reference

### `settings.json`
**Purpose:** Cursor editor configuration

**Contents:**
- Format on save (enabled)
- Code actions on save (fixAll, organizeImports)
- Tab size (2 for JS/JSON, 4 for Python)
- Python venv path (`${workspaceFolder}/backend/venv/bin/python`)
- Linting (flake8 enabled, pylint disabled)
- Formatting (Black for Python, Prettier for JS/TS/JSON)
- File exclusions (\_\_pycache\_\_, node_modules, .next, venv, .env)
- Search exclusions (same as file exclusions)
- Git ignore limit warning (ignored)

## Usage Guidelines

### For AI Agents

1. **Always read `rules/project-rules.md` first**
   - Contains mandatory constraints
   - Violations may cause outages

2. **Consult `memories/` for context**
   - `project-context.md` — Tango voice architecture
   - `device-specifics.md` — Schubert environment
   - `discord-bot-fleet.md` — Bot ecosystem
   - `coding-patterns.md` — Code best practices

3. **Use quick reference for lookups**
   - `discord-bot-reference.md` — Commands, troubleshooting

4. **Follow editor settings**
   - `settings.json` — Consistent formatting

### For Humans

**Adding new context:**
1. Create file in `memories/` with descriptive name
2. Use markdown format
3. Include cross-references to related files
4. Update this README with file description

**Updating rules:**
1. Edit `rules/project-rules.md` (careful — affects all agents)
2. Document change reason in commit message
3. Update AGENTS.md if rule is critical

**Editor configuration:**
1. Edit `settings.json`
2. Restart Cursor if needed
3. Test formatting with sample file

## Project Scope

### What This Directory Covers

**Tango Voice Companion:**
- LiveKit Agents SDK architecture
- Persona configuration (English & Tagalog)
- STT/TTS integration (Deepgram, ElevenLabs)
- LLM routing (LiteLLM proxy)
- Session persistence (PostgreSQL)
- Frontend (Next.js) and backend (FastAPI)

**Discord Bot Fleet:**
- Admiral Schubert (main bot with MCP, memory, voice)
- Specialist bots (Architect, Cartographer, Quartermaster, Dr. Voss, Proctor)
- Tango Discord Bot (simple command bot)
- Tango Discord Agent (autonomous LLM agent)
- FLEET protocol (inter-bot delegation)
- MCP tool integration (GitHub, Gmail, Cloudflare, etc.)
- Persistent memory (pgvector)

**Schubert Server:**
- Service management (systemd)
- Network configuration (Caddy, Cloudflare, Tailscale)
- Shared services (LiteLLM, Ollama, PostgreSQL)
- Port reservations
- File system layout
- Git operations
- Deployment workflow

### What This Directory Does NOT Cover

- **Project Foxtrot** (port 3010) — separate project
- **MeetScribe** (port 8010) — separate project
- **Watson AI** (OpenHands) — separate project
- **Pumpkin AI** (Open WebUI) — separate project
- **Non-Tango services** — caddy, cloudflared, tailscaled
- **Human-only operations** — AGENTS.md modifications, production deployments

## Maintenance

### Weekly
- Review and update `project-context.md` if architecture changes
- Check `coding-patterns.md` for new anti-patterns discovered
- Update `discord-bot-fleet.md` if bots are added/modified

### On Major Changes
- Update relevant memory files immediately
- Add ADR to `docs/decisions/` if architectural
- Update CHANGELOG.md
- Test AI agent behavior with new context

### Quarterly
- Audit all memory files for accuracy
- Remove outdated information
- Consolidate related information
- Update quick references

## Version History

- **2026-08-17:** Initial creation with 7 files
  - `rules/project-rules.md` — Mandatory rules and constraints
  - `memories/project-context.md` — Tango voice architecture
  - `memories/coding-patterns.md` — Code patterns and pitfalls
  - `memories/device-specifics.md` — Schubert environment
  - `memories/discord-bot-fleet.md` — Discord bot ecosystem
  - `memories/discord-bot-reference.md` — Quick reference
  - `settings.json` — Editor configuration

## Contact

**Project Owner:** EdStratum Labs  
**Email:** founder@edstratumlabs.ai  
**Server:** Schubert Nexus (schubert.life)

For questions about this AI context structure or to propose additions, contact the project owner.
