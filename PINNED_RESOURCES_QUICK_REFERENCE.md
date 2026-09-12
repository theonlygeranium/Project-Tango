# Pinned Resources Quick Reference Card

**Location:** `/opt/Project-Tango/scripts/pinned_resources_tools.py`  
**Status:** ✅ Ready for Integration

---

## 5-Minute Integration Guide

### Step 1: Import (Add to top of bot file)

```python
from pinned_resources_tools import (
    execute_pinned_resource_tool,
    get_pinned_resource_tools,
)
```

### Step 2: Add Tool Definitions

```python
def get_dev_tools() -> list[dict]:
    tools = [
        # ... existing tools ...
    ]
    tools.extend(get_pinned_resource_tools())  # Add this line
    return tools
```

### Step 3: Add Tool Execution

```python
async def execute_dev_tool(tool_name: str, args: dict, channel=None) -> str:
    # ... existing tool handlers ...
    
    # Add pinned resource tools
    if tool_name in ["pin_resource", "unpin_resource", "list_pinned"]:
        return await execute_pinned_resource_tool(tool_name, args, channel)
    
    return f"Unknown tool: {tool_name}"
```

### Step 4: Update Call Sites

```python
# BEFORE:
result = await execute_dev_tool(tool_name, tool_args)

# AFTER:
result = await execute_dev_tool(tool_name, tool_args, channel=message.channel)
```

### Step 5: Restart Bot

```bash
sudo systemctl restart your-bot.service
```

---

## Tool Quick Reference

### `pin_resource`

**Purpose:** Create and pin a rich embed message

**Required:**
- `title` (string, max 256 chars)
- `description` (string, max 4096 chars)

**Optional:**
- `fields` (array of `{name, value, inline}`, max 25)
- `color` (hex code like "0x9B59B6")

**Returns:**
```json
{"success": true, "message_id": "...", "url": "..."}
```

**Example Command:**
> "Pin a resource titled 'API Docs' with description 'FastAPI documentation at https://fastapi.tiangolo.com'"

---

### `unpin_resource`

**Purpose:** Unpin and delete a message

**Required:**
- `message_id` (string, Discord message ID)

**Returns:**
```json
{"success": true}
```

**Example Command:**
> "Unpin the resource with ID 1234567890"

---

### `list_pinned`

**Purpose:** List all pinned messages

**Required:** None

**Returns:**
```json
{
  "success": true,
  "pinned": [
    {"id": "...", "title": "...", "url": "..."}
  ]
}
```

**Example Command:**
> "List all pinned resources"

---

## Validation Limits (Enforced Automatically)

| Field | Limit | Error if Exceeded |
|---|---|---|
| Title | 256 chars | "Title exceeds 256 characters" |
| Description | 4096 chars | "Description exceeds 4096 characters" |
| Fields | 25 fields | "Exceeds 25 fields limit" |
| Field name | 256 chars | "Field N name exceeds 256 characters" |
| Field value | 1024 chars | "Field N value exceeds 1024 characters" |
| Total text | 6000 chars | "Total embed text exceeds 6000 characters" |

---

## Common Errors & Solutions

| Error | Cause | Solution |
|---|---|---|
| "Permission denied: cannot pin messages" | Bot lacks Manage Messages permission | Grant permission in channel settings |
| "Message not found" | Invalid message ID | Use `list_pinned` to get valid IDs |
| "Invalid color format" | Color not in hex format | Use format like "0x9B59B6" |
| "Channel is required" | Channel not passed to execute function | Add `channel=message.channel` parameter |

---

## Testing Commands (Natural Language)

```
# Test pin
"Pin a test resource with title 'Test' and description 'This is a test'"

# Test list
"What's currently pinned?"

# Test unpin (replace ID)
"Remove the pinned resource with ID 1234567890"
```

---

## Required Discord Permissions

- ✅ Send Messages (create pins)
- ✅ Manage Messages (pin/unpin)
- ✅ Read Message History (list/fetch pins)

---

## Files You Need

| File | Purpose |
|---|---|
| `scripts/pinned_resources_tools.py` | Core implementation (required) |
| `scripts/discord_ux_utils.py` | Validation & silent messaging (already exists) |
| `docs/pinned-resources-tools.md` | Full documentation (reference) |
| `scripts/pinned_resources_integration_patch.py` | Detailed integration guide (reference) |

---

## Dependencies

- `discord.py` (already installed)
- `discord_ux_utils.py` (already in project)

**No additional packages needed!**

---

## Progress Display (Optional)

Add to `tool_descriptions.py`:

```python
if tool_name == "pin_resource":
    title = tool_args.get("title", "?")[:50]
    return f"📌 Pinning resource: {title}"

if tool_name == "unpin_resource":
    msg_id = tool_args.get("message_id", "?")
    return f"📌 Unpinning resource: {msg_id[-8:]}"

if tool_name == "list_pinned":
    return "📌 Listing pinned resources"
```

---

## Color Options (Hex Codes)

| Color | Hex Code | Use Case |
|---|---|---|
| Purple | `0x9B59B6` | Default (general resources) |
| Blue | `0x3498DB` | Information |
| Green | `0x2ECC71` | Success / Active |
| Red | `0xE74C3C` | Error / Warning |
| Orange | `0xE67E22` | Alert |
| Yellow | `0xF1C40F` | Attention |

---

## Quick Troubleshooting

**Problem:** Tools not appearing in agent  
**Solution:** Verify `get_pinned_resource_tools()` is added to tool list

**Problem:** "Unknown tool: pin_resource"  
**Solution:** Add tool execution handler to `execute_dev_tool()`

**Problem:** "Channel is required"  
**Solution:** Pass `channel=message.channel` to `execute_dev_tool()`

**Problem:** Bot can't pin  
**Solution:** Check bot has Manage Messages permission

---

## Support & Documentation

- **Full Docs:** `/opt/Project-Tango/docs/pinned-resources-tools.md`
- **Integration Guide:** `/opt/Project-Tango/scripts/pinned_resources_integration_patch.py`
- **Example Code:** `/opt/Project-Tango/scripts/pinned_resources_integration_example.py`
- **Summary:** `/opt/Project-Tango/PINNED_RESOURCES_IMPLEMENTATION.md`
- **Verification:** `/opt/Project-Tango/PINNED_RESOURCES_VERIFICATION.md`

---

**Total Integration Time:** ~5 minutes  
**Code Changes Required:** 3 small additions  
**Additional Dependencies:** 0  
**Ready for Production:** ✅ YES
