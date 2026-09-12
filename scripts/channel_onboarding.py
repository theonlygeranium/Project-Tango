"""
Channel Onboarding System — Discord Bot Channel Setup
======================================================

Provides automated channel onboarding for each specialized bot:
- Sets channel topic with bot context
- Pins overview, commands, and tips embeds
- Replaces old onboarding pins on restart
- Handles permission errors gracefully

Usage:
    from channel_onboarding import onboard_channel
    
    BOT_CHANNEL_CONFIG = {
        "topic": "Channel topic here (max 1024 chars)",
        "bot_name": "Bot Name",
        "role": "Bot Role",
        "description": "Bot description for overview embed",
        "commands": [
            {"name": "!command", "description": "What it does"},
        ],
        "tips": ["Tip 1", "Tip 2"],
    }
    
    try:
        await onboard_channel(bot, BOT_CHANNEL_ID, BOT_CHANNEL_CONFIG, replace_existing=True)
    except Exception as e:
        log(f"Channel onboarding failed: {e}", "WARN")
"""

from __future__ import annotations

import discord
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord import Client, TextChannel


# Embed colors (matching ui_components.py)
COLOR_OVERVIEW = 0x9B59B6   # Purple
COLOR_COMMANDS = 0x42DED1   # Teal
COLOR_TIPS = 0xFF825C       # Orange


def build_overview_embed(bot_name: str, role: str, description: str) -> discord.Embed:
    """
    Build the overview embed with bot identity and purpose.
    
    Args:
        bot_name: Display name of the bot (e.g., "Admiral Schubert")
        role: Brief role description (e.g., "Server-Wide Autonomous Agent")
        description: Detailed description of the bot's purpose
    
    Returns:
        Discord embed with bot overview
    """
    embed = discord.Embed(
        title=f"⚓ {bot_name}",
        description=description,
        color=COLOR_OVERVIEW,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="Role",
        value=role,
        inline=False,
    )
    embed.set_footer(text="Channel onboarding • Overview")
    return embed


def build_commands_embed(commands: list[dict]) -> discord.Embed:
    """
    Build the commands reference embed.
    
    Args:
        commands: List of dicts with "name" and "description" keys
                  Example: [{"name": "!status", "description": "Server health snapshot"}]
    
    Returns:
        Discord embed with command reference
    """
    embed = discord.Embed(
        title="📋 Commands",
        description="Available commands for this bot:",
        color=COLOR_COMMANDS,
        timestamp=datetime.now(timezone.utc),
    )
    
    if not commands:
        embed.description = "No commands available. Use natural language to interact."
    else:
        for cmd in commands:
            name = cmd.get("name", "Unknown")
            desc = cmd.get("description", "No description")
            embed.add_field(
                name=name,
                value=desc,
                inline=False,
            )
    
    embed.set_footer(text="Channel onboarding • Commands")
    return embed


def build_tips_embed(tips: list[str]) -> discord.Embed:
    """
    Build the usage tips embed.
    
    Args:
        tips: List of tip strings
    
    Returns:
        Discord embed with usage tips
    """
    embed = discord.Embed(
        title="💡 Tips & Best Practices",
        color=COLOR_TIPS,
        timestamp=datetime.now(timezone.utc),
    )
    
    if not tips:
        embed.description = "No tips available yet."
    else:
        tips_text = "\n".join(f"• {tip}" for tip in tips)
        embed.description = tips_text
    
    embed.set_footer(text="Channel onboarding • Tips")
    return embed


async def onboard_channel(
    bot: Client,
    channel_id: int,
    config: dict,
    replace_existing: bool = True,
) -> None:
    """
    Main channel onboarding orchestrator.
    
    Sets channel topic, removes old onboarding pins, sends and pins
    the three onboarding embeds (overview, commands, tips).
    
    Args:
        bot: Discord bot client instance
        channel_id: Channel ID to onboard
        config: Configuration dict with keys:
            - topic: str — Channel topic (max 1024 chars)
            - bot_name: str — Bot display name
            - role: str — Bot role description
            - description: str — Bot description for overview embed
            - commands: list[dict] — Command reference (name, description)
            - tips: list[str] — Usage tips
        replace_existing: If True, removes old onboarding pins before adding new ones
    
    Raises:
        discord.Forbidden: If bot lacks MANAGE_CHANNELS or MANAGE_MESSAGES permissions
        discord.HTTPException: On other Discord API errors
    """
    try:
        channel = bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            raise ValueError(f"Channel {channel_id} not found or not a text channel")
        
        # 1. Set channel topic
        topic = config.get("topic", "")[:1024]  # Discord topic max length
        if topic:
            try:
                await channel.edit(topic=topic)
            except discord.Forbidden:
                # Log but don't fail — topic is optional
                print(f"[WARN] Missing MANAGE_CHANNELS permission for topic on channel {channel_id}")
        
        # 2. Remove old onboarding pins if replace_existing=True
        if replace_existing:
            try:
                pins = await channel.pins()
                for pin in pins:
                    # Check if this is an onboarding pin by footer text
                    if pin.embeds:
                        for embed in pin.embeds:
                            footer = embed.footer.text if embed.footer else ""
                            if "onboarding" in footer.lower():
                                await pin.unpin()
                                break
            except discord.Forbidden:
                # Log but don't fail — unpinning is optional
                print(f"[WARN] Missing MANAGE_MESSAGES permission for unpinning on channel {channel_id}")
        
        # 3. Build embeds
        overview_embed = build_overview_embed(
            bot_name=config.get("bot_name", "Bot"),
            role=config.get("role", ""),
            description=config.get("description", ""),
        )
        commands_embed = build_commands_embed(config.get("commands", []))
        tips_embed = build_tips_embed(config.get("tips", []))
        
        # 4. Send and pin embeds (silent=True to avoid notification spam)
        embeds = [overview_embed, commands_embed, tips_embed]
        for embed in embeds:
            try:
                msg = await channel.send(embed=embed, silent=True)
                await msg.pin()
            except discord.Forbidden as e:
                raise discord.Forbidden(
                    f"Missing MANAGE_MESSAGES permission to pin on channel {channel_id}"
                ) from e
    
    except discord.Forbidden as e:
        # Re-raise permission errors for caller to handle
        raise
    except Exception as e:
        # Wrap other exceptions
        raise RuntimeError(f"Channel onboarding failed for {channel_id}: {e}") from e
