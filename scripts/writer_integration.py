#!/usr/bin/env python3
"""
WRITER Agent Playbook Integration for Discord Bots

Provides high-level functions for Discord bots to invoke WRITER playbooks
and receive responses. Handles auto-detection of when to trigger playbooks
based on message content.

Usage in Discord bot:
    from writer_integration import should_invoke_playbook, invoke_playbook_from_discord
    
    if should_invoke_playbook(message.content, "cursor-litellm"):
        result = await invoke_playbook_from_discord(
            playbook_name="cursor-litellm",
            discord_channel_id=message.channel.id,
            user_message=message.content
        )
"""

import os
import re
import logging
import discord
import asyncio
from typing import Optional, Dict, Any
from writer_playbook_client import WriterPlaybookClient, PlaybookResult

logger = logging.getLogger(__name__)

# Playbook configurations
PLAYBOOKS = {
    "cursor-litellm": {
        "name": "Cursor LiteLLM Session Provisioning",
        "webhook_url": "https://app.writer.com/webhook/triggers/playbook/1574c302-b407-4553-a2f6-6e42291e805c",
        "api_key": os.getenv("WRITER_PLAYBOOK_API_KEY", ""),
        "description": "Provision and diagnose Cursor LiteLLM BYOK integration",
        "triggers": [
            # Auto-detection patterns (case-insensitive)
            r"\bcursor.*litellm\b",
            r"\blitellm.*cursor\b",
            r"\blitellm.*error\b",
            r"\bcursor.*agent.*error\b",
            r"\bcursor.*byok\b",
            r"\bpolyglot.*litellm\b",
            r"\bwriter.*cursor.*integration\b",
            r"\bcursor.*model.*loading\b",
            r"\bcursor.*not.*working\b",
            r"\blitellm.*service\b",
            r"\bcursor.*api.*key\b",
            r"\bcursor.*models.*missing\b",
            # Explicit commands
            r"run.*cursor.*litellm.*playbook",
            r"invoke.*cursor.*litellm",
            r"diagnose.*cursor",
            r"check.*cursor.*litellm",
            r"provision.*cursor.*session",
        ],
        "timeout": 1800,  # 30 minutes
    }
}


def should_invoke_playbook(message: str, playbook_name: str) -> bool:
    """
    Auto-detect if a message should trigger a WRITER playbook.
    
    Args:
        message: User message content
        playbook_name: Name of the playbook to check (e.g., "cursor-litellm")
    
    Returns:
        True if the message matches any trigger patterns
    """
    playbook = PLAYBOOKS.get(playbook_name)
    if not playbook:
        logger.warning(f"Unknown playbook: {playbook_name}")
        return False
    
    message_lower = message.lower()
    
    for pattern in playbook["triggers"]:
        if re.search(pattern, message_lower):
            logger.info(f"Message matched playbook trigger: {pattern}")
            return True
    
    return False


async def invoke_playbook_from_discord(
    playbook_name: str,
    discord_channel: discord.TextChannel,
    user_message: str,
    progress_updates: bool = True,
    thread_tracker: dict = None,  # Pass in _playbook_threads from architect-bot
    continue_thread_id: Optional[str] = None  # For follow-ups
) -> Optional[PlaybookResult]:
    """
    Invoke a WRITER playbook from Discord and post results back to the channel.
    
    Args:
        playbook_name: Name of the playbook (e.g., "cursor-litellm")
        discord_channel: Discord channel to post updates and results
        user_message: Original user message that triggered the playbook
        progress_updates: If True, post progress updates to Discord
        thread_tracker: Dict to store message_id -> thread_id mapping for follow-ups
        continue_thread_id: If provided, continues an existing WRITER thread
    
    Returns:
        PlaybookResult or None if invocation failed
    """
    playbook = PLAYBOOKS.get(playbook_name)
    if not playbook:
        await discord_channel.send(f"❌ Unknown playbook: `{playbook_name}`")
        return None
    
    # Check API key is configured
    api_key = playbook["api_key"]
    if not api_key:
        await discord_channel.send(
            f"❌ WRITER playbook API key not configured. "
            f"Set `WRITER_PLAYBOOK_API_KEY` in `.env`"
        )
        return None
    
    # Send initial status message
    if continue_thread_id:
        status_msg_content = (
            f"🔄 **Continuing WRITER Agent Conversation**\n"
            f"📋 {playbook['name']}\n"
            f"🧵 Thread: `{continue_thread_id[:16]}...`\n"
            f"💬 Your follow-up: {user_message[:100]}{'...' if len(user_message) > 100 else ''}"
        )
    else:
        status_msg_content = (
            f"⏳ **Invoking WRITER Agent Playbook**\n"
            f"📋 {playbook['name']}\n"
            f"🔄 Starting playbook execution..."
        )
    
    logger.info(f"Sending initial status message to Discord channel {discord_channel.id}")
    try:
        status_message = await discord_channel.send(status_msg_content)
        logger.info(f"Initial status message sent: {status_message.id}")
    except Exception as e:
        logger.error(f"Failed to send initial status message: {e}")
        return None
    
    # Progress callback to update Discord
    last_status_update = asyncio.get_event_loop().time()
    
    async def on_progress(status: str, attempt: int, max_attempts: int):
        nonlocal last_status_update
        
        if not progress_updates:
            return
        
        # Rate-limit updates to once per 10 seconds
        now = asyncio.get_event_loop().time()
        if now - last_status_update < 10:
            return
        
        last_status_update = now
        
        # Map status to emoji
        status_emoji = {
            "triggered": "🚀",
            "running": "⚙️",
            "processing": "🔄",
            "completed": "✅",
            "failed": "❌",
        }.get(status, "⏳")
        
        try:
            await status_message.edit(
                content=f"⏳ **Invoking WRITER Agent Playbook**\n"
                        f"📋 {playbook['name']}\n"
                        f"{status_emoji} Status: `{status}` ({attempt}/{max_attempts} polls)"
            )
        except discord.errors.NotFound:
            logger.warning("Status message was deleted, cannot update")
        except Exception as e:
            logger.error(f"Failed to update status message: {e}")
    
    # Invoke the playbook
    logger.info(f"Invoking playbook: {playbook_name}{' (continue thread)' if continue_thread_id else ''}")
    try:
        async with WriterPlaybookClient(
            webhook_url=playbook["webhook_url"],
            api_key=api_key
        ) as client:
            logger.info("WriterPlaybookClient context manager entered")
            result = await client.invoke_playbook(
                inputs=[],  # This playbook takes no inputs
                timeout=playbook["timeout"],
                progress_callback=on_progress,
                continue_thread_id=continue_thread_id
            )
            logger.info(f"Playbook invocation complete: status={result.status}, thread_id={result.thread_id}")
    except asyncio.TimeoutError as e:
        logger.error(f"Playbook timeout: {e}")
        await status_message.edit(
            content=f"⏳ **WRITER Agent Playbook**\n"
                    f"📋 {playbook['name']}\n"
                    f"⚠️ **Timeout**: Playbook exceeded {playbook['timeout']}s limit\n"
                    f"```\n{str(e)}\n```"
        )
        return None
    except Exception as e:
        logger.exception(f"Playbook invocation failed: {e}")
        await status_message.edit(
            content=f"⏳ **WRITER Agent Playbook**\n"
                    f"📋 {playbook['name']}\n"
                    f"❌ **Error**: {str(e)}"
        )
        return None
    
    # Format and post the result
    logger.info(f"Posting playbook result to Discord: status={result.status}")
    result_message_id = await _post_playbook_result(discord_channel, status_message, playbook, result)
    logger.info("Playbook result posted successfully")
    
    # Track thread ID for follow-ups
    if thread_tracker is not None and result_message_id:
        thread_tracker[result_message_id] = result.thread_id
        logger.info(f"Tracked thread {result.thread_id} for follow-ups on message {result_message_id}")
    
    return result


async def _post_playbook_result(
    channel: discord.TextChannel,
    status_message: discord.Message,
    playbook: Dict[str, Any],
    result: PlaybookResult
) -> Optional[int]:
    """
    Format and post the playbook result to Discord
    
    Returns:
        Message ID of the result message (for thread tracking)
    """
    
    # Build result embed
    if result.success:
        embed_color = discord.Color.green()
        status_emoji = "✅"
        status_text = "Completed Successfully"
    elif result.needs_user_input:
        embed_color = discord.Color.gold()
        status_emoji = "⏸️"
        status_text = "Awaiting User Response"
    else:
        embed_color = discord.Color.red()
        status_emoji = "❌"
        status_text = "Failed"
    
    embed = discord.Embed(
        title=f"{status_emoji} {playbook['name']}",
        description=status_text,
        color=embed_color
    )
    
    # Add metadata
    embed.add_field(
        name="Thread ID",
        value=f"`{result.thread_id}`",
        inline=True
    )
    
    embed.add_field(
        name="Execution Time",
        value=f"{result.execution_time_seconds:.1f}s",
        inline=True
    )
    
    embed.add_field(
        name="Status",
        value=f"`{result.status}`",
        inline=True
    )
    
    # Add deliverables if present
    if result.deliverables:
        deliverables_text = _format_deliverables(result.deliverables)
        
        # Discord has limits: 2000 chars per message, 1024 per field, 6000 total per embed
        # Split into multiple messages if needed
        MAX_DISCORD_MESSAGE = 1900  # Leave room for formatting
        
        if len(deliverables_text) > MAX_DISCORD_MESSAGE:
            # Post embed first
            await status_message.edit(content="**WRITER Agent Playbook Result**", embed=embed)
            
            # Post output in separate messages as code blocks
            chunks = _split_text(deliverables_text, MAX_DISCORD_MESSAGE)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await channel.send(f"**Output** (part {i+1}/{len(chunks)}):\n{chunk}")
                else:
                    await channel.send(f"**Output** (part {i+1}/{len(chunks)} continued):\n{chunk}")
        else:
            # Short enough to fit in embed description
            embed.description = f"{status_text}\n\n**Output:**\n{deliverables_text}"
            await status_message.edit(content="**WRITER Agent Playbook Result**", embed=embed)
    else:
        # No deliverables, just update with embed
        await status_message.edit(content="**WRITER Agent Playbook Result**", embed=embed)
    
    # Add error if present
    if result.error_message:
        error_embed = discord.Embed(
            title="⚠️ Note",
            description=result.error_message,
            color=discord.Color.orange()
        )
        await channel.send(embed=error_embed)
    
    # Return the message ID for thread tracking
    return status_message.id


def _format_deliverables(deliverables: Dict[str, Any]) -> str:
    """Format playbook deliverables for Discord display"""
    
    # If deliverables is a simple dict, format as key-value pairs
    if isinstance(deliverables, dict):
        # Check for common WRITER playbook output formats
        
        # Format 1: Text output
        if "type" in deliverables and deliverables["type"] == "text":
            content = deliverables.get("content", str(deliverables))
            # Remove excessive newlines and clean up
            content = content.strip()
            return content
        
        # Format 2: Structured output
        lines = []
        for key, value in deliverables.items():
            if isinstance(value, (dict, list)):
                import json
                value_str = json.dumps(value, indent=2)
            else:
                value_str = str(value)
            
            lines.append(f"{key}: {value_str}")
        
        return "\n".join(lines)
    
    # Fallback: convert to string
    return str(deliverables)


def _split_text(text: str, max_length: int) -> list[str]:
    """Split text into chunks that fit Discord's message limits"""
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    # Split by lines to avoid breaking mid-line
    lines = text.split('\n')
    
    for line in lines:
        # If adding this line would exceed limit, start new chunk
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
        
        current_chunk += line + '\n'
    
    # Add final chunk
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return chunks


def list_available_playbooks() -> str:
    """
    Get a formatted list of available WRITER playbooks.
    
    Returns:
        Formatted string for Discord display
    """
    lines = ["**Available WRITER Agent Playbooks:**\n"]
    
    for name, config in PLAYBOOKS.items():
        lines.append(f"**{name}**")
        lines.append(f"  📋 {config['description']}")
        lines.append(f"  ⏱️ Timeout: {config['timeout']}s")
        lines.append(f"  🎯 Triggers: {len(config['triggers'])} patterns")
        lines.append("")
    
    return "\n".join(lines)


# Convenience function for The Architect
async def handle_architect_message(message: discord.Message, thread_tracker: dict = None) -> bool:
    """
    Auto-detect and handle WRITER playbook invocations in The Architect.
    
    Args:
        message: Discord message from user
        thread_tracker: Dict to store message_id -> thread_id mapping
    
    Returns:
        True if a playbook was invoked (bot should not process further)
        False if no playbook was triggered (bot should handle normally)
    """
    # Check all playbooks for auto-detection
    for playbook_name in PLAYBOOKS.keys():
        if should_invoke_playbook(message.content, playbook_name):
            logger.info(f"Auto-detected playbook trigger: {playbook_name}")
            
            # Invoke the playbook
            await invoke_playbook_from_discord(
                playbook_name=playbook_name,
                discord_channel=message.channel,
                user_message=message.content,
                progress_updates=True,
                thread_tracker=thread_tracker
            )
            
            return True  # Message was handled by playbook
    
    return False  # No playbook triggered


if __name__ == "__main__":
    # Test auto-detection
    test_messages = [
        "Can you help with Cursor LiteLLM integration?",
        "I'm getting LiteLLM errors in Cursor",
        "Run the cursor litellm playbook",
        "Check if the litellm service is working",
        "Just a normal message",
    ]
    
    print("Testing auto-detection:")
    for msg in test_messages:
        detected = should_invoke_playbook(msg, "cursor-litellm")
        print(f"  {'✓' if detected else '✗'} {msg}")
