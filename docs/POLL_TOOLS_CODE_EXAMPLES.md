# Discord Poll Tool - Code Examples

## Complete Implementation Ready

The native Discord poll creation tool is now fully implemented and integrated into Schubert Bot V2.

---

## Quick Reference

### Tool Call Example (from LLM)

```json
{
  "type": "function",
  "function": {
    "name": "create_poll",
    "arguments": {
      "question": "Which feature should we prioritize next?",
      "answers": ["Dark mode", "API v2", "Mobile app", "Performance"],
      "duration_hours": 48,
      "allow_multiselect": false
    }
  }
}
```

### Result Format

```json
{
  "success": true,
  "message_id": "1234567890123456789"
}
```

Or on error:

```json
{
  "success": false,
  "error": "Validation failed: Question exceeds 300 characters (got 350)"
}
```

---

## Code Snippets

### 1. Core Poll Creation Function

```python
async def create_poll(
    channel: discord.TextChannel,
    question: str,
    answers: list[str],
    duration_hours: int = 24,
    allow_multiselect: bool = False,
    bot_token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create a native Discord poll in the specified channel.
    
    Returns:
        dict with keys:
            - success: bool
            - message_id: str (if successful)
            - error: str (if failed)
    """
    # Validate parameters
    validation_error = validate_poll_parameters(question, answers, duration_hours)
    if validation_error:
        return {"success": False, "error": f"Validation failed: {validation_error}"}
    
    # Build poll payload
    payload = {
        "poll": {
            "question": {"text": question.strip()},
            "answers": [{"poll_media": {"text": answer.strip()}} for answer in answers],
            "duration": duration_hours,
            "allow_multiselect": allow_multiselect,
        }
    }
    
    # Try discord.py HTTP client, fallback to aiohttp
    # ... (see poll_tools.py for full implementation)
```

### 2. Validation Function

```python
def validate_poll_parameters(
    question: str,
    answers: list[str],
    duration_hours: int,
) -> Optional[str]:
    """
    Validate poll parameters according to Discord API constraints.
    
    Returns None if valid, or an error message string if invalid.
    """
    # Question validation
    if not question or not question.strip():
        return "Question cannot be empty"
    if len(question) > MAX_QUESTION_LENGTH:
        return f"Question exceeds {MAX_QUESTION_LENGTH} characters (got {len(question)})"
    
    # Answers validation
    if not answers or len(answers) < 2:
        return "Poll must have at least 2 answer options"
    if len(answers) > MAX_ANSWERS:
        return f"Poll cannot have more than {MAX_ANSWERS} answers (got {len(answers)})"
    
    for i, answer in enumerate(answers, 1):
        if not answer or not answer.strip():
            return f"Answer {i} cannot be empty"
        if len(answer) > MAX_ANSWER_LENGTH:
            return f"Answer {i} exceeds {MAX_ANSWER_LENGTH} characters (got {len(answer)})"
    
    # Duration validation
    if duration_hours < MIN_DURATION:
        return f"Duration must be at least {MIN_DURATION} hour (got {duration_hours})"
    if duration_hours > MAX_DURATION:
        return f"Duration cannot exceed {MAX_DURATION} hours (got {duration_hours})"
    
    return None
```

### 3. Tool Definition (OpenAI Format)

```python
def get_poll_tools() -> list[dict]:
    """Return the poll tool definitions for the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "create_poll",
                "description": (
                    "Create a native Discord poll with voting buttons. "
                    "Use this to gather human feedback, make team decisions, "
                    "or get consensus on design choices. The poll will have "
                    "native Discord voting UI with real-time vote counts. "
                    "Examples: 'Which architecture?', 'Rate this feature 1-5', "
                    "'Which bug should we fix first?'"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The poll question (max 300 characters). Be clear and specific.",
                        },
                        "answers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of answer options (2-10 items, max 55 chars each). "
                                "Keep answers short and distinct."
                            ),
                            "minItems": 2,
                            "maxItems": 10,
                        },
                        "duration_hours": {
                            "type": "integer",
                            "description": (
                                "Hours until poll closes (1-768, default 24). "
                                "Use 1-4 for urgent decisions, 24-48 for normal, "
                                "168 (1 week) for long-term planning."
                            ),
                            "default": 24,
                            "minimum": 1,
                            "maximum": 768,
                        },
                        "allow_multiselect": {
                            "type": "boolean",
                            "description": (
                                "Whether users can select multiple answers (default false). "
                                "Use true for 'select all that apply' questions."
                            ),
                            "default": False,
                        },
                    },
                    "required": ["question", "answers"],
                },
            },
        },
    ]
```

### 4. Tool Handler

```python
async def handle_poll_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    channel: discord.TextChannel,
    bot_token: Optional[str] = None,
) -> str:
    """
    Handle poll tool execution.
    
    Returns:
        JSON string with result (for LLM consumption)
    """
    import json
    
    if tool_name != "create_poll":
        return json.dumps({
            "success": False,
            "error": f"Unknown poll tool: {tool_name}"
        })
    
    # Extract parameters
    question = tool_args.get("question", "")
    answers = tool_args.get("answers", [])
    duration_hours = tool_args.get("duration_hours", 24)
    allow_multiselect = tool_args.get("allow_multiselect", False)
    
    # Create poll
    result = await create_poll(
        channel=channel,
        question=question,
        answers=answers,
        duration_hours=duration_hours,
        allow_multiselect=allow_multiselect,
        bot_token=bot_token,
    )
    
    return json.dumps(result)
```

### 5. Integration in Agent Loop

```python
# In schubert-bot-v2.py

# Import at top
from poll_tools import (
    get_poll_tools, handle_poll_tool, is_poll_tool,
    POLL_PROMPT_ADDITION,
)

# Add to system prompt
SYSTEM_PROMPT += POLL_PROMPT_ADDITION

# Add to tool aggregation
def get_legacy_tools() -> list[dict]:
    return LEGACY_TOOLS + get_coding_tools() + get_poll_tools() + [...]

# Add handler in execute_tool_v2()
elif is_poll_tool(tool_name):
    log(f"Poll tool {tool_name}: {args_str(tool_args)}", "INFO")
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    result = await handle_poll_tool(tool_name, tool_args, message.channel, bot_token)
    
    # Store poll creation in memory
    if memory_store and len(str(result)) > 50:
        try:
            memory_store.store(
                f"Tool: {tool_name}({json.dumps(tool_args)[:200]})\nResult: {str(result)[:300]}",
                metadata={
                    "project": project.name if project else "default",
                    "session_id": str(channel_id),
                },
                event_type="tool",
            )
        except Exception:
            pass
    
    return result
```

### 6. Progress Description

```python
# In tool_descriptions.py

if tool_name == "create_poll":
    question = tool_args.get("question", "?")
    num_answers = len(tool_args.get("answers", []))
    duration = tool_args.get("duration_hours", 24)
    return f"📊 Creating poll: '{question[:50]}' ({num_answers} options, {duration}h)"
```

---

## Usage Examples

### Example 1: Simple Yes/No Poll

```python
result = await create_poll(
    channel=channel,
    question="Should we deploy the new feature today?",
    answers=["Yes, deploy now", "No, wait until Monday"],
    duration_hours=2,
)
# Result: {"success": true, "message_id": "1234..."}
```

### Example 2: Multi-Select Survey

```python
result = await create_poll(
    channel=channel,
    question="Which features do you use regularly? (select all that apply)",
    answers=["Dark mode", "Keyboard shortcuts", "Auto-save", "Export", "Notifications"],
    duration_hours=168,  # 1 week
    allow_multiselect=True,
)
```

### Example 3: Rating Scale

```python
result = await create_poll(
    channel=channel,
    question="How would you rate the new UI?",
    answers=["⭐ 1 - Poor", "⭐⭐ 2 - Fair", "⭐⭐⭐ 3 - Good", "⭐⭐⭐⭐ 4 - Great", "⭐⭐⭐⭐⭐ 5 - Excellent"],
    duration_hours=48,
)
```

### Example 4: Priority Selection

```python
result = await create_poll(
    channel=channel,
    question="Which bug has the highest impact on your workflow?",
    answers=[
        "Bug #123: Login timeout after 5 min",
        "Bug #456: Data sync delays",
        "Bug #789: UI freezes on large datasets",
        "Bug #101: Export fails for CSV files",
    ],
    duration_hours=24,
)
```

---

## Testing Code

### Unit Test for Validation

```python
def test_validation():
    # Valid poll
    error = validate_poll_parameters(
        question="What's your favorite color?",
        answers=["Red", "Blue", "Green"],
        duration_hours=24
    )
    assert error is None, "Valid poll should pass validation"
    
    # Invalid: question too long
    error = validate_poll_parameters(
        question="x" * 301,
        answers=["A", "B"],
        duration_hours=24
    )
    assert error is not None, "Long question should fail"
    assert "exceeds 300 characters" in error
```

### Integration Test

```python
async def test_poll_creation_live(bot, channel):
    """Test poll creation in a real Discord channel"""
    result = await create_poll(
        channel=channel,
        question="Test poll - please ignore",
        answers=["Option A", "Option B", "Option C"],
        duration_hours=1,
        bot_token=bot.http.token,
    )
    
    assert result["success"] == True, f"Poll creation failed: {result.get('error')}"
    assert "message_id" in result, "Missing message_id in result"
    
    print(f"✅ Poll created successfully: {result['message_id']}")
```

---

## Discord API Payload

### What Gets Sent to Discord

```json
POST /channels/{channel_id}/messages

{
  "poll": {
    "question": {
      "text": "Which feature should we prioritize next?"
    },
    "answers": [
      {"poll_media": {"text": "Dark mode"}},
      {"poll_media": {"text": "API v2"}},
      {"poll_media": {"text": "Mobile app"}},
      {"poll_media": {"text": "Performance"}}
    ],
    "duration": 48,
    "allow_multiselect": false
  }
}
```

### What Discord Returns

```json
{
  "id": "1234567890123456789",
  "type": 0,
  "content": "",
  "channel_id": "9876543210987654321",
  "author": {...},
  "poll": {
    "question": {"text": "Which feature should we prioritize next?"},
    "answers": [...],
    "expiry": "2026-08-21T12:00:00.000000+00:00",
    "allow_multiselect": false,
    "results": {
      "is_finalized": false,
      "answer_counts": [...]
    }
  },
  ...
}
```

---

## Files Reference

- **Implementation:** `/opt/Project-Tango/scripts/poll_tools.py`
- **Integration:** `/opt/Project-Tango/scripts/schubert-bot-v2.py`
- **Tests:** `/opt/Project-Tango/scripts/test_poll_tools.py`
- **Docs:** `/opt/Project-Tango/docs/POLL_TOOLS.md`
- **Quick Start:** `/opt/Project-Tango/docs/POLL_TOOLS_QUICKSTART.md`
- **This File:** `/opt/Project-Tango/docs/POLL_TOOLS_CODE_EXAMPLES.md`

---

**Status:** ✅ Implementation Complete  
**Version:** 1.0  
**Date:** 2026-08-19
