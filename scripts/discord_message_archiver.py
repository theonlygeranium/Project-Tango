#!/usr/bin/env python3
"""
Discord Message Archiver & Bulk Deleter
=========================================
Archives all Discord messages from bot channels to JSON files, then optionally
bulk deletes messages that are less than 14 days old.

Usage:
  python3 discord_message_archiver.py --archive-only    # Archive messages only
  python3 discord_message_archiver.py --archive-delete  # Archive then bulk delete

Author: Jeff Geronimo
Date: 2026-08-18
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv("/opt/Project-Tango/.env")

# Add scripts directory to path
SCRIPT_DIR = "/opt/Project-Tango/scripts"
sys.path.insert(0, SCRIPT_DIR)

# Configuration
ARCHIVE_DIR = Path("/opt/Project-Tango/archives/discord_messages")
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# Bot token (using Admiral Schubert's token for full access)
BOT_TOKEN = os.environ.get("SCHUBERT_BOT_TOKEN", "")

# All bot channels to process
CHANNELS_TO_ARCHIVE = {
    "admiral": int(os.environ.get("SCHUBERT_BOT_CHANNEL_ID", "0")),
    "architect": int(os.environ.get("ARCHITECT_CHANNEL_ID", "0")),
    "quartermaster": int(os.environ.get("QUARTERMASTER_CHANNEL_ID", "0")),
    "cartographer": int(os.environ.get("CARTOGRAPHER_CHANNEL_ID", "0")),
    "dr-voss": int(os.environ.get("DR_VOSS_CHANNEL_ID", "0")),
    "proctor": int(os.environ.get("PROCTOR_CHANNEL_ID", "0")),
    "cortex": int(os.environ.get("CORTEX_CHANNEL_ID", "0")),
    "senior-staff-meeting": int(os.environ.get("SENIOR_STAFF_CHANNEL_ID", "0")),
    "proctor-delegation": int(os.environ.get("PROCTOR_DELEGATION_CHANNEL_ID", "0")),
    "proctor-analysis": int(os.environ.get("PROCTOR_ANALYSIS_CHANNEL_ID", "0")),
}

# 14 days cutoff for bulk deletion
BULK_DELETE_CUTOFF = datetime.now(timezone.utc) - timedelta(days=14)

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


def save_message_to_json(message: discord.Message) -> dict:
    """Convert a Discord message to a JSON-serializable dict."""
    return {
        "id": str(message.id),
        "channel_id": str(message.channel.id),
        "channel_name": message.channel.name if hasattr(message.channel, "name") else "Unknown",
        "author_id": str(message.author.id),
        "author_name": f"{message.author.name}#{message.author.discriminator}",
        "author_display_name": message.author.display_name,
        "author_is_bot": message.author.bot,
        "content": message.content,
        "timestamp": message.created_at.isoformat(),
        "edited_timestamp": message.edited_at.isoformat() if message.edited_at else None,
        "attachments": [
            {
                "id": str(att.id),
                "filename": att.filename,
                "url": att.url,
                "size": att.size,
                "content_type": att.content_type,
            }
            for att in message.attachments
        ],
        "embeds": [
            {
                "title": embed.title,
                "description": embed.description,
                "url": embed.url,
                "color": embed.color.value if embed.color else None,
                "timestamp": embed.timestamp.isoformat() if embed.timestamp else None,
                "fields": [
                    {"name": field.name, "value": field.value, "inline": field.inline}
                    for field in embed.fields
                ],
            }
            for embed in message.embeds
        ],
        "reactions": [
            {
                "emoji": str(reaction.emoji),
                "count": reaction.count,
            }
            for reaction in message.reactions
        ],
        "reference": {
            "message_id": str(message.reference.message_id),
            "channel_id": str(message.reference.channel_id),
        } if message.reference else None,
    }


async def archive_channel(channel: discord.TextChannel, channel_name: str) -> tuple[int, list[dict]]:
    """Archive all messages from a channel."""
    print(f"📥 Archiving #{channel.name} (ID: {channel.id})...")
    
    messages_data = []
    message_count = 0
    
    try:
        async for message in channel.history(limit=None, oldest_first=True):
            message_data = save_message_to_json(message)
            messages_data.append(message_data)
            message_count += 1
            
            if message_count % 100 == 0:
                print(f"   Archived {message_count} messages from #{channel.name}...")
        
        print(f"✅ Archived {message_count} messages from #{channel.name}")
        return message_count, messages_data
    
    except discord.Forbidden:
        print(f"❌ No permission to read #{channel.name}")
        return 0, []
    except Exception as e:
        print(f"❌ Error archiving #{channel.name}: {e}")
        return 0, []


async def bulk_delete_channel(channel: discord.TextChannel, channel_name: str) -> int:
    """Bulk delete messages less than 14 days old from a channel."""
    print(f"🗑️  Deleting messages from #{channel.name}...")
    
    deleted_count = 0
    
    try:
        # Get messages to delete (< 14 days old)
        messages_to_delete = []
        
        async for message in channel.history(limit=None):
            if message.created_at > BULK_DELETE_CUTOFF:
                messages_to_delete.append(message)
            else:
                # Stop when we reach messages older than 14 days
                break
        
        if not messages_to_delete:
            print(f"   No messages to delete from #{channel.name}")
            return 0
        
        print(f"   Found {len(messages_to_delete)} messages to delete from #{channel.name}")
        
        # Discord allows bulk delete of up to 100 messages at a time
        for i in range(0, len(messages_to_delete), 100):
            batch = messages_to_delete[i:i+100]
            
            if len(batch) == 1:
                # Single message deletion
                await batch[0].delete()
                deleted_count += 1
            else:
                # Bulk deletion
                await channel.delete_messages(batch)
                deleted_count += len(batch)
            
            print(f"   Deleted {deleted_count}/{len(messages_to_delete)} messages from #{channel.name}...")
            
            # Rate limiting delay
            await asyncio.sleep(1)
        
        print(f"✅ Deleted {deleted_count} messages from #{channel.name}")
        return deleted_count
    
    except discord.Forbidden:
        print(f"❌ No permission to delete messages in #{channel.name}")
        return 0
    except Exception as e:
        print(f"❌ Error deleting messages from #{channel.name}: {e}")
        return 0


@bot.event
async def on_ready():
    """Main execution when bot is ready."""
    print(f"✅ Bot logged in as {bot.user}")
    print(f"📁 Archive directory: {ARCHIVE_DIR}")
    print()
    
    # Parse command line arguments
    archive_mode = "--archive-only" in sys.argv
    delete_mode = "--archive-delete" in sys.argv
    
    if not archive_mode and not delete_mode:
        print("❌ Error: Must specify --archive-only or --archive-delete")
        await bot.close()
        return
    
    # Create timestamp for this archive
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_file = ARCHIVE_DIR / f"discord_archive_{timestamp}.json"
    
    # Archive phase
    print("=" * 70)
    print("PHASE 1: ARCHIVING MESSAGES")
    print("=" * 70)
    print()
    
    all_archives = {}
    total_messages = 0
    
    for channel_name, channel_id in CHANNELS_TO_ARCHIVE.items():
        if channel_id == 0:
            print(f"⚠️  Skipping {channel_name} (no channel ID configured)")
            continue
        
        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"⚠️  Could not find channel: {channel_name} (ID: {channel_id})")
            continue
        
        count, messages_data = await archive_channel(channel, channel_name)
        
        if count > 0:
            all_archives[channel_name] = {
                "channel_id": str(channel_id),
                "channel_name": channel.name,
                "message_count": count,
                "messages": messages_data,
            }
            total_messages += count
        
        print()
    
    # Save archive to JSON
    if all_archives:
        archive_data = {
            "archive_timestamp": timestamp,
            "archive_date": datetime.now(timezone.utc).isoformat(),
            "total_channels": len(all_archives),
            "total_messages": total_messages,
            "channels": all_archives,
        }
        
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, indent=2, ensure_ascii=False)
        
        print("=" * 70)
        print(f"✅ Archive saved: {archive_file}")
        print(f"📊 Total messages archived: {total_messages}")
        print(f"📊 Total channels archived: {len(all_archives)}")
        print("=" * 70)
        print()
    
    # Delete phase (if requested)
    if delete_mode:
        print("=" * 70)
        print("PHASE 2: BULK DELETING MESSAGES (< 14 DAYS OLD)")
        print("=" * 70)
        print()
        
        # 3-second countdown
        for i in range(3, 0, -1):
            print(f"⏳ Starting deletion in {i} seconds... (Ctrl+C to cancel)")
            await asyncio.sleep(1)
        
        print()
        
        total_deleted = 0
        
        for channel_name, channel_id in CHANNELS_TO_ARCHIVE.items():
            if channel_id == 0:
                continue
            
            channel = bot.get_channel(channel_id)
            if not channel:
                continue
            
            deleted = await bulk_delete_channel(channel, channel_name)
            total_deleted += deleted
            print()
        
        print("=" * 70)
        print(f"✅ Bulk deletion complete!")
        print(f"🗑️  Total messages deleted: {total_deleted}")
        print("=" * 70)
        print()
    
    # Create summary report
    summary_file = ARCHIVE_DIR / f"archive_summary_{timestamp}.txt"
    with open(summary_file, "w") as f:
        f.write("Discord Message Archive Summary\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Archive Date: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"Total Channels: {len(all_archives)}\n")
        f.write(f"Total Messages Archived: {total_messages}\n")
        
        if delete_mode:
            f.write(f"Total Messages Deleted: {total_deleted}\n")
            f.write(f"Bulk Delete Cutoff: {BULK_DELETE_CUTOFF.isoformat()}\n")
        
        f.write("\n" + "=" * 70 + "\n\n")
        f.write("Channels Archived:\n\n")
        
        for channel_name, data in all_archives.items():
            f.write(f"  #{data['channel_name']}\n")
            f.write(f"    Channel ID: {data['channel_id']}\n")
            f.write(f"    Messages: {data['message_count']}\n\n")
    
    print(f"📄 Summary saved: {summary_file}")
    print()
    print("✅ All operations complete!")
    
    await bot.close()


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Error: SCHUBERT_BOT_TOKEN not found in environment")
        sys.exit(1)
    
    try:
        bot.run(BOT_TOKEN)
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(0)
