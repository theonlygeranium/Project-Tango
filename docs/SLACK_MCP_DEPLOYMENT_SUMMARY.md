# Phase 2 Deployment Summary

**Status:** Ready for deployment (requires Slack bot token)  
**Date:** 2026-08-18  
**Estimated Time:** 2-4 hours (mostly waiting for Slack app approval)

---

## What's Been Completed

✅ **Infrastructure:**
- `@zencoderai/slack-mcp-server` npm package installed globally
- systemd service file created: `/opt/Project-Tango/deploy/slack-mcp.service`
- Port 8075 selected (next available after Gmail MCP on 8071)
- Node.js v22.23.2 and npm v10.9.8 verified

✅ **Documentation:**
- Complete setup guide: `/opt/Project-Tango/docs/SLACK_MCP_SETUP.md`
- Architectural decision record: `/opt/Project-Tango/docs/decisions/2026-08-18-012-slack-mcp-server.md`
- Updated `.env.example` with MCP configuration
- Updated CHANGELOG.md with Phase 2 entry

✅ **Configuration:**
- Service configured to run as user z121532
- Environment variable schema defined
- MCP client integration documented

---

## What Needs Human Action

### Required Steps (15-30 minutes)

**Step 1: Create Slack Bot App**
1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. App Name: `Tango MCP Server`
4. Select workspace
5. Navigate to "OAuth & Permissions"
6. Add Bot Token Scopes (see list in `SLACK_MCP_SETUP.md`)
7. Click "Install to Workspace"
8. Copy Bot User OAuth Token (starts with `xoxb-`)

**Step 2: Get Team ID**
- From workspace URL: `https://app.slack.com/client/T0XXXXXXXXX/...`
- Or use: `curl -H "Authorization: Bearer xoxb-..." https://slack.com/api/team.info | jq -r '.team.id'`

**Step 3: Configure `.env`**

```bash
sudo -u z121532 nano /opt/Project-Tango/.env
```

Add these lines:
```bash
# Slack MCP Server
SLACK_BOT_TOKEN=xoxb-your-actual-token-here
SLACK_TEAM_ID=T0XXXXXXXXX

# MCP Servers Configuration
MCP_SLACK_URL=http://127.0.0.1:8075/mcp
MCP_SLACK_ENABLED=true
MCP_SLACK_TIMEOUT=90
```

**Step 4: Deploy Service**

```bash
# Install service
sudo cp /opt/Project-Tango/deploy/slack-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload

# Start service
sudo systemctl enable slack-mcp.service
sudo systemctl start slack-mcp.service

# Verify
sudo systemctl status slack-mcp.service
ss -tlnp | grep 8075
```

**Step 5: Restart Discord Bots**

```bash
# Restart The Architect (primary bot for testing)
sudo systemctl restart schubert-architect.service

# Optional: Restart other bots
sudo systemctl restart schubert-bot.service
sudo systemctl restart schubert-dr-voss.service
```

**Step 6: Verify Integration**

```bash
# Check Architect discovered Slack MCP
sudo journalctl -u schubert-architect -n 100 --no-pager | grep -i "slack\|mcp"

# Should see:
# "Loaded MCP server config from env: slack -> http://127.0.0.1:8075/mcp"
# "Connected to MCP server: slack"
# "Discovered X tools from slack MCP server"
```

**Step 7: Test from Discord**

Go to Discord channel `1539473266400432208` (The Architect's work channel):

```
@The Architect what Slack channels are available?
```

```
@The Architect search Slack for messages about "deployment"
```

---

## Expected Capabilities After Deployment

### From The Architect's Discord Channel

✅ **Search Slack:**
```
@The Architect search Slack for "API changes"
```

✅ **List Channels:**
```
@The Architect what Slack channels exist?
```

✅ **Read Channel History:**
```
@The Architect read the last 10 messages from #tango-ops
```

✅ **Get User Info:**
```
@The Architect who is user U098QT0F9A9 in Slack?
```

✅ **Read Threads:**
```
@The Architect read the thread for message 1234567890.123456 in #general
```

### Technical Details

**Tools Available (8 functions):**
- `slack__list_channels`
- `slack__post_message`
- `slack__reply_to_thread`
- `slack__add_reaction`
- `slack__get_channel_history`
- `slack__get_thread_replies`
- `slack__list_users`
- `slack__get_user_profile`

**Architecture:**
```
Discord → The Architect Bot → mcp_client.py → Slack MCP Server (port 8075) → Slack API
```

**Permissions:**
- Bot sees only channels it's invited to
- Honors Slack's native permission model
- Cannot read other users' DMs
- Search respects Slack visibility rules

---

## Troubleshooting Commands

```bash
# Check Slack MCP service
sudo systemctl status slack-mcp.service
sudo journalctl -u slack-mcp -n 50 --no-pager

# Check Discord bot logs
sudo journalctl -u schubert-architect -n 100 --no-pager

# Test MCP endpoint directly
curl -X POST http://127.0.0.1:8075/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Test Slack token
curl -H "Authorization: Bearer xoxb-YOUR-TOKEN" \
  https://slack.com/api/auth.test
```

---

## Rollback Procedure

If issues arise:

```bash
# Stop Slack MCP
sudo systemctl stop slack-mcp.service
sudo systemctl disable slack-mcp.service

# Remove MCP config from .env
sudo -u z121532 nano /opt/Project-Tango/.env
# Comment out or remove MCP_SLACK_* lines

# Restart Discord bots
sudo systemctl restart schubert-architect.service
```

Discord bots will continue functioning normally without Slack access.

---

## Next Steps (After Verification)

1. **Monitor usage** for 24-48 hours
2. **Deploy Phase 1 webhooks** (outbound notifications)
3. **Add health checks** to Dr. Voss for Slack MCP
4. **Add Proctor tests** for Slack MCP connectivity
5. **Phase 3 planning:** Bi-directional message bridge

---

## Key Files

- **Setup Guide:** `/opt/Project-Tango/docs/SLACK_MCP_SETUP.md` (detailed instructions)
- **Service File:** `/opt/Project-Tango/deploy/slack-mcp.service`
- **ADR:** `/opt/Project-Tango/docs/decisions/2026-08-18-012-slack-mcp-server.md`
- **CHANGELOG:** `/opt/Project-Tango/CHANGELOG.md` (Phase 2 entry added)
- **MCP Client:** `/opt/Project-Tango/scripts/mcp_client.py` (already present)

---

## Success Criteria

✅ **Service Health:**
- `slack-mcp.service` is active and running
- Port 8075 is listening
- No errors in journalctl logs

✅ **MCP Discovery:**
- Discord bots log "Loaded MCP server config from env: slack"
- Tools discovered and indexed

✅ **Functional Testing:**
- Can list Slack channels from Discord
- Can search Slack messages from Discord
- Can read channel history from Discord
- Results formatted correctly in Discord responses

✅ **Performance:**
- Response time < 5 seconds for typical queries
- No rate limit errors
- Stable operation for 24 hours

---

**Deployment Owner:** Jeff Geronimo  
**Technical Contact:** EdStratum Labs  
**Escalation:** File issue in Discord if problems arise
