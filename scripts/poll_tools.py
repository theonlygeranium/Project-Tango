"""
Discord Poll Creation Tool — Native Poll Support for Agent Decision-Making
===========================================================================

Provides native Discord poll creation using the Discord REST API v10.

Discord's native poll feature (introduced in 2024) supports:
  - Question text (max 300 chars)
  - Up to 10 answer options (max 55 chars each)
  - Duration: 1-768 hours
  - Single-select or multi-select voting
  - Native voting UI with real-time vote counts

Tools:
  1. create_poll — Create a native Discord poll

Use Cases:
  - Senior staff meeting decisions (e.g., "Which architecture should we use?")
  - Bot channel feedback collection (e.g., "Rate this feature: 1-5")
  - Agent-initiated polls when needing human input
  - Project planning consensus gathering

Integration:
  - Integrates with schubert-bot-v2.py agent loop
  - Uses OpenAI function calling format
  - Handles validation and permission errors
  - Returns message ID for tracking

Example:
    from poll_tools import get_poll_tools, handle_poll_tool
    
    tools = get_poll_tools()
    result = await handle_poll_tool(
        "create_poll",
        {
            "question": "Which feature should we prioritize?",
            "answers": ["Authentication", "Dark Mode", "API v2"],
            "duration_hours": 48,
            "allow_multiselect": False
        },
        channel,
        bot_token
    )
"""

from __future__ import annotations

import aiohttp
from typing import Any, Optional
import discord

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_QUESTION_LENGTH = 300
MAX_ANSWER_LENGTH = 55
MAX_ANSWERS = 10
MIN_DURATION = 1
MAX_DURATION = 768  # 32 days in hours


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_poll_parameters(
    question: str,
    answers: list[str],
    duration_hours: int,
) -> Optional[str]:
    """
    Validate poll parameters according to Discord API constraints.
    
    Returns None if valid, or an error message string if invalid.
    """
    # Validate question
    if not question or not question.strip():
        return "Question cannot be empty"
    if len(question) > MAX_QUESTION_LENGTH:
        return f"Question exceeds {MAX_QUESTION_LENGTH} characters (got {len(question)})"
    
    # Validate answers
    if not answers or len(answers) < 2:
        return "Poll must have at least 2 answer options"
    if len(answers) > MAX_ANSWERS:
        return f"Poll cannot have more than {MAX_ANSWERS} answers (got {len(answers)})"
    
    for i, answer in enumerate(answers, 1):
        if not answer or not answer.strip():
            return f"Answer {i} cannot be empty"
        if len(answer) > MAX_ANSWER_LENGTH:
            return f"Answer {i} exceeds {MAX_ANSWER_LENGTH} characters (got {len(answer)})"
    
    # Validate duration
    if duration_hours < MIN_DURATION:
        return f"Duration must be at least {MIN_DURATION} hour (got {duration_hours})"
    if duration_hours > MAX_DURATION:
        return f"Duration cannot exceed {MAX_DURATION} hours (got {duration_hours})"
    
    return None


# ---------------------------------------------------------------------------
# Poll Creation
# ---------------------------------------------------------------------------

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
    
    Args:
        channel: Discord text channel to post the poll in
        question: Poll question (max 300 chars)
        answers: List of answer options (2-10 items, max 55 chars each)
        duration_hours: Hours until poll closes (1-768, default 24)
        allow_multiselect: Whether users can select multiple answers
        bot_token: Discord bot token (optional, will use channel._state.http if not provided)
    
    Returns:
        dict with keys:
            - success: bool
            - message_id: str (if successful)
            - error: str (if failed)
    
    Example:
        result = await create_poll(
            channel,
            "What's your favorite color?",
            ["Red", "Blue", "Green"],
            duration_hours=48,
            allow_multiselect=False
        )
        if result["success"]:
            print(f"Poll created: {result['message_id']}")
        else:
            print(f"Error: {result['error']}")
    """
    # Validate parameters
    validation_error = validate_poll_parameters(question, answers, duration_hours)
    if validation_error:
        return {
            "success": False,
            "error": f"Validation failed: {validation_error}"
        }
    
    # Build poll payload
    payload = {
        "poll": {
            "question": {"text": question.strip()},
            "answers": [
                {"poll_media": {"text": answer.strip()}}
                for answer in answers
            ],
            "duration": duration_hours,
            "allow_multiselect": allow_multiselect,
        }
    }
    
    # Try using discord.py's HTTP client first
    if not bot_token:
        try:
            # discord.py 2.x may not have native poll support in send_message
            # Try to use the internal HTTP client with raw JSON
            http = channel._state.http
            
            # Use the raw request method if available
            if hasattr(http, "request"):
                response = await http.request(
                    discord.http.Route("POST", f"/channels/{channel.id}/messages"),
                    json=payload
                )
                return {
                    "success": True,
                    "message_id": response["id"],
                }
            else:
                # Fallback: need bot token for raw aiohttp
                return {
                    "success": False,
                    "error": "Bot token required for poll creation (discord.py HTTP client incompatible)"
                }
        except AttributeError as e:
            # discord.py version doesn't support this, fall back to raw aiohttp
            if not bot_token:
                return {
                    "success": False,
                    "error": f"Bot token required (discord.py fallback failed: {e})"
                }
        except discord.HTTPException as e:
            return {
                "success": False,
                "error": f"Discord API error: {e.status} - {e.text}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }
    
    # Raw aiohttp fallback (or if bot_token provided)
    if bot_token:
        try:
            url = f"{DISCORD_API_BASE}/channels/{channel.id}/messages"
            headers = {
                "Authorization": f"Bot {bot_token}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (Project-Tango, 2.0)"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200 or resp.status == 201:
                        data = await resp.json()
                        return {
                            "success": True,
                            "message_id": data["id"],
                        }
                    else:
                        error_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"HTTP {resp.status}: {error_text}"
                        }
        except aiohttp.ClientError as e:
            return {
                "success": False,
                "error": f"Network error: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }
    
    return {
        "success": False,
        "error": "No valid method available for poll creation"
    }


# ---------------------------------------------------------------------------
# Tool Definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool Handler
# ---------------------------------------------------------------------------

async def handle_poll_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    channel: discord.TextChannel,
    bot_token: Optional[str] = None,
) -> str:
    """
    Handle poll tool execution.
    
    Args:
        tool_name: Name of the tool to execute (should be "create_poll")
        tool_args: Tool arguments from LLM
        channel: Discord channel context
        bot_token: Optional bot token for raw API calls
    
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


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def is_poll_tool(tool_name: str) -> bool:
    """Check if a tool name is a poll tool."""
    return tool_name == "create_poll"


# ---------------------------------------------------------------------------
# Prompt Addition (for agent system prompt)
# ---------------------------------------------------------------------------

POLL_PROMPT_ADDITION = """
## Native Discord Polls

You can create native Discord polls to gather human feedback or consensus:

- Use `create_poll` when you need team input on a decision
- Polls show as native Discord voting UI with real-time counts
- Examples:
  - "Which architecture approach should we use? [Option A, Option B, Option C]"
  - "Rate the new feature: [1 - Poor, 2 - Fair, 3 - Good, 4 - Great, 5 - Excellent]"
  - "Which bug should we prioritize? [Bug #123, Bug #456, Bug #789]"

Guidelines:
- Keep questions clear and specific (max 300 chars)
- Provide 2-10 distinct answer options (max 55 chars each)
- Set appropriate duration:
  - 1-4 hours for urgent decisions
  - 24-48 hours for normal team decisions
  - 168 hours (1 week) for long-term planning
- Use multi-select for "select all that apply" questions
"""
