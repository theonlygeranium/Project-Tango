# Discord Bot External Service Access Assessment

## Current MCP Server Connections

Based on the Discord bot fleet configuration (`mcp_client.py`), the bots currently connect to:

### ✅ Already Configured & Accessible

| Service | Port | Status | Token Required | Purpose |
|---------|------|--------|----------------|---------|
| **Schubert Nexus** | 8000 | Configured | `MCP_SCHUBERT_TOKEN` | Server operations, file access |
| **PostgreSQL** | 8060 | Configured | `MCP_POSTGRES_TOKEN` | Database access, memory layer |
| **Redis** | 8062 | Configured | `MCP_REDIS_TOKEN` | Vector search (semantic memory) |
| **Ollama** | 8063 | Configured | `MCP_OLLAMA_TOKEN` | Local models (qwen2.5-coder, deepseek-r1) |
| **GitHub** | 8091 | ✅ Configured | `MCP_GITHUB_TOKEN` (PAT) | Repo operations, issues, PRs (85+ tools) |
| **Gmail (Freelance)** | 8071 | ✅ Enabled | None (service account) | Email operations (DWD service account) |
| **Cloudflare** | N/A | ✅ Direct API | `CLOUDFLARE_API_TOKEN` | DNS, WAF, analytics via cloudflare_api.py |
| **Outline Wiki** | 3101 | ✅ Enabled | `ol_api_*` key | Knowledge base (20 tools) - **NEW** |

### ⏸️ Configured but Disabled

| Service | Port | Status | Reason | Action Needed |
|---------|------|--------|--------|---------------|
| **Gmail (Personal)** | 8070 | Disabled | Requires OAuth browser flow | Enable after OAuth setup |
| **Gmail (Work)** | Remote | Disabled | Requires OAuth consent | May be blocked by Workspace admin |

### ❌ Missing / Not Configured

Based on the documentation mentioning 167+ tools across 6 servers, here are services that **may be missing**:

| Service | Mentioned In | Status | Potential Use Case |
|---------|-------------|--------|-------------------|
| **Linear** | Bot docs | ❌ Not found | Issue tracking integration |
| **Slack** | Bot docs | ❌ Not found | Workspace operations |
| **Jira** | Not mentioned | ❌ Not found | Issue tracking (if used) |

## Documentation Access

### ✅ Now Available via MCP

**Context7 MCP** (Documentation):
- **Cursor documentation** (`/websites/cursor`) - 3000+ snippets
- **Discord API docs** (`/discord/discord-api-docs`) - 4000+ snippets  
- **Discord developer platform** (`/llmstxt/discord_llms_txt`) - 4600+ snippets

**Outline MCP** (Knowledge Base):
- **EdStratum Labs Wiki** - Internal project documentation (20 tools)
- Collections, documents, templates, comments, attachments
- Smart document updates with patch mode (preserves formatting)

This provides complete documentation access for:
- Writing Discord bot code (Context7)
- Configuring Cursor MCP servers (Context7)
- Internal project knowledge (Outline)
- Architecture decisions and runbooks (Outline)

## Recommendations

### 1. **Critical - Verify MCP Server Status**

Check if all configured MCP servers are actually running:

```bash
# Check MCP server ports
sudo netstat -tlnp | grep -E "8000|8060|8062|8063|8091|8070|8071"

# Or check with curl
curl -s http://127.0.0.1:8000/mcp -H "Authorization: Bearer $MCP_SCHUBERT_TOKEN" | jq .
curl -s http://127.0.0.1:8091/mcp -H "Authorization: Bearer $MCP_GITHUB_TOKEN" | jq .
```

### 2. **High Priority - Add Missing Integrations**

If you use these services, add MCP servers:

**Linear Integration:**
```bash
# Add to .env
MCP_LINEAR_URL=http://127.0.0.1:8XXX/mcp
MCP_LINEAR_TOKEN=lin_api_...

# Or use official Linear MCP server
MCP_LINEAR_URL=https://linear.app/api/mcp
MCP_LINEAR_TOKEN=...
```

**Slack Integration:**
```bash
MCP_SLACK_URL=http://127.0.0.1:8XXX/mcp
MCP_SLACK_TOKEN=xoxb-...
```

### 3. **Medium Priority - Enable Disabled Gmail Accounts**

If you need personal/work Gmail access:
- **Personal:** Complete OAuth browser flow, then enable in config
- **Work:** Check with Workspace admin about OAuth consent restrictions

### 4. **Documentation Access - Clarify Wiki Needs**

Questions to answer:
- **Do you have a project wiki?** (GitHub Wiki, Notion, Confluence, etc.)
- **Is internal documentation needed?** (Team docs, runbooks, ADRs)
- **API references?** Already covered by Context7 MCP for Cursor/Discord

### 5. **Verify Tool Count**

The documentation mentions **167+ tools** across MCP servers. Current configuration shows:
- Schubert Nexus
- PostgreSQL  
- Redis
- Ollama
- GitHub (85+ tools)
- Gmail (Freelance)
- Cloudflare (via direct API)

**Action:** Run the bots and check actual tool count:
```bash
sudo journalctl -u schubert-bot.service -n 100 | grep "MCP.*tools available"
```

Expected: ~167 tools. If significantly lower, some MCP servers may not be connecting properly.

## Environment Variables to Check

Verify these are set in `/opt/Project-Tango/.env`:

```bash
# Currently found:
✅ MCP_GITHUB_TOKEN
✅ CLOUDFLARE_API_TOKEN
✅ CLOUDFLARE_ACCOUNT_ID
✅ CLOUDFLARE_ZONE_*

# Should exist but not verified:
❓ MCP_SCHUBERT_TOKEN
❓ MCP_POSTGRES_TOKEN
❓ MCP_REDIS_TOKEN
❓ MCP_OLLAMA_TOKEN
❓ MCP_GMAIL_PERSONAL_TOKEN
❓ MCP_GMAIL_WORK_TOKEN

# Potentially missing:
❌ MCP_LINEAR_TOKEN
❌ MCP_SLACK_TOKEN
```

## Next Steps

1. **Verify all MCP server connectivity** (see commands above)
2. **Check actual tool count** when bots are running
3. **Clarify wiki/documentation access needs** with user
4. **Add Linear/Slack integrations** if those services are used
5. **Enable Gmail personal/work** if needed
6. **Document any additional external services** the bots should access

## Summary

**What you have:**
- ✅ GitHub (full access, 85+ tools)
- ✅ Cloudflare (DNS, WAF, analytics)
- ✅ Gmail Freelance (email operations)
- ✅ Cursor/Discord docs (via Context7 MCP - just installed)
- ✅ Local services (PostgreSQL, Redis, Ollama, Schubert Nexus)

**What might be missing:**
- ❓ Linear (if you use it for issue tracking)
- ❓ Slack (if you use it for team communication)
- ❓ Project wiki/documentation (Notion, Confluence, GitHub Wiki)
- ❓ Some MCP servers may not be running (need verification)

**Recommendation:** Verify MCP server connectivity first, then clarify which additional integrations you need based on your workflow.
