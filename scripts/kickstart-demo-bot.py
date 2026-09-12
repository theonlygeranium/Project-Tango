#!/usr/bin/env python3
"""
Kickstart Demo Bot - Discord to Slack Bridge
==============================================
Monitors the kickstart-demo Discord channel and provides a button/command
to send the Writer Event Feedback Summary to Slack #demo-cape-webinars.

Features:
- Persistent button in channel for one-click sending
- Slash command: /send-feedback
- Natural language: "send feedback summary to slack"
- Command: !send-feedback

Author: Cursor Agent
Created: 2026-08-19
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from discord_to_slack_automation import (
    FeedbackSummaryView,
    send_feedback_summary_to_slack,
    KICKSTART_DEMO_CHANNEL_ID,
    DEMO_CAPE_WEBINARS_CHANNEL_ID
)

# Try to import MCP client
try:
    from mcp_client import MCPClient
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logging.warning("MCP client not available - Slack integration will be disabled")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_FILE = "/var/log/kickstart-demo-bot.log"

# Discord bot token from environment
BOT_TOKEN = os.environ.get("KICKSTART_DEMO_BOT_TOKEN")
if not BOT_TOKEN:
    # Fall back to Admiral Schubert token for testing
    BOT_TOKEN = os.environ.get("SCHUBERT_BOT_TOKEN")

# Admin user who can manage the bot
ADMIN_USER_ID = int(os.environ.get("DISCORD_ADMIN_USER_ID", "1075596247966167131"))


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------

def setup_logging():
    """Configure logging to file and console."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )

setup_logging()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bot Setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# MCP Client (initialized in on_ready)
mcp_client = None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    """Bot startup handler."""
    global mcp_client
    
    log.info(f"Bot connected as {bot.user} (ID: {bot.user.id})")
    log.info(f"Monitoring channel: {KICKSTART_DEMO_CHANNEL_ID}")
    log.info(f"Target Slack channel: {DEMO_CAPE_WEBINARS_CHANNEL_ID}")
    
    # Initialize MCP client for Slack integration
    if MCP_AVAILABLE:
        try:
            mcp_client = MCPClient()
            await mcp_client.connect_to_all_servers()
            log.info("MCP client initialized - Slack integration active")
        except Exception as e:
            log.error(f"Failed to initialize MCP client: {e}")
            mcp_client = None
    else:
        log.warning("MCP not available - Slack integration disabled")
    
    # Post persistent button in kickstart-demo channel
    await post_button_if_needed()


async def post_button_if_needed():
    """Post the persistent button in kickstart-demo channel if not already there."""
    try:
        channel = bot.get_channel(KICKSTART_DEMO_CHANNEL_ID)
        if not channel:
            log.error(f"Could not find channel {KICKSTART_DEMO_CHANNEL_ID}")
            return
        
        # Check if button message already exists (look for recent messages from bot)
        async for message in channel.history(limit=50):
            if message.author.id == bot.user.id and message.embeds:
                if "Writer Event Feedback Summary" in message.embeds[0].title:
                    log.info("Button message already exists, skipping")
                    return
        
        # Post new button message
        view = FeedbackSummaryView(mcp_client)
        
        embed = discord.Embed(
            title="📊 Writer Event Feedback Summary → Slack",
            description=(
                "Click the button below to send the comprehensive Writer Event "
                "Feedback Summary to Slack **#demo-cape-webinars**.\n\n"
                "This will post the full report with all metrics, insights, and action items.\n\n"
                "**Alternative methods:**\n"
                "• Command: `!send-feedback`\n"
                "• Natural language: \"send feedback summary to slack\""
            ),
            color=0x9B59B6  # Purple
        )
        embed.set_footer(text="Button remains active • Kickstart Demo Bot")
        
        await channel.send(embed=embed, view=view)
        log.info("Posted button message to kickstart-demo channel")
        
    except Exception as e:
        log.error(f"Failed to post button: {e}")


@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages."""
    # Ignore bot's own messages
    if message.author.id == bot.user.id:
        return
    
    # Only respond in kickstart-demo channel
    if message.channel.id != KICKSTART_DEMO_CHANNEL_ID:
        return
    
    # Check for natural language requests
    content_lower = message.content.lower()
    if any(phrase in content_lower for phrase in [
        "send feedback summary",
        "send the feedback",
        "post feedback to slack",
        "share feedback summary"
    ]):
        await message.reply("⏸️ Slack notifications have been disabled. This function is currently inactive.")
        return
    
    # Process commands
    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@bot.command(name="send-feedback")
async def send_feedback_command(ctx: commands.Context):
    """Send Writer Event Feedback Summary to Slack #demo-cape-webinars."""
    # Only allow in kickstart-demo channel
    if ctx.channel.id != KICKSTART_DEMO_CHANNEL_ID:
        await ctx.reply("❌ This command only works in the kickstart-demo channel.")
        return
    
    log.info(f"Command invoked by {ctx.author.name}")
    
    async with ctx.typing():
        result = await send_feedback_summary_to_slack(mcp_client)
    
    if result["success"]:
        await ctx.reply(
            "✅ Writer Event Feedback Summary sent to Slack **#demo-cape-webinars**!"
        )
    else:
        await ctx.reply(
            f"❌ Failed to send to Slack: {result.get('error', 'Unknown error')}"
        )


@bot.command(name="repost-button")
@commands.has_permissions(administrator=True)
async def repost_button_command(ctx: commands.Context):
    """Repost the feedback summary button (admin only)."""
    await post_button_if_needed()
    await ctx.reply("✅ Button reposted (or already exists)")


@bot.command(name="status")
async def status_command(ctx: commands.Context):
    """Show bot status and configuration."""
    status_embed = discord.Embed(
        title="🤖 Kickstart Demo Bot Status",
        color=0x42DED1  # Teal
    )
    
    status_embed.add_field(
        name="📺 Monitoring",
        value=f"<#{KICKSTART_DEMO_CHANNEL_ID}>",
        inline=True
    )
    
    status_embed.add_field(
        name="🎯 Target",
        value=f"Slack #demo-cape-webinars",
        inline=True
    )
    
    mcp_status = "✅ Active" if mcp_client else "❌ Unavailable"
    status_embed.add_field(
        name="🔌 Slack Integration",
        value=mcp_status,
        inline=True
    )
    
    status_embed.add_field(
        name="📚 Available Commands",
        value=(
            "• `!send-feedback` - Send summary to Slack\n"
            "• `!status` - Show this status\n"
            "• `!repost-button` - Repost button (admin)"
        ),
        inline=False
    )
    
    await ctx.reply(embed=status_embed)


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Handle command errors."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        # Ignore unknown commands
        pass
    else:
        log.error(f"Command error: {error}")
        await ctx.reply(f"❌ An error occurred: {str(error)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Run the bot."""
    if not BOT_TOKEN:
        log.error("No bot token configured!")
        log.error("Set KICKSTART_DEMO_BOT_TOKEN or SCHUBERT_BOT_TOKEN in environment")
        sys.exit(1)
    
    log.info("Starting Kickstart Demo Bot...")
    log.info(f"Log file: {LOG_FILE}")
    
    try:
        bot.run(BOT_TOKEN)
    except KeyboardInterrupt:
        log.info("Bot stopped by user")
    except Exception as e:
        log.error(f"Bot crashed: {e}")
        raise


if __name__ == "__main__":
    main()
