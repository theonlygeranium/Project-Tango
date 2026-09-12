#!/usr/bin/env python3
"""
Example usage of discord_ux_utils.py module
============================================
Demonstrates how to use the shared Discord UX utilities in bot scripts.

This file is for documentation purposes only and is not meant to be executed.
"""

import asyncio
import discord
from discord_ux_utils import (
    keep_typing,
    send_silent,
    should_use_thread,
    validate_embed_limits,
    SUPPRESS_NOTIFICATIONS,
    IS_COMPONENTS_V2,
)


# ---------------------------------------------------------------------------
# Example 1: Using keep_typing for long-running operations
# ---------------------------------------------------------------------------

async def example_long_operation(channel):
    """Show typing indicator during a long agent task."""
    stop_event = asyncio.Event()
    typing_task = asyncio.create_task(
        keep_typing(channel, stop_event, interval=8.0)
    )
    
    try:
        # Perform long operation (agent reasoning, command execution, etc.)
        result = await perform_agent_task()
        await channel.send(f"Task complete: {result}")
    finally:
        # Always stop typing when done
        stop_event.set()
        await typing_task


# ---------------------------------------------------------------------------
# Example 2: Silent notifications for background tasks
# ---------------------------------------------------------------------------

async def example_background_update(channel):
    """Send a status update without pushing notifications to mobile."""
    # Regular message (sends push notification)
    await channel.send("Starting deployment...")
    
    # Do work...
    
    # Silent message (no push notification)
    await send_silent(
        channel,
        content="Deployment complete",
        embed=discord.Embed(
            title="Status",
            description="All services restarted successfully",
            color=0x2ECC71,
        ),
    )


# ---------------------------------------------------------------------------
# Example 3: Thread decision heuristic
# ---------------------------------------------------------------------------

async def example_handle_user_message(message, user_input):
    """Decide whether to create a thread for the agent task."""
    if should_use_thread(user_input):
        # Create thread for complex/long tasks
        thread = await message.create_thread(
            name=f"Agent Task {datetime.now().strftime('%H:%M')}",
            auto_archive_duration=60,
        )
        channel = thread
    else:
        # Use main channel for simple tasks
        channel = message.channel
    
    # Run agent task in the selected channel
    await run_agent_task(channel, user_input)


# ---------------------------------------------------------------------------
# Example 4: Embed validation before sending
# ---------------------------------------------------------------------------

async def example_send_status_embed(channel, status_data):
    """Build and validate a status embed before sending."""
    title = "System Health Report"
    description = "Current status of all Schubert services"
    
    fields = []
    for service, status in status_data.items():
        fields.append({
            "name": service,
            "value": f"Status: {status['state']}\nUptime: {status['uptime']}",
            "inline": True,
        })
    
    # Validate before sending
    is_valid, error = validate_embed_limits(title, description, fields)
    
    if not is_valid:
        # Handle validation failure gracefully
        await channel.send(f"⚠️ Status embed too large: {error}")
        # Could truncate or paginate here
        return
    
    # Send validated embed
    embed = discord.Embed(title=title, description=description, color=0x3498DB)
    for field in fields:
        embed.add_field(
            name=field["name"],
            value=field["value"],
            inline=field.get("inline", False),
        )
    
    await channel.send(embed=embed)


# ---------------------------------------------------------------------------
# Example 5: Using message flags directly
# ---------------------------------------------------------------------------

async def example_manual_flags(channel):
    """Manually set Discord message flags if needed."""
    # Most code should use send_silent() instead, but flags are exposed
    # for advanced use cases
    
    # Silent message with components v2
    flags = SUPPRESS_NOTIFICATIONS | IS_COMPONENTS_V2
    
    # Note: discord.py typically handles this via the silent= parameter,
    # but the constants are available if needed for raw API calls
    await channel.send(
        "Manual flag example",
        silent=True,  # Preferred: use high-level API
    )


# ---------------------------------------------------------------------------
# Example 6: Combined pattern for agent responses
# ---------------------------------------------------------------------------

async def example_full_agent_pattern(message, user_input):
    """Complete pattern combining all utilities."""
    # 1. Decide thread vs main channel
    if should_use_thread(user_input):
        thread = await message.create_thread(
            name=f"Task: {user_input[:50]}",
            auto_archive_duration=60,
        )
        channel = thread
    else:
        channel = message.channel
    
    # 2. Start typing indicator
    stop_event = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(channel, stop_event))
    
    try:
        # 3. Run agent task
        result = await run_agent_task(user_input)
        
        # 4. Build and validate response embed
        title = "Task Complete"
        description = result['summary']
        fields = [
            {"name": "Duration", "value": f"{result['duration']:.2f}s"},
            {"name": "Steps", "value": str(result['steps'])},
        ]
        
        is_valid, error = validate_embed_limits(title, description, fields)
        
        if is_valid:
            embed = discord.Embed(title=title, description=description)
            for field in fields:
                embed.add_field(name=field["name"], value=field["value"])
            await channel.send(embed=embed)
        else:
            # Fallback to plain text
            await channel.send(f"**{title}**\n{description}")
        
        # 5. Silent follow-up notification
        await send_silent(channel, content="All steps logged to audit trail")
        
    finally:
        # 6. Always stop typing
        stop_event.set()
        await typing_task
