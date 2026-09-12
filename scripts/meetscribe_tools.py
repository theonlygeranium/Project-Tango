"""
MeetScribe Tools — Agent Tool Definitions for Meeting Corpus Integration
=========================================================================
Provides OpenAI function-calling tool definitions and handlers that let the
Discord bot agent query meeting notes and transcripts via the MeetScribe API.

Tools:
  1. query_meetings       — RAG question answering across meeting corpus
  2. search_meetings      — Full-text search across titles, notes, transcripts
  3. list_recent_meetings — List recent meeting sessions
  4. get_meeting_notes    — Fetch AI summary, action items, key decisions
  5. get_meeting_transcript — Fetch transcript for a specific meeting
  6. get_meetscribe_status — Check MeetScribe memory index status

Usage:
    from meetscribe_tools import (
        get_meetscribe_tools,
        handle_meetscribe_tool,
        is_meetscribe_tool,
        get_meetscribe_client,
        close_meetscribe_client,
        MEETSCRIBE_PROMPT_ADDITION,
    )

    tools = get_meetscribe_tools()
    client = get_meetscribe_client()
    if client:
        result = await handle_meetscribe_tool("query_meetings", {"question": "Q3 roadmap"}, client)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from meetscribe_client import (
    MeetScribeClient,
    format_corpus_answer,
    format_session_list,
    format_session_notes,
)

logger = logging.getLogger("schubert-bot.meetscribe-tools")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MEETSCRIBE_OUTPUT_LIMIT = 3000  # Max chars for tool output (same as CODING_OUTPUT_LIMIT)


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling format)
# ---------------------------------------------------------------------------

def get_meetscribe_tools() -> list[dict]:
    """Return MeetScribe tool definitions for the LLM."""
    return [
        {
            "type": "function",
            "function": {
                "name": "query_meetings",
                "description": (
                    "Ask a natural language question about meetings and get a "
                    "grounded answer with cited sources. Use this when the user "
                    "asks about what was discussed, decided, or covered in meetings. "
                    "Examples: 'What was decided about the Q3 roadmap?', "
                    "'Did anyone mention the budget cut?', 'What action items came "
                    "out of last week's sync?'"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The natural language question about meetings",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of source sessions to consider (default 5)",
                            "default": 5,
                        },
                    },
                    "required": ["question"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_meetings",
                "description": (
                    "Full-text search across meeting titles, notes, and transcripts. "
                    "Use this for keyword searches when the user is looking for "
                    "specific terms or topics. Examples: 'budget', 'Q3 roadmap', "
                    "'action item: deploy'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (keywords or phrases)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 10)",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_recent_meetings",
                "description": (
                    "List recent meeting sessions. Use this to show the user "
                    "what meetings are available. Returns session IDs, titles, "
                    "dates, and status."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of sessions to return (default 10)",
                            "default": 10,
                        },
                        "status": {
                            "type": "string",
                            "description": (
                                "Filter by session status (e.g., 'completed', "
                                "'processing'). Omit to list all statuses."
                            ),
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_meeting_notes",
                "description": (
                    "Fetch AI summary, action items, and key decisions for a "
                    "specific meeting. Use this after listing meetings or when "
                    "the user references a specific session by ID."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "integer",
                            "description": "The MeetScribe session ID of the meeting",
                        },
                    },
                    "required": ["session_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_meeting_transcript",
                "description": (
                    "Fetch the full transcript for a specific meeting. Use this "
                    "when the user wants to see what was said verbatim in a meeting. "
                    "Returns transcript segments with speaker labels and timestamps."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_id": {
                            "type": "integer",
                            "description": "The MeetScribe session ID of the meeting",
                        },
                    },
                    "required": ["session_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_meetscribe_status",
                "description": (
                    "Check the MeetScribe memory index status. Returns the number "
                    "of indexed chunks and sessions. Use this to verify the "
                    "MeetScribe integration is healthy."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool identification
# ---------------------------------------------------------------------------

_MEETSCRIBE_TOOL_NAMES = {
    "query_meetings",
    "search_meetings",
    "list_recent_meetings",
    "get_meeting_notes",
    "get_meeting_transcript",
    "get_meetscribe_status",
}


def is_meetscribe_tool(tool_name: str) -> bool:
    """Check if a tool name is a MeetScribe tool."""
    return tool_name in _MEETSCRIBE_TOOL_NAMES


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

async def handle_meetscribe_tool(
    tool_name: str,
    tool_args: dict,
    client: MeetScribeClient,
) -> str:
    """
    Handle a MeetScribe tool call and return a formatted string result.

    Args:
        tool_name: The name of the MeetScribe tool to execute
        tool_args: Tool arguments from the LLM
        client: An initialized MeetScribeClient instance

    Returns:
        Formatted string result for the LLM. Never raises exceptions;
        errors are returned as strings.
    """
    try:
        if tool_name == "query_meetings":
            return await _handle_query_meetings(tool_args, client)
        elif tool_name == "search_meetings":
            return await _handle_search_meetings(tool_args, client)
        elif tool_name == "list_recent_meetings":
            return await _handle_list_recent_meetings(tool_args, client)
        elif tool_name == "get_meeting_notes":
            return await _handle_get_meeting_notes(tool_args, client)
        elif tool_name == "get_meeting_transcript":
            return await _handle_get_meeting_transcript(tool_args, client)
        elif tool_name == "get_meetscribe_status":
            return await _handle_get_meetscribe_status(tool_args, client)
        else:
            return f"Error: unknown MeetScribe tool '{tool_name}'"
    except Exception as exc:
        logger.error("MeetScribe tool '%s' failed: %s", tool_name, exc, exc_info=True)
        return f"Error in {tool_name}: {exc}"


async def _handle_query_meetings(args: dict, client: MeetScribeClient) -> str:
    """Handle query_meetings — RAG question answering across meeting corpus."""
    question = args.get("question", "")
    limit = args.get("limit", 5)

    if not question:
        return "Error: question is required"

    result = await client.query_corpus(question, limit=limit)
    formatted = format_corpus_answer(result)

    if len(formatted) > MEETSCRIBE_OUTPUT_LIMIT:
        formatted = formatted[:MEETSCRIBE_OUTPUT_LIMIT] + "\n... (truncated)"
    return formatted


async def _handle_search_meetings(args: dict, client: MeetScribeClient) -> str:
    """Handle search_meetings — full-text search across meeting content."""
    query = args.get("query", "")
    limit = args.get("limit", 10)

    if not query:
        return "Error: query is required"

    result = await client.search_sessions(query, limit=limit)

    if isinstance(result, dict) and "error" in result:
        return f"❌ MeetScribe search failed: {result.get('error', 'unknown error')}"

    sessions = result if isinstance(result, list) else result.get("sessions", result.get("results", []))
    if not sessions:
        return f"No meetings found matching '{query}'."

    formatted = format_session_list(sessions)

    if len(formatted) > MEETSCRIBE_OUTPUT_LIMIT:
        formatted = formatted[:MEETSCRIBE_OUTPUT_LIMIT] + "\n... (truncated)"
    return formatted


async def _handle_list_recent_meetings(args: dict, client: MeetScribeClient) -> str:
    """Handle list_recent_meetings — list recent meeting sessions."""
    limit = args.get("limit", 10)
    status = args.get("status")

    result = await client.list_sessions(limit=limit, status=status)

    if isinstance(result, dict) and "error" in result:
        return f"❌ Failed to list meetings: {result.get('error', 'unknown error')}"

    sessions = result if isinstance(result, list) else result.get("sessions", [])
    formatted = format_session_list(sessions)

    if len(formatted) > MEETSCRIBE_OUTPUT_LIMIT:
        formatted = formatted[:MEETSCRIBE_OUTPUT_LIMIT] + "\n... (truncated)"
    return formatted


async def _handle_get_meeting_notes(args: dict, client: MeetScribeClient) -> str:
    """Handle get_meeting_notes — fetch AI summary, action items, key decisions."""
    session_id = args.get("session_id")

    if session_id is None:
        return "Error: session_id is required"

    result = await client.get_session_notes(session_id)
    if isinstance(result, dict) and "error" in result:
        return f"❌ Failed to fetch notes: {result.get('error', 'unknown error')}"
    formatted = format_session_notes(result)

    if len(formatted) > MEETSCRIBE_OUTPUT_LIMIT:
        formatted = formatted[:MEETSCRIBE_OUTPUT_LIMIT] + "\n... (truncated)"
    return formatted


async def _handle_get_meeting_transcript(args: dict, client: MeetScribeClient) -> str:
    """Handle get_meeting_transcript — fetch transcript for a specific meeting."""
    session_id = args.get("session_id")

    if session_id is None:
        return "Error: session_id is required"

    result = await client.get_session_transcript(session_id)

    if isinstance(result, dict) and "error" in result:
        return f"❌ Failed to fetch transcript: {result.get('error', 'unknown error')}"

    segments = result if isinstance(result, list) else result.get("segments", result.get("transcript", []))
    if not segments:
        return "No transcript available for this session."

    lines = []
    for seg in segments[:50]:
        speaker = seg.get("speaker", seg.get("speaker_name", "Unknown"))
        text = seg.get("text", seg.get("content", ""))
        start = seg.get("start_time", seg.get("start", ""))
        timestamp_str = f"[{start}] " if start else ""
        lines.append(f"{timestamp_str}**{speaker}:** {text}")

    formatted = "\n".join(lines)
    if len(formatted) > MEETSCRIBE_OUTPUT_LIMIT:
        formatted = formatted[:MEETSCRIBE_OUTPUT_LIMIT] + "\n... (truncated)"
    return formatted


async def _handle_get_meetscribe_status(args: dict, client: MeetScribeClient) -> str:
    """Handle get_meetscribe_status — check MeetScribe memory index status."""
    result = await client.get_memory_status()

    if isinstance(result, dict) and "error" in result:
        return f"❌ MeetScribe status check failed: {result.get('error', 'unknown error')}"

    chunks = result.get("chunks", result.get("total_chunks", 0))
    sessions = result.get("sessions_indexed", result.get("total_sessions", result.get("sessions", 0)))
    indexed = result.get("indexed", result.get("status", "unknown"))

    return (
        f"**MeetScribe Memory Index**\n"
        f"  • Indexed chunks: {chunks}\n"
        f"  • Indexed sessions: {sessions}\n"
        f"  • Status: {indexed}"
    )


# ---------------------------------------------------------------------------
# Prompt addition (for agent system prompt)
# ---------------------------------------------------------------------------

MEETSCRIBE_PROMPT_ADDITION = """
### MeetScribe Meeting Integration
You have access to MeetScribe tools that let you query meeting notes and transcripts:
- Use `query_meetings` when the user asks about what was discussed/decided in meetings
- Use `search_meetings` for keyword searches across meeting content
- Use `list_recent_meetings` to show recent meetings
- Use `get_meeting_notes` to fetch detailed notes for a specific meeting
- Use `get_meeting_transcript` to fetch the full transcript of a meeting
- Use `get_meetscribe_status` to check the MeetScribe memory index

When a user asks about work meetings, projects discussed in meetings, or decisions made in meetings,
use these tools to provide grounded answers with cited sources.
"""


# ---------------------------------------------------------------------------
# Singleton client management
# ---------------------------------------------------------------------------

_meetscribe_client: MeetScribeClient | None = None


def get_meetscribe_client() -> MeetScribeClient | None:
    """
    Get or create the singleton MeetScribeClient instance.

    The client is only created if MEETSCRIBE_ENABLED is true and
    MEETSCRIBE_API_KEY is set. Returns None if the integration is
    disabled or unconfigured.
    """
    global _meetscribe_client

    if _meetscribe_client is not None:
        return _meetscribe_client

    enabled = os.environ.get("MEETSCRIBE_ENABLED", "true").lower() not in {
        "0", "false", "no", "off",
    }
    if not enabled:
        logger.info("MeetScribe integration disabled (MEETSCRIBE_ENABLED=false)")
        return None

    api_key = os.environ.get("MEETSCRIBE_API_KEY", "")
    if not api_key:
        logger.warning("MeetScribe API key not configured (MEETSCRIBE_API_KEY not set)")
        return None

    _meetscribe_client = MeetScribeClient(api_key=api_key)
    logger.info("MeetScribeClient singleton created")
    return _meetscribe_client


async def close_meetscribe_client() -> None:
    """Close the MeetScribeClient connection."""
    global _meetscribe_client
    if _meetscribe_client is not None:
        await _meetscribe_client.close()
        _meetscribe_client = None
        logger.info("MeetScribeClient singleton closed")
