#!/usr/bin/env python3
"""
Simple Discord Slash Command Bot - Send Feedback to Slack
==========================================================
Lightweight bot that provides a /send-feedback slash command
that can be used from ANY Discord channel.

This bot has minimal permissions and only provides the feedback sending functionality.

Author: Cursor Agent
Created: 2026-08-19
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Try to import MCP client
try:
    from mcp_client import MCPClient
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logging.warning("MCP client not available")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_FILE = "/var/log/feedback-slash-bot.log"

# Bot token from environment (use SCHUBERT_BOT_TOKEN for now)
BOT_TOKEN = os.environ.get("SCHUBERT_BOT_TOKEN")

# Slack channel ID
SLACK_CHANNEL_ID = "C0BR92E39PW"  # demo-cape-webinars

# The feedback message
FEEDBACK_MESSAGE = """# 📊 Writer Event Feedback Summary

_30 responses · Dec 7, 2025 – Feb 3, 2026 · 10 events_

## 🔍 At a Glance

| Metric | Value |
|---|---|
| ⭐ Avg Overall Rating | 4.50 / 5 |
| 💯 Avg NPS Score | 8.97 / 10 |
| 📈 NPS Score | +60 |
| 🚀 Ready to implement ≤30 days | 90% (27/30) |
| ⚠️ Outlier low scores (1–2) | None (lowest = 3) |

## ✨ What's Working — top positive themes

1. 🔗 Integration with existing tools (Slack, Gmail) — 8 mentions
2. ⚙️ Can see 5+ workflows to automate — 8 mentions
3. 📒 Playbooks concept > just chatting with AI — 6 mentions
4. 💪 More powerful than ChatGPT/Copilot — 6 mentions
5. 🎙️ Voice/brand consistency for regulated industries — 6 mentions

_(Also: ⏱️ Save 10+ hrs/week (5), 🧠 Knowledge Graphs (5), 🛠️ Practical examples (5), 🎬 Live demo (5))_

## 🛠️ What Needs Improvement

| Signal | Count |
|---|---|
| 🐢 Pacing / session too fast | 3 |
| 🌀 Breakout rooms chaotic | 3 |
| 🔒 Security & compliance coverage | 3 |
| 📊 ROI / before-after metrics | 2 |
| 🧪 Hands-on practice environment | 2 |
| 🏥 Industry-specific examples | 1 |
| ❓ More Q&A time | 1 |
| 🔌 Deeper Connectors coverage | 1 |

_(13 of 30 said "no major concerns" ✅)_

## 🎯 Top Use Cases Requested

| Use Case | Count |
|---|---|
| 📝 Meeting summaries | 11 |
| 🧲 Lead enrichment | 11 |
| 📋 Customer case studies | 10 |
| 📆 Event recap automation | 9 |
| ⚔️ Competitive analysis | 7 |
| 📑 RFP responses | 6 |
| ✍️ Proposal generation | 6 |
| 📧 Sales email personalization | 6 |
| 🚀 Product launch materials | 6 |
| 📢 Marketing campaign briefs | 6 |

## 🚧 Top Barriers to Adoption

| Barrier | Count |
|---|---|
| 📊 Want to see more ROI data | 8 |
| 👔 Need executive buy-in | 6 |
| 💰 Need to understand pricing | 5 |
| ✅ No barriers, ready to go | 5 |
| 🧪 Test with our workflows | 4 |
| 🔐 Waiting on IT/Security review | 2 |

## 🎯 Action Items — Sales

- 📄 Build an ROI one-pager with before/after metrics (addresses the #1 barrier — 8 mentions)
- 💵 Create pricing & packaging FAQ to share with evaluators (5 pricing asks)
- 🤝 Stand up a champion enablement deck for securing executive buy-in (6 mentions)
- 🔐 Prepare a security & compliance brief (3 explicit asks + 2 in IT/Security review)
- 🧪 Offer a guided hands-on sandbox / follow-up advanced session (2 practice + 1 advanced ask)
- 📞 Prioritize outreach to hot accounts (see pipeline below)

## 📣 Action Items — Marketing

- 🎯 Lead campaigns with the top use cases: Meeting summaries, Lead enrichment, Customer case studies
- 🎬 Capture the live-demo "campaign brief in real-time" moment as a reusable video asset (5 mentions)
- ⚔️ Build competitive battlecards vs. ChatGPT/Copilot (6 "more powerful" mentions)
- 🏭 Develop industry-specific examples (healthcare flagged)
- ⏱️ Tighten breakout-room logistics & extend sessions to 2.5 hrs (pacing feedback)
- 🎙️ Showcase voice/brand consistency for regulated-industry prospects (6 mentions)

## 📈 Follow-Up Pipeline

| Follow-Up Type | Count |
|---|---|
| 🕐 Office hours | 11 |
| 📚 Send resources/docs | 7 |
| 📅 Schedule follow-up demo | 3 |
| 🤔 Still evaluating | 4 |
| 🚫 No follow-up needed | 5 |

🔥 **Top hot accounts** (strong buying intent / enterprise pricing / "move fast"):
Datadog, Snowflake, Asana, Box, Slack, Atlassian, Workday, Twilio, Monday.com, Stripe

_Footer: 30 total responses across 10 events, Dec 7, 2025 – Feb 3, 2026._

---

## 💡 3 Most Important Insights

1️⃣ **Demand is strong and near-term** — 90% ready to implement within 30 days, NPS +60, no outlier low scores.
2️⃣ **ROI data is the #1 barrier** (8 mentions) — prospects need quantified before/after proof to buy.
3️⃣ **Meeting summaries & lead enrichment are the gateway use cases** (11 mentions each) — the best hooks for Sales and Marketing.

## 🏁 Single Highest-Priority Next Action

Produce an ROI one-pager with before/after metrics from existing customers and arm Sales with it immediately — it unblocks the top barrier and the largest share of warm leads."""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    """Configure logging."""
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

class FeedbackBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.mcp_client = None

    async def setup_hook(self):
        """Called when bot is ready to sync commands."""
        await self.tree.sync()
        log.info("Slash commands synced")


bot = FeedbackBot()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    """Bot startup."""
    log.info(f"Bot connected as {bot.user}")
    log.info(f"Slash command /send-feedback available in ALL channels")
    
    # Initialize MCP client
    if MCP_AVAILABLE:
        try:
            bot.mcp_client = MCPClient()
            await bot.mcp_client.connect_to_all_servers()
            log.info("MCP client connected - Slack integration active")
        except Exception as e:
            log.error(f"MCP client failed: {e}")


# ---------------------------------------------------------------------------
# Slash Commands
# ---------------------------------------------------------------------------

@bot.tree.command(
    name="send-feedback",
    description="Send Writer Event Feedback Summary to Slack #demo-cape-webinars"
)
async def send_feedback(interaction: discord.Interaction):
    """Send the feedback summary to Slack."""
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(
        "⏸️ Slack notifications have been disabled. This command is currently inactive.",
        ephemeral=True
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Run the bot."""
    if not BOT_TOKEN:
        log.error("No bot token configured!")
        sys.exit(1)
    
    log.info("Starting Feedback Slash Command Bot...")
    
    try:
        bot.run(BOT_TOKEN)
    except KeyboardInterrupt:
        log.info("Bot stopped")
    except Exception as e:
        log.error(f"Bot crashed: {e}")
        raise


if __name__ == "__main__":
    main()
