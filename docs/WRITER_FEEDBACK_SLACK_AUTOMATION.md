# Discord to Slack - Writer Feedback Summary Automation

## ✅ SOLUTION DEPLOYED (Updated 2026-08-19)

The Architect bot can now send the Writer Event Feedback Summary to Slack from the kickstart-demo Discord channel.

**Recent Fix (2026-08-19):** Resolved two issues:
1. MCP client initialization order - button now created after MCP client is ready
2. Slack tool name - uses `slack__post_message` (custom MCP server with namespace format `server__tool`)

**Note:** The Discord bots use a custom Slack MCP server (slack-mcp binary) which uses the `slack__tool` naming convention, different from the Cursor Slack MCP plugin which uses `slack_tool` (no double underscore).

## Configuration

**Discord Channel:** kickstart-demo (ID: 1539657495142998078)  
**Slack Channel:** demo-cape-webinars (ID: C0BR92E39PW)  
**Bot:** The Architect (ID: 1538766501035642890)

## How to Use

In the **#kickstart-demo** Discord channel, ask The Architect:

### Natural Language (Recommended)
```
@The Architect send the Writer Event Feedback Summary to Slack
```

Or simply:
```
@The Architect post feedback summary to slack
```

Or:
```
@The Architect share the Writer event results with demo-cape-webinars
```

### What Happens
1. The Architect detects your request in the kickstart-demo channel
2. Uses the `send_writer_feedback_to_slack` tool (newly added)
3. Sends the complete formatted message to Slack #demo-cape-webinars via MCP
4. Confirms delivery in Discord

## Message Content

The message includes:
- 📊 At a Glance (5 key metrics: NPS +60, 4.50/5 rating, 90% ready to implement)
- ✨ What's Working (top 5 positive themes)
- 🛠️ What Needs Improvement (8 signals)
- 🎯 Top Use Cases Requested (10 use cases)
- 🚧 Top Barriers to Adoption (6 barriers)
- 🎯 Action Items — Sales (6 action items)
- 📣 Action Items — Marketing (6 action items)
- 📈 Follow-Up Pipeline (5 types, 30 responses)
- 🔥 Top Hot Accounts (10 companies)
- 💡 3 Most Important Insights
- 🏁 Single Highest-Priority Next Action

Total: ~6,400 characters, fully formatted with Slack markdown (tables, emojis, headers).

## Technical Implementation (Updated 2026-08-19)

**Root Cause of "MCP client not available" Error:**
The button view was being created during bot startup **before** the MCP client was initialized. The button stored a reference to `None`, causing all button clicks to fail.

**Fix Applied:**
1. Reordered `on_ready()` in `architect-bot.py`:
   - MCP client initialization moved earlier
   - Button view registration now happens **after** MCP client is ready
   - Added `bot.add_view(SendFeedbackButtonView(mcp_client))` to register persistent view
2. Enhanced `post_kickstart_button()`:
   - Added `force_refresh` parameter to delete old button and post fresh one
   - Improved error handling
3. Added `!refresh-button` admin command for manual button refresh

**Initialization Order (Correct):**
1. Bot comes online
2. Memory store initialized
3. Channel onboarding
4. Multi-agent coordinator
5. Metrics collector
6. **MCP client initialized** ← Must happen before button
7. **Button view registered with MCP client**
8. **Button posted to Discord channel**
9. Health monitor started
10. Auto-updater started

**Files Modified:**
- `/opt/Project-Tango/scripts/architect-bot.py`
  - Fixed MCP client initialization order (lines 4142-4188 in `on_ready()`)
  - Added `bot.add_view()` registration for persistent button (line 4155)
  - Moved button posting after MCP initialization (line 4180)
  - Enhanced `post_kickstart_button()` with `force_refresh` parameter
  - Added `!refresh-button` admin command (line 4514)

**Files Created:**
- `/opt/Project-Tango/scripts/send_feedback_slack.py` - Message content
- `/opt/Project-Tango/scripts/discord_to_slack_automation.py` - UI components
- `/opt/Project-Tango/scripts/refresh_kickstart_button.py` - One-time button refresh utility
- `/opt/Project-Tango/docs/DISCORD_TO_SLACK_AUTOMATION.md` - Documentation

**Service Status:**
- ✅ schubert-architect.service restarted at 2026-08-19 16:40:07
- ✅ The Architect online and monitoring kickstart-demo channel
- ✅ MCP client connected (Slack integration active)
- ✅ Button view registered with MCP client (initialization order fixed)
- ✅ Slack tool name: `slack__post_message` (custom MCP server format)

## Why The Architect?

Admiral Schubert is channel-locked to its own channel (1538476446157115442) for security reasons. The Architect has more flexible channel access and is perfect for this cross-channel automation.

## Example Usage

```
User (in #kickstart-demo): @The Architect send feedback summary to slack

The Architect: ✅ Writer Event Feedback Summary sent to Slack #demo-cape-webinars.
```

## Troubleshooting

**"MCP client not available" error**
- **Fixed 2026-08-19:** The initialization order issue has been resolved. MCP client now initializes before button view creation.
- If the error persists, use `!refresh-button` command in The Architect's channel to recreate the button.
- Check MCP client connection: `sudo journalctl -u schubert-architect.service | grep -E "(MCP|button)"`

**"The Architect doesn't respond"**
- Make sure to @mention The Architect in kickstart-demo channel
- The Architect monitors: kickstart-demo (1539657495142998078), architect channel (1538767137080877056), and work channel (1539473266400432208)

**"Failed to send to Slack"**
- Check MCP client connection: `sudo journalctl -u schubert-architect.service | grep MCP`
- Verify Slack permissions for channel C0BR92E39PW

**"Wrong channel"**
- The automation only works from kickstart-demo Discord channel
- The Architect will respond but only send to Slack from that channel

## Future Enhancements

- Add scheduling capability (weekly sends)
- Track send history
- Update message with dynamic dates
- Add confirmation dialog before sending
- Support multiple message templates

---

**Status:** ✅ DEPLOYED AND WORKING  
**Last Updated:** 2026-08-19 16:40  
**Last Fix:** Correct Slack MCP server tool format `slack__post_message` (2026-08-19 16:40)  
**Previous Fix:** MCP client initialization order (2026-08-19 16:25)  
**Deployed By:** Cursor Agent
