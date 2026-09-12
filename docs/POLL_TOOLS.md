# Discord Poll Creation Tool

## Overview

Native Discord poll creation tool for agent decision-making and feedback gathering. Integrates with the Schubert Bot V2 agent loop to enable LLM-driven poll creation using Discord's native poll API (introduced 2024).

## Features

- **Native Discord Polls**: Creates polls with native Discord voting UI and real-time vote counts
- **Full Validation**: Enforces Discord API limits on question length, answer count, and duration
- **Agent Integration**: Fully integrated with the Schubert Bot V2 tool system
- **Memory Storage**: Poll creations are stored in the memory system for context
- **Voice Mode Support**: Works in both text and voice channels

## Implementation

### Files

- **`scripts/poll_tools.py`** - Core implementation with validation, API calls, and tool definitions
- **`scripts/schubert-bot-v2.py`** - Integration into agent loop (imports and handlers)
- **`scripts/tool_descriptions.py`** - Progress display descriptions for poll creation
- **`docs/POLL_TOOLS.md`** - This documentation (YOU ARE HERE)

### Tool Definition

**Tool Name:** `create_poll`

**Parameters:**
- `question` (required, string, max 300 chars) - The poll question
- `answers` (required, array of strings, 2-10 items, max 55 chars each) - Answer options
- `duration_hours` (optional, integer, 1-768, default 24) - Hours until poll closes
- `allow_multiselect` (optional, boolean, default false) - Whether users can select multiple answers

**Returns:** JSON with `success` (bool), `message_id` (string if successful), `error` (string if failed)

### Discord API Constraints

The implementation enforces Discord's native poll API limits:

| Constraint | Value | Validated |
|------------|-------|-----------|
| Max question length | 300 characters | ✅ |
| Max answer length | 55 characters | ✅ |
| Max answers | 10 | ✅ |
| Min answers | 2 | ✅ |
| Min duration | 1 hour | ✅ |
| Max duration | 768 hours (32 days) | ✅ |

## Usage

### From Agent (Natural Language)

The LLM can call the `create_poll` tool when appropriate:

```
User: "Can you create a poll asking which feature we should prioritize?"

Agent: [Calls create_poll tool]
{
  "question": "Which feature should we prioritize next?",
  "answers": ["Dark mode", "API v2", "Mobile app", "Performance"],
  "duration_hours": 48
}
```

### Use Cases

1. **Senior Staff Meeting Decisions**
   - "Which architecture approach should we use?"
   - "Should we proceed with the database migration?"

2. **Feature Feedback**
   - "Rate the new authentication flow: 1-5"
   - "Which features would you like to see? (multi-select)"

3. **Priority Planning**
   - "Which bug should we fix first?"
   - "What should the team work on this sprint?"

4. **Agent-Initiated Polls**
   - When the agent needs human input to proceed
   - When multiple valid options exist and human preference is needed

## API Implementation

### Discord REST API v10

**Endpoint:** `POST /channels/{channel_id}/messages`

**Payload Structure:**
```json
{
  "poll": {
    "question": {"text": "string (max 300 chars)"},
    "answers": [
      {"poll_media": {"text": "string (max 55 chars)"}}
    ],
    "duration": 24,
    "allow_multiselect": false
  }
}
```

### Implementation Strategy

The tool uses a dual-strategy approach:

1. **Primary:** Attempts to use discord.py's internal HTTP client (`channel._state.http`)
2. **Fallback:** Uses raw `aiohttp` with bot token if discord.py doesn't support the payload format

This ensures compatibility even if discord.py doesn't have native poll support in the installed version.

## Integration Points

### 1. Tool Registration

```python
# In schubert-bot-v2.py
from poll_tools import (
    get_poll_tools, handle_poll_tool, is_poll_tool,
    POLL_PROMPT_ADDITION,
)

# Add to system prompt
SYSTEM_PROMPT += POLL_PROMPT_ADDITION

# Add to tool list
def get_legacy_tools() -> list[dict]:
    return LEGACY_TOOLS + get_coding_tools() + get_poll_tools() + [...]
```

### 2. Tool Execution

```python
# In execute_tool_v2()
elif is_poll_tool(tool_name):
    log(f"Poll tool {tool_name}: {args_str(tool_args)}", "INFO")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    result = await handle_poll_tool(tool_name, tool_args, message.channel, bot_token)
    # ... memory storage ...
    return result
```

### 3. Progress Display

```python
# In tool_descriptions.py
if tool_name == "create_poll":
    question = tool_args.get("question", "?")
    num_answers = len(tool_args.get("answers", []))
    duration = tool_args.get("duration_hours", 24)
    return f"📊 Creating poll: '{question[:50]}' ({num_answers} options, {duration}h)"
```

## Error Handling

The tool provides clear error messages for validation failures:

- `"Validation failed: Question exceeds 300 characters (got 350)"`
- `"Validation failed: Poll cannot have more than 10 answers (got 12)"`
- `"Validation failed: Answer 3 exceeds 55 characters (got 60)"`
- `"HTTP 403: Missing permissions to create polls in this channel"`

## Testing

### Manual Testing

Test the tool by asking the agent to create a poll:

```
User: "Create a poll asking what the team wants for lunch with options: Pizza, Sushi, Burgers, Tacos. Keep it open for 4 hours."

Agent: [Creates poll and shows native Discord voting UI]
```

### Validation Testing

The validation tests can be run with:

```bash
cd /opt/Project-Tango/scripts
python3 -c "from poll_tools import validate_poll_parameters; print(validate_poll_parameters('Test?', ['A', 'B'], 24))"
```

Expected output: `None` (meaning validation passed)

### Integration Testing

Test in a live Discord channel:

1. Start the bot: `sudo systemctl start schubert-bot.service`
2. In a bound Discord channel, send: `"Admiral, create a quick poll asking if the team is ready to deploy, with Yes and No options"`
3. Verify the poll appears with native Discord voting buttons
4. Verify votes are tracked in real-time
5. Check logs: `sudo journalctl -u schubert-bot.service -n 50 | grep "Poll tool"`

## Configuration

### Required Environment Variables

- `DISCORD_BOT_TOKEN` - Used for fallback raw API calls if discord.py doesn't support poll format

### Bot Permissions

The Discord bot requires the following permissions to create polls:
- `Send Messages` - To post the poll message
- `Embed Links` - For proper poll rendering (may be required)

## Limitations

1. **No Poll Editing**: Once created, polls cannot be edited via API
2. **No Vote Retrieval**: The API doesn't provide vote data retrieval (Discord limitation)
3. **No Anonymous Polls**: All polls show who voted for what (Discord limitation)
4. **No Emoji/Image Answers**: Only text answers supported (Discord limitation)

## Future Enhancements

Potential future additions:

- [ ] Poll result retrieval (if Discord adds API support)
- [ ] Poll end notification webhook handling
- [ ] Poll analytics (vote counts, participation rates)
- [ ] Scheduled poll creation (via scheduler)
- [ ] Poll templates for common use cases
- [ ] Integration with Writer Playbook for automated polls

## References

- [Discord API Documentation - Polls](https://discord.com/developers/docs/resources/poll)
- [Discord API v10 Reference](https://discord.com/developers/docs/reference)
- `scripts/poll_tools.py` - Implementation source code
- `scripts/schubert-bot-v2.py` - Integration code

## Changelog

### 2026-08-19 - Initial Implementation
- ✅ Native Discord poll creation via REST API
- ✅ Full parameter validation
- ✅ Integration with Schubert Bot V2 agent loop
- ✅ Memory storage for poll creation events
- ✅ Voice mode support
- ✅ Progress display in tool descriptions
- ✅ Dual-strategy API calling (discord.py + fallback)
- ✅ Comprehensive error handling
- ✅ Documentation and usage examples

---

**Status:** ✅ Ready for Production
**Version:** 1.0
**Last Updated:** 2026-08-19
