# Slack MCP Server Setup Guide

**Phase 2: Bidirectional Discord ↔ Slack Integration**

This guide covers deploying the Slack MCP Server to enable Discord bots (The Architect, Admiral Schubert, etc.) to access Slack workspace data: search messages, read channels, get user profiles, and more.

---

## Prerequisites

✅ **Already completed:**
- Node.js v22.23.2 installed
- npm v10.9.8 installed
- `@zencoderai/slack-mcp-server` package installed globally

⏳ **Needs completion:**
- Slack Bot Token (`xoxb-...`)
- Slack Team ID

---

## Step 1: Create Slack Bot App

### 1.1 Create New Slack App

1. Go to https://api.slack.com/apps
2. Click **"Create New App"**
3. Choose **"From scratch"**
4. App Name: `Tango MCP Server`
5. Select your workspace
6. Click **"Create App"**

### 1.2 Configure OAuth Scopes

Navigate to **OAuth & Permissions** and add these Bot Token Scopes:

**Required Scopes (Read Access):**
```
channels:history       # Read messages from public channels
channels:read          # List public channels
chat:write            # Send messages (if you want write access)
groups:history         # Read messages from private channels
groups:read           # List private channels
im:history            # Read direct messages
im:read               # List DMs
mpim:history          # Read group DMs
mpim:read             # List group DMs
reactions:read        # Read emoji reactions
users:read            # Read user info
users:read.email      # Read user emails
search:read           # Use Slack search API
files:read            # Read file info
```

**Optional Scopes (Write Access):**
```
chat:write            # Post messages
chat:write.public     # Post to channels bot isn't in
reactions:write       # Add emoji reactions
```

### 1.3 Install App to Workspace

1. Scroll to **"OAuth Tokens for Your Workspace"**
2. Click **"Install to Workspace"**
3. Review permissions and click **"Allow"**
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### 1.4 Get Team ID

Two ways to get your Team ID:

**Method 1: From Workspace URL**
```
https://app.slack.com/client/T0XXXXXXXXX/C0XXXXXXXXX
                              ^^^^^^^^^^^
                              This is your Team ID
```

**Method 2: From API**
```bash
curl -H "Authorization: Bearer xoxb-YOUR-BOT-TOKEN" \
  https://slack.com/api/team.info | jq -r '.team.id'
```

---

## Step 2: Configure Environment Variables

Edit `/opt/Project-Tango/.env` as user `z121532`:

```bash
sudo -u z121532 nano /opt/Project-Tango/.env
```

Add these lines (or update if they exist):

```bash
# Slack MCP Server (for Discord bot fleet access)
SLACK_BOT_TOKEN=xoxb-your-actual-bot-token-here
SLACK_TEAM_ID=T0XXXXXXXXX
```

**Security check:**
```bash
ls -la /opt/Project-Tango/.env
# Should show: -rw------- 1 z121532 z121532
```

---

## Step 3: Deploy Slack MCP Service

### 3.1 Install systemd Service

```bash
sudo cp /opt/Project-Tango/deploy/slack-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 3.2 Start Service

```bash
sudo systemctl enable slack-mcp.service
sudo systemctl start slack-mcp.service
```

### 3.3 Verify Service

```bash
# Check service status
sudo systemctl status slack-mcp.service

# Check if port 8075 is listening
ss -tlnp | grep 8075

# Check logs
sudo journalctl -u slack-mcp -n 50 --no-pager
```

**Expected output:**
```
● slack-mcp.service - Slack MCP Server (Streamable HTTP)
   Loaded: loaded (/etc/systemd/system/slack-mcp.service; enabled)
   Active: active (running) since ...
```

---

## Step 4: Configure Discord Bots to Use Slack MCP

### 4.1 Add MCP Server Configuration

Edit `/opt/Project-Tango/.env` again and add:

```bash
# MCP Servers Configuration
MCP_SLACK_URL=http://127.0.0.1:8075/mcp
MCP_SLACK_ENABLED=true
MCP_SLACK_TIMEOUT=90
```

### 4.2 Restart Discord Bot Services

The MCP client auto-discovers servers from environment variables. Restart the bots to load the new config:

```bash
# Restart The Architect
sudo systemctl restart schubert-architect.service

# Restart Admiral Schubert (if you want Slack access there too)
sudo systemctl restart schubert-bot.service

# Restart Dr. Voss
sudo systemctl restart schubert-dr-voss.service
```

### 4.3 Verify MCP Discovery

Check bot logs to confirm Slack MCP was discovered:

```bash
sudo journalctl -u schubert-architect -n 100 --no-pager | grep -i "slack\|mcp"
```

**Expected output:**
```
Loaded MCP server config from env: slack -> http://127.0.0.1:8075/mcp
Connected to MCP server: slack
Discovered X tools from slack MCP server
```

---

## Step 5: Test Slack Access from Discord

### 5.1 Go to Architect Channel

Navigate to Discord channel ID: `1539473266400432208` (The Architect's work channel)

### 5.2 Test Search

```
@The Architect search Slack for messages about "deployment"
```

### 5.3 Test Channel List

```
@The Architect what Slack channels are available?
```

### 5.4 Test Message Reading

```
@The Architect read the last 10 messages from #tango-ops in Slack
```

### 5.5 Check Available Tools

The Architect should now have access to these Slack tools (namespaced as `slack__tool_name`):

- `slack__list_channels` - List all channels
- `slack__post_message` - Send message to channel
- `slack__reply_to_thread` - Reply to thread
- `slack__add_reaction` - Add emoji reaction
- `slack__get_channel_history` - Read channel messages
- `slack__get_thread_replies` - Read thread replies
- `slack__list_users` - List workspace users
- `slack__get_user_profile` - Get user details

---

## Troubleshooting

### Issue: Service won't start

**Check 1: Verify slack-mcp binary**
```bash
which slack-mcp
# Should output: /usr/bin/slack-mcp
```

**Check 2: Test manual start**
```bash
SLACK_BOT_TOKEN=xoxb-... SLACK_TEAM_ID=T... \
  slack-mcp --transport http --port 8075
```

**Check 3: Review logs**
```bash
sudo journalctl -u slack-mcp -n 100 --no-pager
```

### Issue: Discord bots not discovering Slack MCP

**Check 1: Verify MCP env vars**
```bash
grep MCP_SLACK /opt/Project-Tango/.env
```

**Check 2: Restart bot with verbose logging**
```bash
sudo systemctl restart schubert-architect
sudo journalctl -u schubert-architect -f
# Watch for "Loaded MCP server config from env: slack"
```

**Check 3: Test MCP endpoint manually**
```bash
curl -X POST http://127.0.0.1:8075/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

### Issue: Slack API errors (invalid_auth)

**Check 1: Verify token format**
```bash
# Bot tokens start with xoxb-
echo $SLACK_BOT_TOKEN | grep -E '^xoxb-'
```

**Check 2: Test token with Slack API**
```bash
curl -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
  https://slack.com/api/auth.test
```

**Expected response:**
```json
{
  "ok": true,
  "url": "https://your-workspace.slack.com/",
  "team": "Your Workspace",
  "team_id": "T0XXXXXXXXX",
  "user": "tango-mcp-server",
  "user_id": "U0XXXXXXXXX"
}
```

### Issue: Permission errors (missing_scope)

**Solution:** Add the missing scope to your Slack app at https://api.slack.com/apps, then reinstall the app to your workspace.

---

## Security Considerations

### Token Storage

- ✅ `.env` file is mode 600, owned by z121532
- ✅ Never commit `.env` to git
- ✅ Bot token only has scopes it needs
- ✅ MCP server runs as unprivileged user z121532

### Access Control

- Bot only sees channels it's been invited to
- Honors Slack's native permission model
- Cannot read DMs of other users (only bot's own DMs)
- Search respects Slack's visibility rules

### Monitoring

```bash
# Watch Slack API calls
sudo journalctl -u slack-mcp -f | grep -i "api\|error"

# Check for failed auth attempts
sudo journalctl -u slack-mcp -n 100 | grep "invalid_auth\|unauthorized"
```

---

## Next Steps

Once Slack MCP is working:

1. **Test full integration**: Have The Architect search Slack and post results to Discord
2. **Enable webhooks (Phase 1)**: Set up incoming webhooks for outbound notifications
3. **Phase 3**: Implement bi-directional message bridge
4. **Phase 4**: Extend Admiral Schubert's memory to include Slack conversations
5. **Phase 5**: Add Slack slash commands to trigger Discord bot actions

---

## Architecture Diagram

```
Discord Channel (1539473266400432208)
         |
         | User: "@The Architect search Slack"
         |
         v
  The Architect Bot (schubert-architect.service)
         |
         | 1. LLM decides to use slack__search_messages tool
         |
         v
  MCP Client (mcp_client.py)
         |
         | 2. Routes to slack MCP server
         | POST http://127.0.0.1:8075/mcp
         |
         v
  Slack MCP Server (slack-mcp.service)
         |
         | 3. Calls Slack Web API
         | Authorization: Bearer xoxb-...
         |
         v
  Slack API (api.slack.com)
         |
         | 4. Returns search results
         |
         v
  [Results flow back through stack]
         |
         v
  Discord: The Architect posts formatted results
```

---

**Created:** 2026-08-18  
**Author:** Cursor Agent  
**Status:** Ready for deployment  
**Service:** `slack-mcp.service` on port 8075
