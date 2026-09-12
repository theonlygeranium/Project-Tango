#!/usr/bin/env python3
"""
Discord to Slack Automation - Writer Event Feedback Summary
=============================================================
Sends a formatted Writer Event Feedback Summary from Discord (kickstart-demo channel)
to Slack (demo-cape-webinars channel) with proper Slack markdown formatting.

This can be triggered via:
- Discord button interaction
- Discord slash command
- Natural language request to bot

Author: Cursor Agent
Created: 2026-08-19
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

# Import discord at module level for class definitions
try:
    import discord
except ImportError:
    discord = None

if TYPE_CHECKING:
    from mcp_client import MCPClient


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Discord
KICKSTART_DEMO_CHANNEL_ID = 1539657495142998078

# Slack
DEMO_CAPE_WEBINARS_CHANNEL_ID = "C0BR92E39PW"

# The formatted message to send to Slack
# Using Slack mrkdwn formatting (https://api.slack.com/reference/surfaces/formatting)
WRITER_EVENT_FEEDBACK_MESSAGE = """# 📊 Writer Event Feedback Summary

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
# Core Functions
# ---------------------------------------------------------------------------

async def send_feedback_summary_to_slack(mcp_client: MCPClient) -> dict:
    """
    Send the Writer Event Feedback Summary to Slack.

    DISABLED — Slack notifications turned off to prevent messages being sent as user to work channels.

    Args:
        mcp_client: MCP client instance with Slack MCP server connected

    Returns:
        dict with success status and message
    """
    return {
        "success": False,
        "error": "Slack notifications have been disabled. This function is currently inactive."
    }


async def handle_button_click(
    interaction: discord.Interaction,
    mcp_client: MCPClient
) -> None:
    """
    Handle Discord button click to send feedback summary to Slack.
    
    Args:
        interaction: Discord interaction from button click
        mcp_client: MCP client instance
    """
    # Defer response since Slack posting might take a moment
    await interaction.response.defer(ephemeral=True)
    
    # Send to Slack
    result = await send_feedback_summary_to_slack(mcp_client)
    
    if result["success"]:
        await interaction.followup.send(
            "✅ Writer Event Feedback Summary sent to Slack #demo-cape-webinars!",
            ephemeral=True
        )
    else:
        await interaction.followup.send(
            f"❌ Failed to send to Slack: {result.get('error', 'Unknown error')}",
            ephemeral=True
        )


async def handle_command(
    message: discord.Message,
    mcp_client: MCPClient
) -> None:
    """
    Handle Discord command to send feedback summary to Slack.
    
    Args:
        message: Discord message with command
        mcp_client: MCP client instance
    """
    # Send thinking indicator
    async with message.channel.typing():
        result = await send_feedback_summary_to_slack(mcp_client)
    
    if result["success"]:
        await message.reply(
            "✅ Writer Event Feedback Summary sent to Slack #demo-cape-webinars!"
        )
    else:
        await message.reply(
            f"❌ Failed to send to Slack: {result.get('error', 'Unknown error')}"
        )


async def handle_natural_language(
    message: discord.Message,
    mcp_client: MCPClient
) -> None:
    """
    Handle natural language request from agent to send feedback summary.
    
    This is called by the bot's agent loop when it determines the user
    wants to send the feedback summary to Slack.
    
    Args:
        message: Discord message that triggered the agent
        mcp_client: MCP client instance
    
    Returns:
        None (sends response via Discord message)
    """
    result = await send_feedback_summary_to_slack(mcp_client)
    
    if result["success"]:
        await message.channel.send(
            "✅ I've sent the Writer Event Feedback Summary to Slack #demo-cape-webinars."
        )
    else:
        await message.channel.send(
            f"❌ I couldn't send to Slack: {result.get('error', 'Unknown error')}"
        )


# ---------------------------------------------------------------------------
# Button View for Discord
# ---------------------------------------------------------------------------

class FeedbackSummaryView(discord.ui.View):
    """
    Discord UI View with button to send feedback summary to Slack.
    
    Usage:
        view = FeedbackSummaryView(mcp_client)
        await channel.send(
            "📊 Click the button below to send the Writer Event Feedback Summary to Slack:",
            view=view
        )
    """
    
    def __init__(self, mcp_client: MCPClient):
        super().__init__(timeout=None)  # Button stays active indefinitely
        self.mcp_client = mcp_client
    
    @discord.ui.button(
        label="📊 Send to Slack #demo-cape-webinars",
        style=discord.ButtonStyle.primary,
        custom_id="send_feedback_to_slack"
    )
    async def send_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await handle_button_click(interaction, self.mcp_client)


async def create_button_message(
    channel: discord.TextChannel,
    mcp_client: MCPClient
) -> discord.Message:
    """
    Create a persistent button in Discord to send feedback summary to Slack.
    
    Args:
        channel: Discord channel to post button in
        mcp_client: MCP client instance
    
    Returns:
        The message with the button
    """
    view = FeedbackSummaryView(mcp_client)
    
    embed = discord.Embed(
        title="📊 Writer Event Feedback Summary",
        description=(
            "Click the button below to send the comprehensive Writer Event "
            "Feedback Summary to Slack #demo-cape-webinars.\n\n"
            "This will post the full report with all metrics, insights, and action items."
        ),
        color=0x9B59B6  # Purple
    )
    embed.set_footer(text="Button remains active indefinitely")
    
    message = await channel.send(embed=embed, view=view)
    return message


# ---------------------------------------------------------------------------
# Agent Tool for Natural Language Triggering
# ---------------------------------------------------------------------------

def get_send_feedback_tool_definition() -> dict:
    """
    OpenAI function calling tool definition for sending feedback summary.
    
    Add this to your bot's tool registry to enable natural language triggering.
    
    Returns:
        Tool definition dict
    """
    return {
        "type": "function",
        "function": {
            "name": "send_writer_feedback_to_slack",
            "description": (
                "Send the Writer Event Feedback Summary to Slack #demo-cape-webinars channel. "
                "Use this when the user asks to send the feedback summary, post to Slack, "
                "or share the Writer event results with the team."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }


async def execute_send_feedback_tool(
    message: discord.Message,
    mcp_client: MCPClient
) -> dict:
    """
    Execute the send_writer_feedback_to_slack tool.
    
    Args:
        message: Discord message that triggered the tool
        mcp_client: MCP client instance
    
    Returns:
        Tool execution result
    """
    result = await send_feedback_summary_to_slack(mcp_client)
    return result


# ---------------------------------------------------------------------------
# Testing & Main
# ---------------------------------------------------------------------------

async def test_send():
    """Test sending feedback summary to Slack."""
    from mcp_client import MCPClient
    
    # Initialize MCP client
    mcp = MCPClient()
    await mcp.connect_to_all_servers()
    
    # Send message
    result = await send_feedback_summary_to_slack(mcp)
    
    print("Result:", result)
    
    await mcp.disconnect_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_send())
