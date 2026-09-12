# Context7 MCP Integration for Project Tango

This directory contains the Context7 MCP integration for accessing up-to-date Cursor and Discord documentation.

## What's Installed

### 1. MCP Server Configuration (`mcp.json`)
Registers the Context7 MCP server that provides access to:
- **Cursor documentation** (`/websites/cursor`) - ~3000 snippets covering MCP, rules, skills, agents, cloud agents, hooks
- **Discord API docs** (`/discord/discord-api-docs`) - ~4000 snippets covering bot auth, gateway, REST, voice, SDKs
- **Discord developer platform** (`/llmstxt/discord_llms_txt`) - ~4600 snippets for broader platform + SDKs

### 2. Scoped Rule (`rules/consult-docs-sot.mdc`)
Instructs AI agents to query Context7 before writing or modifying code that touches:
- Cursor internals (MCP config, rules, skills, agents, hooks)
- Discord API (bot auth, gateway, REST endpoints, voice)

**Applies to:** `*.ts`, `*.js`, `*.py`, `*.json`, `*.md` files

### 3. Skill (`skills/cursor-discord-docs/SKILL.md`)
Provides detailed procedures for:
- Resolving library IDs
- Querying with specific questions
- Reading and citing returned snippets
- Writing code consistent with retrieved docs
- Query limits (max 3 calls per question)

**Applies to:** Code files and `.cursor/**/*`

## Activation Steps

1. **Enable the Context7 MCP server:**
   - Open Cursor → Settings → Customize → MCP
   - The `context7` server should appear (from `mcp.json`)
   - Enable it if not already active

2. **Restart Cursor session:**
   - Close and reopen Cursor to load the new rule and skill
   - Or run: Cmd/Ctrl + Shift + P → "Developer: Reload Window"

3. **Verify installation:**
   ```bash
   # Check files are in place
   ls -la /opt/Project-Tango/.cursor/mcp.json
   ls -la /opt/Project-Tango/.cursor/rules/consult-docs-sot.mdc
   ls -la /opt/Project-Tango/.cursor/skills/cursor-discord-docs/SKILL.md
   ```

## Usage

When working on Discord bot code or Cursor configuration, AI agents will automatically:
1. Query Context7 for current documentation
2. Use retrieved docs as source of truth (over model memory)
3. Cite source URLs in explanations
4. Limit to 3 queries per question to avoid API abuse

## Security Considerations

Per Cursor's MCP documentation:

- **Verify source:** The Context7 MCP server is from `@upstash/context7-mcp` (official Upstash package)
- **Review permissions:** Context7 is read-only with no authentication tokens required
- **Restricted keys:** No API keys or credentials stored in `mcp.json`
- **Audit code:** The MCP server code can be reviewed at https://github.com/upstash/context7-mcp
- **MCP Allowlist:** For team environments, consider using Cursor's MCP allowlist feature

### Blast Radius
- **Low risk:** Context7 only reads documentation; no write access to files or systems
- **No auth required:** No tokens or credentials needed
- **Network only:** Makes HTTPS requests to Upstash's Context7 API

## Validation Results

✅ MCP server configuration valid (stdio transport)  
✅ Rule scoped to relevant file types  
✅ Skill includes library ID table and query procedure  
✅ 3-call limit enforced  
✅ Security best practices followed (read-only, no secrets)  

## Files

```
.cursor/
├── mcp.json                              # Context7 MCP server registration
├── rules/
│   └── consult-docs-sot.mdc             # Rule: consult docs before coding
├── skills/
│   └── cursor-discord-docs/
│       └── SKILL.md                      # Skill: Cursor & Discord docs retrieval
└── README-CONTEXT7.md                    # This file
```

## Library IDs Reference

| Target | Library ID | Coverage |
|--------|-----------|----------|
| Cursor docs | `/websites/cursor` | MCP, rules, skills, agents, cloud agents, hooks |
| Discord API | `/discord/discord-api-docs` | Bot auth, gateway, REST, voice, SDKs |
| Discord platform | `/llmstxt/discord_llms_txt` | Broader developer platform + SDKs |

## Support

- **Context7 MCP:** https://github.com/upstash/context7-mcp
- **Cursor MCP Docs:** https://docs.cursor.com/advanced/mcp
- **Discord API Docs:** https://discord.com/developers/docs
