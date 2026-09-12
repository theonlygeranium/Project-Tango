# ADR: Voice Agent MCP Knowledge Access

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Project Tango runs two parallel agent surfaces on Schubert:

1. **Discord fleet bots** — use a dynamic MCP client (`scripts/mcp_client.py`) that connects to Schubert MCP servers (GitHub, Postgres, Redis, Ollama, Schubert shell/fs, Gmail) and discovers tools at runtime via `tools/list`.
2. **Voice agents** — the `Jarvis` agent (subclass of `livekit.agents.Agent`) has only a single `web_search` function tool. No GitHub, Postgres, Redis, or shell access.

This asymmetry means voice personas cannot answer questions about the user's GitHub repos, project memory, or database state — capabilities the Discord bots already have.

## Decision

Bridge the existing MCP client (`scripts/mcp_client.py`) into the LiveKit voice agent tool surface via a new module `backend/mcp_tools.py`. The bridge:

- Reuses `MCPClient` and `build_default_client()` from the existing module (no fork).
- Connects to MCP servers at worker startup (co-located on Schubert, so `127.0.0.1` URLs resolve identically).
- Filters tools per-persona via `Persona.enabled_mcp_servers`.
- Enforces a read-only allowlist (`READ_ONLY_TOOL_PATTERNS`) — write/destructive tools are excluded by default.
- Wraps each MCP tool as a LiveKit `function_tool` that delegates to `mcp_client.call_tool()`.
- Provides a master switch `TANGO_MCP_TOOLS=false` to disable all MCP tool access.

## Rationale

- **Co-location**: The voice worker and MCP servers all run on Schubert. No new network path, tunnel, or external exposure is needed.
- **Precedent**: `backend/search_tools.py` already ports a Discord-bot capability (Serper.dev web search) into the voice path. This follows the same pattern.
- **Security**: Per-persona scoping + read-only allowlist + master switch provides three layers of defense. The `schubert` server (shell/filesystem) is excluded from all voice personas by default.
- **Product-manager summarization**: MCP tool results are raw, dense payloads. A system-prompt guidance section makes personas summarize like a PM — qualitative by default, quantitative only on explicit request — keeping voice turns short and intelligible.

## Alternatives Considered

1. **Per-persona hardcoded tools** — rejected: not dynamic, would require code changes for each new tool.
2. **Full write access** — rejected: security risk for end-user-facing voice personas.
3. **Separate MCP client fork** — rejected: maintenance burden, divergence from the Discord fleet's tested client.
4. **Output rewriting** — rejected: would hide information the LLM needs for follow-up questions. System-prompt injection shapes how the LLM speaks about data it already has.

## Consequences

- New env vars: `TANGO_MCP_TOOLS`, `MCP_SCHUBERT_TOKEN`, `MCP_POSTGRES_TOKEN`, `MCP_REDIS_TOKEN`, `MCP_OLLAMA_TOKEN`, `MCP_GITHUB_TOKEN`.
- Deploy step: `scripts/deploy.sh` now symlinks `scripts/mcp_client.py` → `backend/mcp_client.py`.
- Latency: MCP tool calls add tens to hundreds of milliseconds inside a voice turn. Mitigated by LLM-initiated (not auto-injected) tool calls and the summarization guidance.
- Future admin-only expansion (write tools, `schubert` server) requires its own ADR and is explicitly deferred.

## References

- SPEC-006: Voice Agent MCP Knowledge Access (wiki)
- `backend/mcp_tools.py` — the bridge module
- `scripts/mcp_client.py` — the MCP client reused from the Discord fleet
- `backend/search_tools.py` — precedent for porting Discord capabilities into the voice path
- `docs/decisions/2026-07-22-010-account-authentication-and-persona-authorization.md` — account/persona authorization boundary
