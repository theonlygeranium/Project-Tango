#!/usr/bin/env python3
"""
Integration Patch for Architect Bot — Pinned Resources
========================================================
This file shows the exact changes needed to integrate pinned_resources_tools
into architect-bot.py (or any other bot).

Apply these changes to enable pinned resource management in your bot.

Changes:
1. Add import at top of file
2. Add tool definitions to get_dev_tools()
3. Add tool execution to execute_dev_tool()
4. (Optional) Add progress descriptions to tool_descriptions.py
"""

# ===========================================================================
# CHANGE 1: Add Import (Top of File)
# ===========================================================================

# After existing imports, add:
from pinned_resources_tools import (
    execute_pinned_resource_tool,
    get_pinned_resource_tools,
)


# ===========================================================================
# CHANGE 2: Add Tool Definitions to get_dev_tools()
# ===========================================================================

# BEFORE:
def get_dev_tools() -> list[dict]:
    """Return development-specific tool definitions for the LLM."""
    return [
        # ... existing tools ...
        get_cloudflare_tool_definition(),
    ]

# AFTER:
def get_dev_tools() -> list[dict]:
    """Return development-specific tool definitions for the LLM."""
    tools = [
        # ... existing tools ...
        get_cloudflare_tool_definition(),
    ]
    # Add pinned resource management tools
    tools.extend(get_pinned_resource_tools())
    return tools


# ===========================================================================
# CHANGE 3: Add Tool Execution to execute_dev_tool()
# ===========================================================================

# BEFORE:
async def execute_dev_tool(tool_name: str, args: dict) -> str:
    """Execute a development-specific tool."""

    if tool_name == "deploy_file":
        # ... existing code ...
    
    # ... other tools ...
    
    elif tool_name == "cloudflare":
        action = args.get("action", "")
        if not action:
            return "Error: 'action' is required for cloudflare tool"
        return await execute_cloudflare_tool(action, args)

    return f"Unknown tool: {tool_name}"


# AFTER:
async def execute_dev_tool(tool_name: str, args: dict, channel=None) -> str:
    """Execute a development-specific tool."""

    if tool_name == "deploy_file":
        # ... existing code ...
    
    # ... other tools ...
    
    elif tool_name == "cloudflare":
        action = args.get("action", "")
        if not action:
            return "Error: 'action' is required for cloudflare tool"
        return await execute_cloudflare_tool(action, args)
    
    # Add pinned resource tool execution
    elif tool_name in ["pin_resource", "unpin_resource", "list_pinned"]:
        if not channel:
            return json.dumps({
                "success": False,
                "error": "Channel is required for pinned resource tools",
            })
        return await execute_pinned_resource_tool(tool_name, args, channel)

    return f"Unknown tool: {tool_name}"


# ===========================================================================
# CHANGE 4: Update Tool Execution Call Sites
# ===========================================================================

# Find all places where execute_dev_tool() is called and add the channel parameter:

# BEFORE:
# result = await execute_dev_tool(tool_name, tool_args)

# AFTER:
# result = await execute_dev_tool(tool_name, tool_args, channel=message.channel)

# Common locations:
# - In the agent loop where tools are executed
# - In tool call processing functions
# - In streaming response handlers


# ===========================================================================
# CHANGE 5: (Optional) Add Progress Descriptions
# ===========================================================================

# In tool_descriptions.py, add to describe_tool_call():

def describe_tool_call(tool_name: str, tool_args: dict) -> str:
    """
    Translate a tool name + arguments into a brief, human-readable description
    for live progress display in Discord.
    """

    # ... existing tool descriptions ...

    # Add pinned resource tool descriptions
    if tool_name == "pin_resource":
        title = tool_args.get("title", "?")
        # Truncate for display
        if len(title) > 50:
            title = title[:50] + "..."
        return f"📌 Pinning resource: {title}"

    if tool_name == "unpin_resource":
        msg_id = tool_args.get("message_id", "?")
        # Show last 8 digits for brevity
        if len(msg_id) > 8:
            msg_id = "..." + msg_id[-8:]
        return f"📌 Unpinning resource: {msg_id}"

    if tool_name == "list_pinned":
        return "📌 Listing pinned resources"

    # ... rest of function ...


# ===========================================================================
# Example: Full Integration in run_agent_loop()
# ===========================================================================

async def run_agent_loop(
    message: discord.Message,
    user_input: str,
    mcp_client: MCPClient,
    progress: AgentProgressView,
) -> str:
    """
    Simplified example showing pinned resource tool integration.
    """
    
    # Get all tools (now includes pinned resource tools)
    tools = get_dev_tools()
    
    # ... build messages, call OpenAI ...
    
    # Process tool calls
    for tool_call in tool_calls:
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])
        
        # Execute tool (pass channel for pinned resource tools)
        result = await execute_dev_tool(
            tool_name,
            tool_args,
            channel=message.channel,  # Add this parameter
        )
        
        # ... add result to conversation ...


# ===========================================================================
# Testing After Integration
# ===========================================================================

# 1. Restart the bot
# sudo systemctl restart architect-bot.service

# 2. Send a test command in Discord
# "Pin a resource titled 'Test' with description 'This is a test'"

# 3. Verify the resource was pinned
# "List all pinned resources"

# 4. Clean up
# "Unpin the resource with ID <message_id>"


# ===========================================================================
# Rollback Instructions
# ===========================================================================

# If something goes wrong, revert the changes:

# 1. Remove the import
# 2. Remove tools.extend(get_pinned_resource_tools()) from get_dev_tools()
# 3. Remove the pinned resource tool handling from execute_dev_tool()
# 4. Remove the channel parameter from execute_dev_tool() signature
# 5. Restart the bot

# Backup the original file before making changes:
# cp /opt/Project-Tango/scripts/architect-bot.py \
#    /opt/Project-Tango/scripts/architect-bot.py.bak.$(date +%Y%m%d-%H%M%S)
