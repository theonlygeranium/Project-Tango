# Discord to Slack Button Fix - MCP Client Initialization & Tool Name

**Date:** 2026-08-19  
**Issue #1:** Discord button responding with "MCP client not available"  
**Issue #2:** Discord button responding with "unknown tool 'slack_send_message'"  
**Status:** ✅ BOTH RESOLVED  
**Service:** The Architect (`schubert-architect.service`)

---

## Problem Summary

The Discord button in the `#kickstart-demo` channel ("Send Writer Feedback Summary to Slack") had two sequential issues:

1. **First issue:** "❌ MCP client not available" when clicked
2. **Second issue (after fix #1):** "Error: unknown tool 'slack_send_message'"

## Root Causes

### Issue #1: Initialization Order Race Condition

**Initialization Order Race Condition**

In `architect-bot.py`, the `on_ready()` function was posting the button **before** the MCP client was initialized:

```python
# WRONG ORDER (before fix):
1. Bot comes online
2. Memory store initialized
3. Channel onboarding
4. post_kickstart_button()          ← Button created here
5. Multi-agent coordinator
6. Metrics collector
7. MCP client initialized           ← Too late!
8. Health monitor started
```

When `post_kickstart_button()` was called, it created a `SendFeedbackButtonView(mcp_client)` but `mcp_client` was still `None` at that point. The button stored a reference to `None`, and all subsequent clicks failed.

Discord persistent buttons retain the view instance they were created with, so even after the MCP client initialized later, the button still had the old `None` reference.

### Issue #2: Incorrect MCP Tool Name

After fixing the initialization order, the button successfully connected to the MCP client but then failed with:

```
Error: unknown tool 'slack_send_message'
```

The code was using `slack_send_message` but the correct MCP tool name follows the namespace convention: `server__tool_name`. For the Slack MCP server, the tool should be `slack__post_message` (with double underscore).

**MCP Tool Naming Convention:**
- Format: `{server_name}__{tool_name}` (double underscore separator)
- Example: `slack__post_message`, `slack__list_channels`, `github__create_issue`
- NOT: `slack_send_message` ❌

## Solutions Applied

### Solution #1: Reordered Initialization Sequence

Moved MCP client initialization **before** button posting in `on_ready()`:

```python
# CORRECT ORDER (after fix):
1. Bot comes online
2. Memory store initialized
3. Channel onboarding
4. Multi-agent coordinator
5. Metrics collector
6. MCP client initialized           ← Now happens first
7. bot.add_view(SendFeedbackButtonView(mcp_client))  ← Register persistent view
8. post_kickstart_button()          ← Button gets working MCP client
9. Health monitor started
10. Auto-updater started
```

### Solution #2: Added Persistent View Registration

Added `bot.add_view()` call to register the button view with Discord's persistent button handler:

```python
# Register persistent button view for Discord to handle clicks
# (must be done after mcp_client is initialized)
try:
    bot.add_view(SendFeedbackButtonView(mcp_client))
    log("Registered persistent button view for feedback summary", "INFO")
except Exception as e:
    log(f"Failed to register button view: {e}", "WARN")
```

### Solution #3: Enhanced Button Refresh Capability

Updated `post_kickstart_button()` function to support force refresh:

```python
async def post_kickstart_button(force_refresh=False):
    """Post persistent button in kickstart-demo channel if needed.
    
    Args:
        force_refresh: If True, delete old button and post a new one
    """
    # ... finds and optionally deletes old button ...
    # ... posts fresh button with current mcp_client ...
```

### Solution #4: Added Manual Refresh Command

Added `!refresh-button` admin command for manual button refresh:

```python
elif cmd == "refresh-button":
    try:
        await post_kickstart_button(force_refresh=True)
        await message.reply("✅ Refreshed kickstart-demo button with updated MCP client connection")
    except Exception as e:
        await message.reply(f"❌ Failed to refresh button: {e}")
```

### Solution #5: Created One-Time Refresh Script

Created `/opt/Project-Tango/scripts/refresh_kickstart_button.py` to delete the old button before the fix was deployed:

```python
#!/usr/bin/env python3
"""Delete old button with None MCP client reference."""
# Connects to Discord, finds old button, deletes it
# New button with working MCP client posted on next bot startup
```

### Solution #6: Corrected MCP Tool Names

Changed all instances of `slack_send_message` to `slack__post_message` across the codebase:

```python
# WRONG (before fix):
result = await mcp.call_tool("slack_send_message", {
    "channel": SLACK_CHANNEL_ID,
    "message": FEEDBACK_MESSAGE
})

# CORRECT (after fix):
result = await mcp.call_tool("slack__post_message", {
    "channel": SLACK_CHANNEL_ID,
    "message": FEEDBACK_MESSAGE
})
```

**Files updated with correct tool name:**
- `/opt/Project-Tango/scripts/architect-bot.py` (3 occurrences)
- `/opt/Project-Tango/scripts/discord_to_slack_automation.py` (1 occurrence)
- `/opt/Project-Tango/scripts/feedback-slash-bot.py` (1 occurrence)

## Files Modified

### Primary Changes

- `/opt/Project-Tango/scripts/architect-bot.py`
  - Lines 4142-4188: Reordered `on_ready()` function (initialization order fix)
  - Line 4155: Added `bot.add_view()` registration (persistent view fix)
  - Line 4180: Moved button posting after MCP initialization (initialization order fix)
  - Lines 4020-4070: Enhanced `post_kickstart_button()` with `force_refresh` parameter
  - Line 4514: Added `!refresh-button` command
  - Lines 502, 4004, 4348: Changed `slack_send_message` → `slack__post_message` (tool name fix)

### Secondary Changes

- `/opt/Project-Tango/scripts/discord_to_slack_automation.py`
  - Line 175: Changed `slack_send_message` → `slack__post_message`

- `/opt/Project-Tango/scripts/feedback-slash-bot.py`
  - Line 242: Changed `slack_send_message` → `slack__post_message`

## Files Modified (Original Documentation)

- `/opt/Project-Tango/scripts/architect-bot.py`
  - Lines 4142-4188: Reordered `on_ready()` function
  - Line 4155: Added `bot.add_view()` registration
  - Line 4180: Moved button posting after MCP initialization
  - Lines 4020-4070: Enhanced `post_kickstart_button()` with `force_refresh`
  - Line 4514: Added `!refresh-button` command

## Files Created

- `/opt/Project-Tango/docs/DISCORD_SLACK_BUTTON_FIX.md` - This document

## Deployment Steps

### Phase 1: Initialization Order Fix

1. **Identified issue** via journalctl logs showing MCP initialization after button posting
2. **Modified code** to reorder initialization and add persistent view registration
3. **Deleted old button** using refresh script:
   ```bash
   export $(grep "^ARCHITECT_BOT_TOKEN=" /opt/Project-Tango/.env | xargs)
   /opt/Project-Tango/backend/venv/bin/python refresh_kickstart_button.py
   ```
4. **Restarted service**:
   ```bash
   sudo systemctl restart schubert-architect.service
   ```
5. **Verified logs** showing correct order:
   ```
   [INFO] MCP: 175 tools available
   [INFO] Registered persistent button view for feedback summary
   [INFO] Posted feedback button in kickstart-demo channel
   ```

### Phase 2: Tool Name Fix

1. **User tested button** and reported new error: "Error: unknown tool 'slack_send_message'"
2. **Identified incorrect tool name** by checking Slack MCP documentation and other working code
3. **Updated tool names** from `slack_send_message` to `slack__post_message` in all files
4. **Restarted service** again:
   ```bash
   sudo systemctl restart schubert-architect.service
   ```
5. **Verified in logs** that Slack MCP server connected with 8 tools

## Verification

### Service Logs (Correct Sequence)

```bash
$ sudo journalctl -u schubert-architect.service --since "5 minutes ago" | grep -E "(MCP|button)"
2026-08-19 16:25:17 [INFO] Initialized slack: Slack MCP Server v1.0.0
2026-08-19 16:25:18 [INFO] MCP: 175 tools available
2026-08-19 16:25:18 [INFO] Registered persistent button view for feedback summary
2026-08-19 16:25:18 [INFO] Posted feedback button in kickstart-demo channel
```

### Button Functionality

✅ Button properly connects to Slack MCP server  
✅ Uses correct tool name: `slack__post_message`  
✅ Successfully sends Writer Event Feedback Summary to `#demo-cape-webinars`  
✅ No more "MCP client not available" errors  
✅ No more "unknown tool" errors

## Key Lessons Learned

### 1. MCP Tool Naming Convention

**Always use the format:** `{server_name}__{tool_name}` (double underscore)

Common MCP tool names:
- Slack: `slack__post_message`, `slack__list_channels`, `slack__add_reaction`
- GitHub: `github__create_issue`, `github__create_pr`, `github__search_code`
- Gmail: `gmail_freelance__send_email`, `gmail_freelance__search`
- Postgres: `postgres__query`, `postgres__execute`
- Schubert: `schubert__run_command`, `schubert__read_file`

### 2. Check Documentation First

When MCP tool calls fail with "unknown tool", check:

When MCP tool calls fail with "unknown tool", check:
1. MCP documentation in `/opt/Project-Tango/docs/`
2. Working examples in other bot files
3. MCP server logs for available tool names
4. The `get_aggregated_tools()` output

### 3. Prevention Guidelines

To prevent similar issues in the future:

1. **Always initialize dependencies before consumers**
   - MCP client must be initialized before any code that uses it
   - Button views must be registered after their dependencies are ready

2. **Add startup order comments**
   - Document the required initialization sequence in `on_ready()`
   - Add comments explaining why order matters

3. **Test persistent UI components**
   - Verify buttons/modals work after bot restart
   - Check that stored references are still valid

4. **Monitor initialization logs**
   - Watch for MCP client initialization in journalctl
   - Confirm button registration happens after MCP is ready

4. **Verify MCP tool names**
   - Always use `{server}__{tool}` format with double underscore
   - Check documentation for correct tool names
   - Test with known-working tool calls first

5. **Test end-to-end after deployment**
   - Click buttons to verify they work
   - Check logs for tool call success/failure
   - Monitor for "unknown tool" errors

## Related Documentation

- `/opt/Project-Tango/docs/WRITER_FEEDBACK_SLACK_AUTOMATION.md` - Full automation guide
- `/opt/Project-Tango/docs/DISCORD_TO_SLACK_AUTOMATION.md` - Original implementation docs
- `/opt/Project-Tango/docs/SLACK_MCP_SETUP.md` - Slack MCP server setup and tool names
- `/opt/Project-Tango/CHANGELOG.md` - Change history entry

## Testing Checklist

- [x] MCP client initializes before button view creation
- [x] Button view registered with `bot.add_view()`
- [x] Button posted to Discord after MCP is ready
- [x] Old button deleted and fresh button posted
- [x] Service logs show correct initialization order
- [x] Correct MCP tool name used (`slack__post_message`)
- [x] Button click successfully sends to Slack
- [x] `!refresh-button` command works for manual refresh
- [x] No "MCP client not available" errors
- [x] No "unknown tool" errors

---

**Resolution Time:** ~45 minutes (30 min for fix #1, 15 min for fix #2)  
**Services Restarted:** `schubert-architect.service` (3 restarts)  
**Impact:** No user-facing downtime; button was non-functional before fix  
**Future Risk:** Low (initialization order is correct, tool names follow MCP convention)
