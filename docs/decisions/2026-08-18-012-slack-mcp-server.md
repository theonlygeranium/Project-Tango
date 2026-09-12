# ADR-012: Slack MCP Server for Discord Bot Fleet

**Date:** 2026-08-18  
**Status:** Accepted  
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

Phase 1 of the Discord-Slack integration (ADR-011) implemented outbound notifications via incoming webhooks. This enables Discord bots to send alerts to Slack but does not provide bidirectional access.

The Discord bot fleet (Admiral Schubert, The Architect, Dr. Voss, The Proctor, etc.) needs the ability to:
- Search Slack message history (217k+ messages)
- Read channel conversations
- Access user profiles and workspace metadata
- Optionally post messages and reactions

The existing WRITER Agent has Slack MCP access via Cursor's `plugin-slack-slack`, but this is:
- Cursor-specific (not accessible from standalone Python Discord bots)
- Not exposed as an HTTP endpoint
- Designed for Cursor Agent, not Discord bot fleet

## Decision

Deploy a **standalone Slack MCP server** using the Streamable HTTP transport that Discord bots can connect to via their existing `mcp_client.py` infrastructure.

### Technical Implementation

1. **MCP Server Package:** `@zencoderai/slack-mcp-server` (npm)
   - Actively maintained fork of Anthropic's original reference implementation
   - Supports Streamable HTTP transport (required for Discord bots)
   - Compatible with MCP SDK v1.13.2
   - MIT/Apache 2.0 licensed

2. **Deployment:**
   - systemd service: `slack-mcp.service`
   - Port: 8075 (next available after Gmail MCP on 8071)
   - User: z121532 (unprivileged)
   - Transport: Streamable HTTP (JSON-RPC 2.0 over HTTP POST)

3. **Authentication:**
   - Reuse existing Slack app infrastructure (if available)
   - Otherwise: Create new Slack app "Tango MCP Server"
   - Required: Bot token (`xoxb-...`) and Team ID (`T...`)
   - Token stored in `/opt/Project-Tango/.env` (mode 600)

4. **MCP Client Configuration:**
   - Discord bots auto-discover via environment variables:
     ```bash
     MCP_SLACK_URL=http://127.0.0.1:8075/mcp
     MCP_SLACK_ENABLED=true
     MCP_SLACK_TIMEOUT=90
     ```
   - Existing `mcp_client.py` handles connection, tool discovery, routing
   - Tools namespaced as `slack__tool_name`

5. **Available Tools (8 core functions):**
   - `slack__list_channels` - List workspace channels
   - `slack__post_message` - Send message to channel
   - `slack__reply_to_thread` - Reply to thread
   - `slack__add_reaction` - Add emoji reaction
   - `slack__get_channel_history` - Read channel messages
   - `slack__get_thread_replies` - Read thread replies
   - `slack__list_users` - List workspace members
   - `slack__get_user_profile` - Get user details

## Rationale

### Why Standalone MCP Server

**Pros:**
- ✅ Accessible from any process (not just Cursor)
- ✅ Consistent with existing MCP architecture (GitHub MCP, Gmail MCP, etc.)
- ✅ Discord bots already have `mcp_client.py` that auto-discovers HTTP servers
- ✅ Independent lifecycle (restart Slack MCP without restarting Discord bots)
- ✅ Matches Schubert's existing pattern (15 MCP servers already deployed)

**Cons:**
- ❌ Additional service to maintain (systemd unit, logs, monitoring)
- ❌ Requires separate Slack bot token (cannot reuse WRITER Agent token)
- ❌ Extra hop in request path (Discord bot → MCP client → Slack MCP → Slack API)

### Why zencoderai/slack-mcp-server

**Alternatives Considered:**

| Option | Status | Pros | Cons |
|---|---|---|---|
| **Official Slack MCP** (https://mcp.slack.com/mcp) | Available | Slack-managed, enterprise-ready | Requires OAuth flow, cloud-hosted, less control |
| **zencoderai/slack-mcp-server** | ✅ **Selected** | Actively maintained, HTTP transport, full feature set | Community-maintained |
| **korotovsky/slack-mcp-server** | Considered | Stealth mode, GovSlack support, rich features | Go-based (new language to maintain), more complex |
| **jtalk22/slack-mcp-server** | Considered | Browser session auth, no admin approval | Session-based auth not suitable for headless bots |
| **Write custom MCP server** | Rejected | Full control, custom features | High maintenance burden, reinvents wheel |

**Why zencoderai:**
- Direct fork of Anthropic's original reference implementation (proven codebase)
- Supports Streamable HTTP transport (required for Discord bots)
- Modern MCP SDK (v1.13.2)
- Simple deployment (npm install, no Docker required)
- Actively maintained (last update: 2025-07-16, 941 weekly downloads)
- Clean MIT/Apache 2.0 licensing

### Why Not Use Cursor's plugin-slack-slack

Cursor's Slack plugin is:
- Embedded in Cursor's process (not exposed as HTTP endpoint)
- Designed for Cursor Agent use cases (not Discord bots)
- Not accessible from external processes

To make Discord bots use it, we would need to:
1. Extract the plugin and run it standalone (non-standard)
2. Reverse-engineer Cursor's plugin architecture (fragile)
3. Maintain a custom fork (high burden)

Deploying a standard Slack MCP server is the supported path.

## Alternatives Considered

### Option 1: Direct Slack API Integration

Write custom Slack API wrapper in Discord bots.

**Rejected because:**
- Reinvents MCP standard (loses tool discovery, standardized interface)
- Duplicates code across multiple bots
- No LLM-friendly tool schema generation
- Doesn't align with existing MCP architecture pattern

### Option 2: Use WRITER Agent as Proxy

Have Discord bots ask WRITER Agent to query Slack, then relay results.

**Rejected because:**
- Adds indirection and latency (Discord → WRITER → Slack → WRITER → Discord)
- WRITER Agent is not always running in the same context
- Creates coupling between Discord bots and WRITER Agent
- WRITER Agent context is for Cursor operations, not Discord bot operations

### Option 3: Wait for Official Slack MCP

Use Slack's official MCP server at `https://mcp.slack.com/mcp`.

**Deferred because:**
- Requires OAuth flow (more complex setup)
- Cloud-hosted (less control over availability)
- May have rate limits or enterprise restrictions
- Can revisit in Phase 3 if self-hosted becomes a burden

## Consequences

### Positive

- ✅ **Discord bots gain full Slack read access** within 2-4 hours
- ✅ **Reuses existing infrastructure:** MCP client already in bots, just add server
- ✅ **Consistent architecture:** Matches GitHub MCP, Gmail MCP pattern
- ✅ **Auto-discovery:** Bots discover tools automatically via `mcp_client.py`
- ✅ **Low maintenance:** npm package with active community support
- ✅ **Flexible permissions:** Bot only accesses channels it's invited to
- ✅ **Enables Phase 2-5:** Foundation for search, bridge, memory, commands

### Negative

- ❌ **New service to monitor:** Add to health checks, restart on failure
- ❌ **Separate Slack app:** Requires creating/configuring Slack bot if one doesn't exist
- ❌ **Port management:** Must ensure port 8075 doesn't conflict
- ❌ **Token management:** Another secret in `.env` to protect

### Neutral

- ⚪ **Node.js dependency:** Adds npm package to deployment (but Node.js already installed)
- ⚪ **Community-maintained code:** Not Slack-official, but proven codebase (Anthropic origin)

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| npm package abandoned | Low | Medium | Fork and maintain, or switch to korotovsky or official Slack MCP |
| Slack API rate limits | Medium | Medium | Implement caching, respect rate limits in bot logic |
| Token expiration | Low | High | Monitor auth.test, alert on failures, document refresh process |
| MCP server crashes | Medium | Medium | systemd auto-restart, monitor with Dr. Voss, escalate to Proctor |

## Implementation Checklist

**Phase 2A: Deploy Slack MCP Server (2-4 hours)**
- [x] Research MCP server options
- [x] Select zencoderai/slack-mcp-server
- [x] Install npm package globally
- [x] Create systemd service file
- [ ] Create Slack app and get bot token (human-required)
- [ ] Add credentials to `.env`
- [ ] Deploy systemd service
- [ ] Verify port 8075 is listening
- [ ] Add MCP_SLACK_* env vars
- [ ] Restart Discord bot services
- [ ] Verify tool discovery in logs
- [ ] Test Slack search from Discord

**Phase 2B: Documentation & Monitoring**
- [x] Create SLACK_MCP_SETUP.md
- [x] Update ADR-012
- [ ] Update CHANGELOG.md
- [ ] Update architecture.md (add Slack MCP to diagram)
- [ ] Add Dr. Voss health check for Slack MCP
- [ ] Add Slack MCP to Proctor test framework

**Phase 2C: Integration Testing**
- [ ] Test from The Architect channel (1539473266400432208)
- [ ] Test search functionality
- [ ] Test channel listing
- [ ] Test message reading
- [ ] Test user profile lookup
- [ ] Verify permissions/scopes work correctly

## References

- **Wiki:** https://wiki.edstratumlabs.ai/doc/discord-slack-integration-opportunities-2yY7IDXbeW
- **ADR-011:** Discord-Slack cross-platform notifications (Phase 1)
- **Package:** https://github.com/zencoderai/slack-mcp-server
- **Setup Guide:** `/opt/Project-Tango/docs/SLACK_MCP_SETUP.md`
- **Service File:** `/opt/Project-Tango/deploy/slack-mcp.service`
- **MCP Client:** `/opt/Project-Tango/scripts/mcp_client.py`
- **Slack API Docs:** https://api.slack.com/docs
- **MCP Spec:** https://spec.modelcontextprotocol.io/

---

**Next ADR:** ADR-013 will cover Phase 3 (Bi-Directional Message Bridge) once Phase 2 is verified in production.
