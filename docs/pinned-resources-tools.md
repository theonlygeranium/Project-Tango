# Pinned Resource Management Tools

**Location:** `/opt/Project-Tango/scripts/pinned_resources_tools.py`

Agent tools for creating, managing, and listing pinned resource messages in Discord channels. Enables LLMs to pin reference material, documentation links, status dashboards, and other persistent content with rich embeds.

---

## Overview

The pinned resources system provides three tools for agent-controlled pinning:

| Tool | Purpose | Permissions Required |
|---|---|---|
| `pin_resource` | Create and pin a rich embed | Send Messages, Manage Messages |
| `unpin_resource` | Unpin and delete a message | Manage Messages |
| `list_pinned` | List all pinned messages | Read Message History |

All tools return JSON-serializable results for reliable parsing by the LLM.

---

## Architecture

### Module Structure

```
pinned_resources_tools.py
├── execute_pinned_resource_tool()  — Main entry point for tool execution
├── get_pinned_resource_tools()     — OpenAI tool definitions
└── Internal handlers:
    ├── _handle_pin_resource()      — Create and pin embed
    ├── _handle_unpin_resource()    — Unpin and delete
    └── _handle_list_pinned()       — List all pins
```

### Dependencies

- `discord.py` — Discord API client
- `discord_ux_utils.py` — Embed validation and silent messaging
  - `validate_embed_limits()` — Enforce Discord embed constraints
  - `send_silent()` — Send without push notifications

### Integration Points

The module exports two functions for integration:

```python
from pinned_resources_tools import (
    execute_pinned_resource_tool,  # Execute tool by name
    get_pinned_resource_tools,     # Get OpenAI tool definitions
)
```

---

## Tool Reference

### 1. `pin_resource`

Create and pin a rich embed resource message.

**Parameters:**

| Parameter | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `title` | string | ✅ | max 256 chars | Embed title |
| `description` | string | ✅ | max 4096 chars | Embed body text |
| `fields` | array | ❌ | max 25 fields | Array of field objects |
| `color` | string | ❌ | hex code | Sidebar color (default: `0x9B59B6`) |

**Field Object Schema:**

```json
{
  "name": "Field Name",
  "value": "Field value (supports Discord markdown)",
  "inline": false
}
```

**Constraints:**
- Field name: max 256 characters
- Field value: max 1024 characters
- Total embed text: max 6000 characters (title + description + all fields)

**Returns:**

```json
{
  "success": true,
  "message_id": "1234567890123456789",
  "url": "https://discord.com/channels/..."
}
```

**Error Response:**

```json
{
  "success": false,
  "error": "Description exceeds 4096 characters (got 5000)"
}
```

**Example Usage (LLM):**

> "Pin a resource titled 'API Documentation' with the description 'FastAPI docs: https://fastapi.tiangolo.com' and a field named 'Version' with value '0.104.1'"

The LLM will call:

```json
{
  "name": "pin_resource",
  "arguments": {
    "title": "API Documentation",
    "description": "FastAPI docs: https://fastapi.tiangolo.com",
    "fields": [
      {"name": "Version", "value": "0.104.1", "inline": true}
    ],
    "color": "0x3498DB"
  }
}
```

---

### 2. `unpin_resource`

Unpin and delete a resource message.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `message_id` | string | ✅ | Discord message ID |

**Returns:**

```json
{
  "success": true
}
```

**Error Response:**

```json
{
  "success": false,
  "error": "Message not found: 1234567890123456789"
}
```

**Example Usage (LLM):**

> "Remove the pinned resource with ID 1234567890123456789"

The LLM will call:

```json
{
  "name": "unpin_resource",
  "arguments": {
    "message_id": "1234567890123456789"
  }
}
```

---

### 3. `list_pinned`

List all pinned messages in the channel.

**Parameters:** None

**Returns:**

```json
{
  "success": true,
  "pinned": [
    {
      "id": "1234567890123456789",
      "title": "API Documentation",
      "url": "https://discord.com/channels/..."
    },
    {
      "id": "9876543210987654321",
      "title": "Deployment Process",
      "url": "https://discord.com/channels/..."
    }
  ]
}
```

**Title Extraction Logic:**

1. If message has embeds, use `embed.title`
2. If no title, use first 50 chars of `embed.description`
3. If no embeds, use first 50 chars of `message.content`
4. If still no title, use `"(No title)"`

**Example Usage (LLM):**

> "List all pinned resources"

The LLM will call:

```json
{
  "name": "list_pinned",
  "arguments": {}
}
```

---

## Integration Guide

### Step 1: Import the Module

Add to the top of your bot script:

```python
from pinned_resources_tools import (
    execute_pinned_resource_tool,
    get_pinned_resource_tools,
)
```

### Step 2: Add Tools to Tool Definitions

In your `get_all_tools()` function:

```python
def get_all_tools() -> list[dict]:
    tools = []
    tools.extend(get_dev_tools())
    tools.extend(get_pinned_resource_tools())  # Add this line
    # ... add other tools ...
    return tools
```

### Step 3: Add Tool Execution Handler

In your `execute_tool()` function:

```python
async def execute_tool(tool_name: str, args: dict, channel) -> str:
    # Check if it's a pinned resource tool
    if tool_name in ["pin_resource", "unpin_resource", "list_pinned"]:
        return await execute_pinned_resource_tool(tool_name, args, channel)
    
    # ... handle other tools ...
```

### Step 4: (Optional) Add Progress Descriptions

In `tool_descriptions.py`:

```python
if tool_name == "pin_resource":
    title = tool_args.get("title", "?")[:50]
    return f"📌 Pinning resource: {title}"

if tool_name == "unpin_resource":
    msg_id = tool_args.get("message_id", "?")
    return f"📌 Unpinning resource: {msg_id}"

if tool_name == "list_pinned":
    return "📌 Listing pinned resources"
```

### Complete Integration Example

See `/opt/Project-Tango/scripts/pinned_resources_integration_example.py` for a full working example.

---

## Implementation Details

### Validation

All embeds are validated before sending using `validate_embed_limits()` from `discord_ux_utils`:

```python
is_valid, error_msg = validate_embed_limits(title, description, fields)
if not is_valid:
    return {"success": False, "error": error_msg}
```

**Limits enforced:**
- Title: 256 characters
- Description: 4096 characters
- Fields: max 25
- Field name: 256 characters
- Field value: 1024 characters
- Total text: 6000 characters

### Silent Messaging

All pinned resources are sent with `silent=True` using `send_silent()` from `discord_ux_utils`:

```python
message = await send_silent(channel, embed=embed)
```

This prevents push notifications on mobile devices, making it suitable for background updates.

### Error Handling

All Discord API errors are caught and returned as JSON:

| Error Type | Example Message |
|---|---|
| `discord.Forbidden` | `"Permission denied: cannot pin messages in this channel"` |
| `discord.NotFound` | `"Message not found: 1234567890123456789"` |
| `discord.HTTPException` | `"Discord API error: <exception details>"` |
| `ValueError` | `"Invalid color format: 'purple'. Use hex like '0x9B59B6'"` |

All errors include the error type and details for debugging.

### Color Parsing

The `color` parameter accepts multiple formats:

```python
"0x9B59B6"  # With 0x prefix (preferred)
"9B59B6"    # Without prefix (also works)
""          # Empty string = default purple (0x9B59B6)
```

Invalid formats return a JSON error:

```json
{
  "success": false,
  "error": "Invalid color format: 'purple'. Use hex like '0x9B59B6'"
}
```

### Embed Footer

All pinned resources include a timestamped footer:

```python
embed.set_footer(text="📌 Pinned resource • Managed by agent")
embed.timestamp = datetime.now(timezone.utc)
```

This helps users identify agent-managed pins.

---

## Testing

### Unit Test (Manual)

Run the test function in a test channel:

```python
from pinned_resources_tools import execute_pinned_resource_tool
import asyncio

async def test(channel):
    # Pin a test resource
    result = await execute_pinned_resource_tool(
        "pin_resource",
        {
            "title": "Test Resource",
            "description": "This is a test.",
            "fields": [{"name": "Status", "value": "✅ Active"}],
            "color": "0x2ECC71",
        },
        channel,
    )
    print(result)
    
    # List pinned
    result = await execute_pinned_resource_tool("list_pinned", {}, channel)
    print(result)
```

### Integration Test

See `pinned_resources_integration_example.py` for a complete test suite:

```bash
cd /opt/Project-Tango/scripts
python3 pinned_resources_integration_example.py
```

### Test Checklist

- ✅ Pin a resource with title, description, and fields
- ✅ Pin a resource with custom color
- ✅ List pinned resources and verify title extraction
- ✅ Unpin a resource by ID
- ✅ Validate oversized title (should fail)
- ✅ Validate oversized description (should fail)
- ✅ Validate too many fields (should fail)
- ✅ Validate invalid color format (should fail)
- ✅ Test permission errors (no Manage Messages)
- ✅ Test invalid message ID (should fail)

---

## Security Considerations

### Permissions

The bot requires these permissions to use pinned resource tools:

| Permission | Required For | Impact if Missing |
|---|---|---|
| Send Messages | `pin_resource` | Cannot create pins |
| Manage Messages | `pin_resource`, `unpin_resource` | Cannot pin/unpin |
| Read Message History | `list_pinned`, `unpin_resource` | Cannot fetch messages |

All permission errors are caught and returned as JSON:

```json
{
  "success": false,
  "error": "Permission denied: cannot pin messages in this channel"
}
```

### Input Validation

- All embed constraints enforced via `validate_embed_limits()`
- Message IDs validated as integers before use
- Color codes validated as valid hex integers
- No raw user input passed to Discord API without validation

### Rate Limiting

Discord enforces rate limits on pinning:

- **50 pins per channel** (hard limit)
- **Rate limit:** ~10 pins per 10 seconds

The module does **not** implement rate limit handling. Bots should:

1. Monitor pin count via `list_pinned`
2. Warn users when approaching 50 pins
3. Implement retry logic for rate limit errors if needed

### Silent Messaging

All pins use `silent=True` to prevent notification spam. This is enforced at the module level — bots cannot override this without modifying the module.

---

## Troubleshooting

### "Permission denied: cannot pin messages"

**Cause:** Bot lacks `Manage Messages` permission.

**Fix:** Grant the bot the `Manage Messages` permission in the channel or category.

### "Embed validation failed: Title exceeds 256 characters"

**Cause:** Title too long.

**Fix:** The LLM should truncate the title to 256 characters. If this happens frequently, add a system message reminder about embed limits.

### "Message not found: 1234567890123456789"

**Cause:** Message ID is invalid or the message was already deleted.

**Fix:** Use `list_pinned` to get valid message IDs before unpinning.

### Pins not showing in channel

**Cause:** Discord's pin UI can be hidden if there are too many pins.

**Fix:** Discord shows a "📌 Pinned Messages" button in the channel header. If there are 50 pins, older pins may be buried.

---

## Future Enhancements

Potential improvements for future versions:

1. **Pin rotation** — Auto-unpin oldest pin when approaching 50-pin limit
2. **Pin categories** — Tag pins with categories for filtering
3. **Pin expiration** — Auto-unpin after a configured duration
4. **Rich formatting** — Support for images, thumbnails, and author fields
5. **Pin search** — Search pinned messages by keyword
6. **Pin analytics** — Track pin creation, updates, and deletions

---

## See Also

- **Discord Embed Limits:** https://discord.com/developers/docs/resources/channel#embed-limits
- **`discord_ux_utils.py`:** `/opt/Project-Tango/scripts/discord_ux_utils.py`
- **Integration Example:** `/opt/Project-Tango/scripts/pinned_resources_integration_example.py`
- **OpenAI Function Calling:** https://platform.openai.com/docs/guides/function-calling

---

**Author:** Cursor Agent  
**Date:** 2026-08-19  
**Project:** Project Tango — Discord Agent Framework
