#!/usr/bin/env python3
"""
Example Integration — Pinned Resource Tools
============================================
Demonstrates how to integrate pinned_resources_tools.py into an existing
Discord bot with OpenAI function calling.

This example shows:
1. Importing the tool functions and definitions
2. Adding pinned resource tools to the tool list
3. Executing pinned resource tools in the agent loop
4. Handling tool responses

Integration Steps:
------------------

1. Import the module at the top of your bot script:

    from pinned_resources_tools import (
        execute_pinned_resource_tool,
        get_pinned_resource_tools,
    )

2. Add the tools to your tool definitions function:

    def get_all_tools() -> list[dict]:
        tools = []
        tools.extend(get_dev_tools())
        tools.extend(get_pinned_resource_tools())  # Add this line
        # ... add other tools ...
        return tools

3. Add tool execution in your execute_tool function:

    async def execute_tool(tool_name: str, args: dict, channel) -> str:
        # Check if it's a pinned resource tool
        if tool_name in ["pin_resource", "unpin_resource", "list_pinned"]:
            return await execute_pinned_resource_tool(tool_name, args, channel)
        
        # ... handle other tools ...

4. Update tool_descriptions.py (optional, for progress display):

    Add to describe_tool_call():
    
    if tool_name == "pin_resource":
        title = tool_args.get("title", "?")[:50]
        return f"📌 Pinning resource: {title}"
    
    if tool_name == "unpin_resource":
        msg_id = tool_args.get("message_id", "?")
        return f"📌 Unpinning resource: {msg_id}"
    
    if tool_name == "list_pinned":
        return "📌 Listing pinned resources"

Example Usage:
--------------

Once integrated, the agent can use natural language commands like:

- "Pin a resource with title 'API Docs' and description 'FastAPI docs: https://...'"
- "List all pinned resources"
- "Unpin the resource with ID 1234567890"

The LLM will automatically call the appropriate tool with properly formatted arguments.

Security Notes:
---------------

- All tools respect Discord permissions (Manage Messages required for pinning)
- Messages are sent with silent=True to avoid push notifications
- Comprehensive error handling for all Discord API errors
- Input validation via discord_ux_utils.validate_embed_limits()
"""

# ---------------------------------------------------------------------------
# Example Bot Integration (Simplified)
# ---------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import discord

# Import pinned resources tools
from pinned_resources_tools import (
    execute_pinned_resource_tool,
    get_pinned_resource_tools,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Simplified Tool System
# ---------------------------------------------------------------------------

def get_all_tools() -> list[dict]:
    """
    Combine all tool definitions for the LLM.
    
    Add get_pinned_resource_tools() to include pinned resource management.
    """
    tools = []
    
    # Add your existing tools
    # tools.extend(get_dev_tools())
    # tools.extend(get_mcp_tools())
    
    # Add pinned resource tools
    tools.extend(get_pinned_resource_tools())
    
    return tools


async def execute_tool(
    tool_name: str,
    args: dict,
    channel: discord.abc.Messageable,
) -> str:
    """
    Execute a tool by name.
    
    Routes pinned resource tools to execute_pinned_resource_tool().
    """
    
    # Check if it's a pinned resource tool
    if tool_name in ["pin_resource", "unpin_resource", "list_pinned"]:
        return await execute_pinned_resource_tool(tool_name, args, channel)
    
    # Handle other tools
    # ...
    
    return json.dumps({
        "success": False,
        "error": f"Unknown tool: {tool_name}",
    })


# ---------------------------------------------------------------------------
# Example Agent Loop (Simplified)
# ---------------------------------------------------------------------------

async def run_agent_loop(message: discord.Message, user_input: str) -> str:
    """
    Simplified agent loop showing tool integration.
    
    In a real bot, this would include:
    - Session history management
    - OpenAI API streaming
    - Multi-turn conversation
    - Progress indicators
    """
    
    # Get all available tools
    tools = get_all_tools()
    
    # Prepare messages for OpenAI
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful Discord bot assistant. "
                "You can manage pinned resources using the pin_resource, "
                "unpin_resource, and list_pinned tools."
            ),
        },
        {
            "role": "user",
            "content": user_input,
        },
    ]
    
    # Call OpenAI (pseudocode)
    # response = await openai_client.chat.completions.create(
    #     model="gpt-4",
    #     messages=messages,
    #     tools=tools,
    #     stream=True,
    # )
    
    # Process tool calls (pseudocode)
    # for chunk in response:
    #     if chunk.choices[0].delta.tool_calls:
    #         for tool_call in chunk.choices[0].delta.tool_calls:
    #             tool_name = tool_call.function.name
    #             tool_args = json.loads(tool_call.function.arguments)
    #             
    #             # Execute tool
    #             result = await execute_tool(tool_name, tool_args, message.channel)
    #             
    #             # Add tool result to messages
    #             messages.append({
    #                 "role": "tool",
    #                 "tool_call_id": tool_call.id,
    #                 "content": result,
    #             })
    
    return "Response from agent"


# ---------------------------------------------------------------------------
# Example Commands
# ---------------------------------------------------------------------------

def get_example_commands() -> list[str]:
    """
    Example natural language commands that will trigger the pinned resource tools.
    """
    return [
        # Pin resource examples
        "Pin a resource titled 'API Documentation' with a link to our FastAPI docs",
        "Create a pinned reference for the deployment process",
        "Pin a status dashboard showing service health",
        
        # List pinned examples
        "What resources are currently pinned?",
        "Show me all pinned messages",
        "List pinned resources",
        
        # Unpin resource examples
        "Remove the pinned resource with ID 1234567890",
        "Unpin the API docs message",
        "Delete the old status dashboard (ID: 9876543210)",
    ]


# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

async def test_pinned_resources(channel: discord.abc.Messageable):
    """
    Test all three pinned resource tools.
    
    Run this in a test channel to verify integration.
    """
    
    print("🧪 Testing pinned resource tools...")
    
    # Test 1: Pin a resource
    print("\n📌 Test 1: Pin a resource")
    result = await execute_pinned_resource_tool(
        "pin_resource",
        {
            "title": "Test Resource",
            "description": "This is a test pinned resource.",
            "fields": [
                {"name": "Field 1", "value": "Value 1", "inline": True},
                {"name": "Field 2", "value": "Value 2", "inline": True},
            ],
            "color": "0x3498DB",
        },
        channel,
    )
    result_data = json.loads(result)
    print(f"Result: {result}")
    
    if not result_data.get("success"):
        print("❌ Failed to pin resource")
        return
    
    message_id = result_data.get("message_id")
    print(f"✅ Pinned resource with ID: {message_id}")
    
    # Test 2: List pinned resources
    print("\n📌 Test 2: List pinned resources")
    result = await execute_pinned_resource_tool(
        "list_pinned",
        {},
        channel,
    )
    result_data = json.loads(result)
    print(f"Result: {result}")
    
    if not result_data.get("success"):
        print("❌ Failed to list pinned resources")
        return
    
    pinned_count = len(result_data.get("pinned", []))
    print(f"✅ Found {pinned_count} pinned messages")
    
    # Test 3: Unpin the resource
    print("\n📌 Test 3: Unpin the resource")
    if message_id:
        result = await execute_pinned_resource_tool(
            "unpin_resource",
            {"message_id": message_id},
            channel,
        )
        result_data = json.loads(result)
        print(f"Result: {result}")
        
        if result_data.get("success"):
            print("✅ Successfully unpinned and deleted resource")
        else:
            print("❌ Failed to unpin resource")
    else:
        print("⚠️ Skipped (no message_id from test 1)")
    
    print("\n🎉 Tests complete!")


if __name__ == "__main__":
    print(__doc__)
    print("\n" + "=" * 70)
    print("Example Commands:")
    print("=" * 70)
    for cmd in get_example_commands():
        print(f"  • {cmd}")
    print("=" * 70)
