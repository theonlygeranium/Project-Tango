# Discord Bot Integration Guide - Slack MCP Notifications

**Purpose:** Enable Slack notifications in Discord bots using MCP  
**Audience:** Future bot developers / maintainers  
**Date:** 2026-08-19

---

## Quick Reference

### For Existing Bots (Already Updated)

✅ **The Architect** - Updated (line 1627)  
✅ **Dr. Voss** - Updated (line 2341)  
✅ **The Proctor** - Updated (line 4028)

### For New Bots

**One-line change:**
```python
# OLD (webhooks - deprecated)
slack_notifier = get_slack_notifier()

# NEW (MCP)
slack_notifier = get_slack_notifier(mcp_client)
```

---

## Complete Integration Steps

### Step 1: Import SlackNotifier

Add to bot's imports (top of file):

```python
from slack_notifier import get_slack_notifier
```

**Location in existing bots:**
- The Architect: Line 60
- Dr. Voss: Line 60
- The Proctor: Line 70

### Step 2: Initialize SlackNotifier

Where you need to send notifications (usually in message handler or scheduled task):

```python
# Get MCP-enabled notifier
slack_notifier = get_slack_notifier(mcp_client)
```

**Important:** Ensure `mcp_client` is in scope (it should be a global or passed parameter)

**Location in existing bots:**
- The Architect: Line 1627 (in tool execution handler)
- Dr. Voss: Line 2341 (in escalation handler)
- The Proctor: Line 4028 (in report generation)

### Step 3: Send Notifications

Use the appropriate method for your notification type:

#### Deployment Alerts

```python
await slack_notifier.send_deployment_alert(
    title="Deployed v2.1.3",
    message="Successfully deployed to production",
    bot_name="The Architect",
    status="success",  # info, success, warning, error
    metadata={
        "version": "v2.1.3",
        "commit": "abc1234",
        "files_changed": "5"
    }
)
```

**Goes to:** `#tango-ops` (or `SLACK_CHANNEL_TANGO_OPS` if configured)

#### Health Alerts

```python
await slack_notifier.send_health_alert(
    title="Service Failure Detected",
    message="schubert-bot.service is inactive",
    bot_name="Dr. Voss",
    is_critical=True,  # False for warnings
    metadata={
        "service": "schubert-bot.service",
        "status": "inactive",
        "auto_remediation": "attempted"
    }
)
```

**Goes to:** `#tango-ops`

#### Performance Reports

```python
await slack_notifier.send_performance_report(
    title="Daily Performance Report",
    message="All bots operational. 342 operations completed.",
    bot_name="The Proctor",
    metadata={
        "uptime": "99.8%",
        "avg_response_time": "1.2s",
        "operations": "342"
    }
)
```

**Goes to:** `#tango-reports` (or `SLACK_CHANNEL_TANGO_REPORTS` if configured)

#### Generic System Events

```python
from slack_notifier import SlackChannel

await slack_notifier.send_system_event(
    title="System Event",
    message="Custom event notification",
    bot_name="Your Bot Name",
    channel=SlackChannel.TANGO_DEV,  # TANGO_OPS, TANGO_REPORTS, TANGO_DEV
    severity="info",  # info, warning, error, critical
    metadata={"key": "value"}
)
```

---

## Best Practices

### 1. Fire-and-Forget Pattern

Notifications should not block bot operations:

```python
# ✅ GOOD - Fire and forget with asyncio.create_task
asyncio.create_task(slack_notifier.send_deployment_alert(...))

# ❌ BAD - Blocks bot execution
await slack_notifier.send_deployment_alert(...)
```

**Why:** If Slack MCP is slow or failing, the bot should continue operating normally.

### 2. Error Handling

The notifier returns `bool` indicating success/failure:

```python
# If you need to track success
success = await slack_notifier.send_deployment_alert(...)
if not success:
    logging.warning("Slack notification failed (non-critical)")
    # Bot continues normally
```

**Don't:** Make bot operations dependent on Slack notification success.

### 3. Metadata Usage

Add contextual information for better diagnostics:

```python
# ✅ GOOD - Rich metadata
metadata={
    "version": version,
    "user": user_id,
    "timestamp": timestamp,
    "file_path": path
}

# ❌ BAD - Empty or minimal
metadata={}
```

### 4. Title and Message Guidelines

**Title:** Short, descriptive (< 100 chars)
```python
# ✅ GOOD
"Deployed architect-bot.py v2.1.3"

# ❌ BAD
"The Architect has successfully completed the deployment operation for the file located at..."
```

**Message:** Details, context, action items
```python
# ✅ GOOD
"""Successfully deployed architect-bot.py to production.

**Changes:**
- Added Slack MCP support
- Updated tool count to 175

**Next Steps:**
- Monitor logs for 24 hours
- Test Slack notifications
"""
```

---

## Channel Configuration

### Default Channels

The notifier uses these defaults if env vars not set:

| Method | Default Channel |
|---|---|
| `send_deployment_alert()` | `#tango-ops` |
| `send_health_alert()` | `#tango-ops` |
| `send_performance_report()` | `#tango-reports` |
| `send_system_event()` | Specified in call |

### Optional: Configure Channel IDs

For better performance, add actual Slack channel IDs to `.env`:

```bash
# Optional - speeds up MCP calls (no channel lookup)
SLACK_CHANNEL_TANGO_OPS=C01234567
SLACK_CHANNEL_TANGO_REPORTS=C98765432
SLACK_CHANNEL_TANGO_DEV=C55555555
```

**How to get channel IDs:**

**Method 1: From The Architect**
```
@The Architect list Slack channels with IDs
```

**Method 2: From Slack**
Right-click channel → View channel details → Copy channel ID

---

## Testing

### Manual Testing

**1. Test from Discord:**
```
@Your Bot trigger action that sends notification
```

**2. Verify in Slack:**
- Check appropriate channel (#tango-ops, #tango-reports, etc.)
- Verify message formatting
- Check metadata appears correctly

**3. Check logs:**
```bash
sudo journalctl -u your-bot-service -n 50 --no-pager | grep -i slack
```

### Automated Testing

**Test notifier initialization:**
```python
# In bot startup
slack_notifier = get_slack_notifier(mcp_client)
if slack_notifier.enabled:
    logging.info("Slack notifications enabled")
else:
    logging.warning("Slack notifications disabled (no MCP client)")
```

---

## Troubleshooting

### Issue: "Slack notifications disabled"

**Cause:** MCP client not passed or `None`

**Fix:**
```python
# ❌ Wrong
slack_notifier = get_slack_notifier()

# ✅ Right
slack_notifier = get_slack_notifier(mcp_client)
```

### Issue: Notifications not appearing in Slack

**Check 1: MCP client has Slack server**
```bash
sudo journalctl -u your-bot-service | grep "Connected to slack"
# Should see: "Connected to slack: 8 tools discovered"
```

**Check 2: Slack MCP server running**
```bash
sudo systemctl status slack-mcp.service
# Should be: active (running)
```

**Check 3: Bot has channel access**
```
# Ask The Architect in Discord:
@The Architect am I a member of #tango-ops in Slack?
```

If not a member, bot needs to be invited to channels.

### Issue: "MCP call timed out"

**Cause:** Slack MCP server overloaded or slow

**Fix:** Notifications are fire-and-forget, so this is non-critical. Check:
```bash
sudo journalctl -u slack-mcp -n 50 --no-pager
```

### Issue: Wrong channel receiving notifications

**Check channel configuration:**
```bash
grep SLACK_CHANNEL /opt/Project-Tango/.env
```

**Verify fallback working:**
```python
# Code uses fallback if channel ID not set
channel = CHANNEL_IDS.get("tango-ops") or "#tango-ops"
```

---

## Advanced: Custom Notification Types

### Creating Custom Notification Type

**1. Add to NotificationType enum:**
```python
class NotificationType(Enum):
    # ... existing types ...
    CUSTOM_TYPE = "custom_type"
```

**2. Add emoji mapping:**
```python
emoji_map = {
    # ... existing mappings ...
    NotificationType.CUSTOM_TYPE: "🎯",
}
```

**3. Create convenience method:**
```python
async def send_custom_alert(
    self,
    title: str,
    message: str,
    bot_name: str,
    metadata: Optional[dict] = None
) -> bool:
    if not self.enabled:
        return False
    
    formatted = _format_slack_message(
        NotificationType.CUSTOM_TYPE,
        title,
        message,
        bot_name,
        "info",
        metadata
    )
    
    channel = CHANNEL_IDS.get("tango-ops") or "#tango-ops"
    return await self._send_via_mcp(channel, formatted)
```

---

## Integration Checklist

For new bot integration:

- [ ] Import `get_slack_notifier` from `slack_notifier`
- [ ] Initialize with `mcp_client` parameter
- [ ] Use appropriate notification method
- [ ] Use fire-and-forget pattern (`asyncio.create_task`)
- [ ] Add rich metadata for context
- [ ] Test in Discord → verify in Slack
- [ ] Check logs for errors
- [ ] Document what notifications your bot sends

---

## Examples from Existing Bots

### The Architect (Deployment Notifications)

**Location:** Line 1627-1641

```python
slack_notifier = get_slack_notifier(mcp_client)
try:
    if tool_name == "deploy_file":
        file_path = tool_args.get("path", "")
        file_size = len(tool_args.get("content", ""))
        asyncio.create_task(slack_notifier.send_deployment_alert(
            title=f"File Deployed: {os.path.basename(file_path)}",
            message=f"The Architect successfully deployed a file:\n\n**Path:** `{file_path}`\n**Size:** {file_size:,} bytes\n**Requested by:** <@{user_id}>",
            bot_name="The Architect",
            status="success",
            metadata={
                "file": os.path.basename(file_path),
                "size_bytes": str(file_size),
                "user_id": str(user_id)
            }
        ))
except Exception as e:
    logging.error(f"Slack notification error: {e}")
```

### Dr. Voss (Health Alerts)

**Location:** Line 2341-2351

```python
slack_notifier = get_slack_notifier(mcp_client)
try:
    asyncio.create_task(slack_notifier.send_health_alert(
        title=title,
        message=f"{message}\n\n**Issue ID:** `{issue_id}`\n**Auto-remediation:** Exhausted",
        bot_name="Dr. Voss",
        is_critical=(severity == "CRITICAL"),
        metadata={
            "issue_id": issue_id,
            "severity": severity,
            "escalation_attempt": str(escalation_attempt)
        }
    ))
except Exception as e:
    logging.error(f"Slack notification error: {e}")
```

### The Proctor (Performance Reports)

**Location:** Line 4028-4042

```python
slack_notifier = get_slack_notifier(mcp_client)
try:
    summary = report[:500] + "..." if len(report) > 500 else report
    asyncio.create_task(slack_notifier.send_performance_report(
        title="📊 Daily Performance Report",
        message=f"{summary}\n\n*Full report posted to Discord #proctor-analysis*",
        bot_name="The Proctor",
        metadata={
            "report_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "tests_run": str(test_count),
            "success_rate": f"{success_rate}%"
        }
    ))
except Exception as e:
    logging.error(f"Slack notification error: {e}")
```

---

## Reference

**Module:** `/opt/Project-Tango/scripts/slack_notifier.py`  
**Documentation:** `/opt/Project-Tango/docs/MCP_SLACK_IMPLEMENTATION_COMPLETE.md`  
**ADR:** `/opt/Project-Tango/docs/decisions/2026-08-19-013-mcp-only-no-webhooks.md`

**Questions?** Check The Architect in Discord or review the implementation docs.
