#!/usr/bin/env python3
"""
Pinned Resource Management Tools for Discord Agents
=====================================================
Provides agent tools for creating, managing, and listing pinned resource
messages with rich embeds. Enables the LLM to pin reference material,
documentation links, status dashboards, and other persistent content.

Functions:
    execute_pinned_resource_tool(tool_name, args, channel)
        Execute a pinned resource tool (pin_resource, unpin_resource, list_pinned).
    
    get_pinned_resource_tools()
        Return tool definitions for OpenAI function calling format.

Tool Handlers:
    - pin_resource: Create and pin a rich embed with title, description, fields
    - unpin_resource: Unpin and delete a resource message by ID
    - list_pinned: List all pinned messages in the channel

Author: Cursor Agent
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord

if TYPE_CHECKING:
    from discord.abc import Messageable

from discord_ux_utils import validate_embed_limits, send_silent

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Color Constants
# ---------------------------------------------------------------------------

COLOR_PURPLE = 0x9B59B6  # Default color for pinned resources
COLOR_SUCCESS = 0x2ECC71
COLOR_ERROR = 0xE74C3C
COLOR_INFO = 0x3498DB


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

async def execute_pinned_resource_tool(
    tool_name: str,
    args: dict,
    channel: Messageable,
) -> str:
    """
    Execute a pinned resource management tool.

    Args:
        tool_name: name of the tool to execute
        args: tool arguments from the LLM
        channel: Discord channel or thread to operate in

    Returns:
        str: JSON-serialized result with success status and data

    Raises:
        No exceptions — all errors are caught and returned as JSON

    Supported tools:
        - pin_resource: Create and pin a rich embed
        - unpin_resource: Unpin and delete a resource message
        - list_pinned: List all pinned messages in the channel
    """

    if tool_name == "pin_resource":
        return await _handle_pin_resource(args, channel)

    elif tool_name == "unpin_resource":
        return await _handle_unpin_resource(args, channel)

    elif tool_name == "list_pinned":
        return await _handle_list_pinned(channel)

    else:
        return json.dumps({
            "success": False,
            "error": f"Unknown tool: {tool_name}",
        })


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------

async def _handle_pin_resource(args: dict, channel: Messageable) -> str:
    """
    Create and pin a rich embed resource message.

    Args:
        args: dict with keys:
            - title (str, max 256 chars)
            - description (str, max 4096 chars)
            - fields (list[dict], max 25 fields with name/value/inline)
            - color (str, hex code like "0x9B59B6", optional)
        channel: Discord channel or thread

    Returns:
        str: JSON result with success, message_id, url, or error
    """
    try:
        # Extract arguments
        title = args.get("title", "")
        description = args.get("description", "")
        fields = args.get("fields", [])
        color_str = args.get("color", "")

        # Validate required fields
        if not title:
            return json.dumps({
                "success": False,
                "error": "Title is required",
            })

        if not description:
            return json.dumps({
                "success": False,
                "error": "Description is required",
            })

        # Parse color (default to purple)
        try:
            if color_str:
                # Handle both "0x9B59B6" and "9B59B6" formats
                color_str = color_str.strip()
                if color_str.startswith("0x"):
                    color = int(color_str, 16)
                else:
                    color = int(color_str, 16)
            else:
                color = COLOR_PURPLE
        except ValueError:
            return json.dumps({
                "success": False,
                "error": f"Invalid color format: {color_str}. Use hex like '0x9B59B6'",
            })

        # Validate embed limits
        is_valid, error_msg = validate_embed_limits(title, description, fields)
        if not is_valid:
            return json.dumps({
                "success": False,
                "error": f"Embed validation failed: {error_msg}",
            })

        # Create embed
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )

        # Add fields
        for field in fields:
            field_name = field.get("name", "")
            field_value = field.get("value", "")
            field_inline = field.get("inline", False)

            if not field_name or not field_value:
                continue

            embed.add_field(
                name=field_name,
                value=field_value,
                inline=field_inline,
            )

        # Set footer
        embed.set_footer(text="📌 Pinned resource • Managed by agent")

        # Send silently
        message = await send_silent(channel, embed=embed)

        # Pin the message
        try:
            await message.pin()
        except discord.Forbidden:
            # Try to delete the message if we can't pin it
            try:
                await message.delete()
            except Exception:
                pass
            return json.dumps({
                "success": False,
                "error": "Permission denied: cannot pin messages in this channel",
            })
        except discord.HTTPException as e:
            # Try to delete the message if pinning fails
            try:
                await message.delete()
            except Exception:
                pass
            return json.dumps({
                "success": False,
                "error": f"Failed to pin message: {e}",
            })

        # Return success result
        return json.dumps({
            "success": True,
            "message_id": str(message.id),
            "url": message.jump_url,
        })

    except discord.Forbidden:
        return json.dumps({
            "success": False,
            "error": "Permission denied: cannot send messages in this channel",
        })
    except discord.HTTPException as e:
        logger.error(f"Discord HTTP error in pin_resource: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Discord API error: {e}",
        })
    except Exception as e:
        logger.error(f"Unexpected error in pin_resource: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Internal error: {e}",
        })


async def _handle_unpin_resource(args: dict, channel: Messageable) -> str:
    """
    Unpin and delete a resource message.

    Args:
        args: dict with keys:
            - message_id (str, Discord message ID)
        channel: Discord channel or thread

    Returns:
        str: JSON result with success or error
    """
    try:
        # Extract message ID
        message_id_str = args.get("message_id", "")
        if not message_id_str:
            return json.dumps({
                "success": False,
                "error": "message_id is required",
            })

        # Parse message ID
        try:
            message_id = int(message_id_str)
        except ValueError:
            return json.dumps({
                "success": False,
                "error": f"Invalid message_id: {message_id_str}",
            })

        # Fetch the message
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return json.dumps({
                "success": False,
                "error": f"Message not found: {message_id}",
            })
        except discord.Forbidden:
            return json.dumps({
                "success": False,
                "error": "Permission denied: cannot read message history",
            })
        except discord.HTTPException as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to fetch message: {e}",
            })

        # Unpin the message
        if message.pinned:
            try:
                await message.unpin()
            except discord.Forbidden:
                return json.dumps({
                    "success": False,
                    "error": "Permission denied: cannot unpin messages",
                })
            except discord.HTTPException as e:
                return json.dumps({
                    "success": False,
                    "error": f"Failed to unpin message: {e}",
                })

        # Delete the message
        try:
            await message.delete()
        except discord.Forbidden:
            return json.dumps({
                "success": False,
                "error": "Permission denied: cannot delete messages (message was unpinned)",
            })
        except discord.HTTPException as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to delete message (message was unpinned): {e}",
            })

        # Return success
        return json.dumps({
            "success": True,
        })

    except Exception as e:
        logger.error(f"Unexpected error in unpin_resource: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Internal error: {e}",
        })


async def _handle_list_pinned(channel: Messageable) -> str:
    """
    List all pinned messages in the channel.

    Args:
        channel: Discord channel or thread

    Returns:
        str: JSON result with success and pinned array
    """
    try:
        # Fetch pinned messages
        try:
            pinned_messages = await channel.pins()
        except discord.Forbidden:
            return json.dumps({
                "success": False,
                "error": "Permission denied: cannot read pinned messages",
            })
        except discord.HTTPException as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to fetch pinned messages: {e}",
            })

        # Extract title and metadata for each pin
        pinned_list = []
        for msg in pinned_messages:
            # Try to extract title from embed first
            title = None
            if msg.embeds:
                embed = msg.embeds[0]
                if embed.title:
                    title = embed.title
                elif embed.description:
                    # Use first 50 chars of description if no title
                    title = embed.description[:50]
                    if len(embed.description) > 50:
                        title += "..."

            # Fall back to message content
            if not title and msg.content:
                title = msg.content[:50]
                if len(msg.content) > 50:
                    title += "..."

            # Default if still no title
            if not title:
                title = "(No title)"

            pinned_list.append({
                "id": str(msg.id),
                "title": title,
                "url": msg.jump_url,
            })

        # Return success result
        return json.dumps({
            "success": True,
            "pinned": pinned_list,
        })

    except Exception as e:
        logger.error(f"Unexpected error in list_pinned: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Internal error: {e}",
        })


# ---------------------------------------------------------------------------
# Tool Definitions (OpenAI Function Calling Format)
# ---------------------------------------------------------------------------

def get_pinned_resource_tools() -> list[dict]:
    """
    Return OpenAI function calling tool definitions for pinned resources.

    Returns:
        list[dict]: Tool definitions in OpenAI format
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "pin_resource",
                "description": (
                    "Create and pin a rich embed resource message in the channel. "
                    "Useful for pinning documentation, reference links, status dashboards, "
                    "and other persistent information that should be easily accessible. "
                    "The message is sent silently (no push notification) and automatically pinned."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Embed title (max 256 characters)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Embed description/body text (max 4096 characters)",
                        },
                        "fields": {
                            "type": "array",
                            "description": "Optional array of field objects (max 25 fields)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Field name (max 256 characters)",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "Field value (max 1024 characters)",
                                    },
                                    "inline": {
                                        "type": "boolean",
                                        "description": "Whether to display inline (default false)",
                                    },
                                },
                                "required": ["name", "value"],
                            },
                        },
                        "color": {
                            "type": "string",
                            "description": (
                                "Hex color code for the embed sidebar (e.g. '0x9B59B6'). "
                                "Optional, defaults to purple (0x9B59B6)."
                            ),
                        },
                    },
                    "required": ["title", "description"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "unpin_resource",
                "description": (
                    "Unpin and delete a resource message by its message ID. "
                    "Use this to remove outdated or no longer needed pinned resources. "
                    "The message is first unpinned, then deleted."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "Discord message ID of the pinned resource to remove",
                        },
                    },
                    "required": ["message_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_pinned",
                "description": (
                    "List all pinned messages in the current channel. "
                    "Returns message IDs, titles (extracted from embeds or content), "
                    "and jump URLs for each pinned message."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    ]
