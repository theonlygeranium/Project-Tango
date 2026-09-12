#!/usr/bin/env python3
"""Update Discord channels for the Nexus Fleet Model architecture.

Updates channel topics, creates Sentinel channel mapping, and posts starter
messages explaining each bot's role in the new hierarchy.

Usage:
    python scripts/update_discord_channels.py           # Live run
    python scripts/update_discord_channels.py --dry-run   # Preview only

Requires:
    - discord.py (pip install discord.py)
    - SCHUBERT_BOT_TOKEN environment variable
"""
import argparse
import asyncio
import logging
import os
import sys

import discord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel updates: (channel_id, new_topic, starter_message)
# ---------------------------------------------------------------------------

CHANNEL_UPDATES = [
    {
        "channel_id": 1538476446157115442,
        "name": "admiral-schubert",
        "topic": (
            "Tier 0 — Fleet Commander | Sole authority for fleet operations, "
            "task routing, and delegation. Nexus Bus orchestrator."
        ),
        "starter_message": (
            "# Admiral Schubert — Tier 0: Fleet Commander\n\n"
            "Welcome to the Nexus Fleet Model.\n\n"
            "## Role\n"
            "Admiral Schubert is the **sole Tier 0 commander** of the fleet. "
            "All task routing, delegation, and fleet-wide coordination flows "
            "through here.\n\n"
            "## Capabilities\n"
            "- **Orchestrator Router**: Deterministic task decomposition and "
            "routing to specialist bots\n"
            "- **Acknowledgment Protocol**: 30-second ack with 2 retries on "
            "task assignments\n"
            "- **Escalation Ladder**: retry → reroute → Dr. Voss → human "
            "operator\n"
            "- **Nexus Bus**: Inter-bot communication via Redis Streams\n"
            "- **Voice Operations**: Deepgram STT + ElevenLabs TTS\n"
            "- **Fleet Delegation**: Send and receive tasks to all "
            "specialists\n\n"
            "## Hierarchy\n"
            "```\n"
            "Tier 0: Admiral (sole commander)\n"
            "Tier 1: Architect, Dr. Voss, Dr. Cortex\n"
            "Tier 2: Quartermaster, Cartographer, Sentinel\n"
            "```\n\n"
            "## Commands\n"
            "Send natural language messages to interact. Use `@bot_name` to "
            "address specific bots in multi-agent channels."
        ),
    },
    {
        "channel_id": 1539473266400432208,
        "name": "the-architect",
        "topic": (
            "Tier 1 — Lead Developer | Code implementation, architecture "
            "decisions, and fleet-wide upgrades. Reports to Admiral."
        ),
        "starter_message": (
            "# The Architect — Tier 1: Lead Developer\n\n"
            "## Role\n"
            "The Architect has been elevated to **Tier 1 Executive** as the "
            "fleet's lead developer. Focus is on code implementation, "
            "architecture decisions, and fleet-wide upgrades.\n\n"
            "## Capabilities\n"
            "- **Code Implementation**: Full read/write/search on the "
            "codebase\n"
            "- **Architecture Decisions**: ADRs, system design, refactoring\n"
            "- **Self-Healing**: Health monitoring and auto-remediation\n"
            "- **Self-Improvement**: Automated prompt and code updates\n"
            "- **Cloudflare Tooling**: DNS management and cache purging\n"
            "- **Writer Integration**: Document generation via Writer API\n\n"
            "## Reporting\n"
            "Reports directly to Admiral Schubert. Receives tasks via fleet "
            "delegation and Nexus Bus.\n\n"
            "## Hierarchy Position\n"
            "```\n"
            "Tier 0: Admiral\n"
            "Tier 1: Architect ← YOU ARE HERE\n"
            "Tier 2: Quartermaster, Cartographer, Sentinel\n"
            "```"
        ),
    },
    {
        "channel_id": 1539104998821068880,
        "name": "dr-voss",
        "topic": (
            "Tier 1 — Chief Medical Officer | Health monitoring, "
            "diagnostics, crisis response, and auto-remediation. Reports "
            "to Admiral."
        ),
        "starter_message": (
            "# Dr. Voss — Tier 1: Chief Medical Officer\n\n"
            "## Role\n"
            "Dr. Voss serves as the fleet's **Chief Medical Officer** at "
            "Tier 1. Responsible for health monitoring, diagnostics, crisis "
            "response, and auto-remediation across all fleet services.\n\n"
            "## Capabilities\n"
            "- **Self-Healing**: 60-second health checks with escalation\n"
            "- **Diagnostics**: Service failure analysis and root cause\n"
            "- **Crisis Response**: Automated remediation with retry limits\n"
            "- **Self-Improvement**: Automated prompt and code updates\n"
            "- **Coding**: Code-level fixes for health issues\n"
            "- **Intensive Monitoring**: 10-second intervals during "
            "incidents\n\n"
            "## Escalation Ladder\n"
            "Admiral → retry → reroute → **Dr. Voss** → human operator\n\n"
            "## Reporting\n"
            "Reports directly to Admiral Schubert. Activated automatically "
            "during fleet health incidents."
        ),
    },
    {
        "channel_id": 1539173946698498088,
        "name": "dr-cortex",
        "topic": (
            "Tier 1 — Science Officer | Research, analysis, data flywheel, "
            "and weekly fleet analysis reports. Reports to Admiral."
        ),
        "starter_message": (
            "# Dr. Cortex — Tier 1: Science Officer\n\n"
            "## Role\n"
            "Dr. Cortex serves as the fleet's **Science Officer** at "
            "Tier 1. Responsible for research, analysis, the data flywheel, "
            "and weekly fleet analysis reports.\n\n"
            "## Capabilities\n"
            "- **Research**: Web search and evidence synthesis\n"
            "- **Data Flywheel**: Continuous data collection and analysis\n"
            "- **Weekly Analysis**: Fleet performance and capability "
            "reports\n"
            "- **Voice Mode**: Deepgram STT + ElevenLabs TTS\n"
            "- **Fleet Delegation**: Send and receive tasks\n"
            "- **Polls**: Create and manage fleet polls\n"
            "- **Coding**: Code analysis and test execution\n\n"
            "## Reporting\n"
            "Reports directly to Admiral Schubert. Provides research and "
            "analysis support to all tiers."
        ),
    },
    {
        "channel_id": 1538818248542396428,
        "name": "quartermaster",
        "topic": (
            "Tier 2 — Operations | Infrastructure monitoring, service "
            "health, disk/process management. Reports to Admiral."
        ),
        "starter_message": (
            "# Quartermaster — Tier 2: Operations\n\n"
            "## Role\n"
            "Quartermaster is the fleet's **operations specialist** at "
            "Tier 2. Responsible for infrastructure monitoring, service "
            "health, disk usage, and process management.\n\n"
            "## Capabilities\n"
            "- **Service Status**: Monitor systemd services\n"
            "- **Disk Usage**: Track filesystem capacity and alerts\n"
            "- **Process Management**: Running process inspection\n"
            "- **Log Tailing**: Real-time log analysis\n"
            "- **Health Checks**: Comprehensive system health reports\n"
            "- **Memory Recall**: Persistent operational context\n\n"
            "## Reporting\n"
            "Reports to Admiral Schubert. Provides operational data to "
            "Dr. Voss for health-related decisions."
        ),
    },
    {
        "channel_id": 1538818895706718269,
        "name": "cartographer",
        "topic": (
            "Tier 2 — Documentation | Wiki maintenance, knowledge "
            "management, and change logs. Reports to Admiral."
        ),
        "starter_message": (
            "# Cartographer — Tier 2: Documentation\n\n"
            "## Role\n"
            "Cartographer is the fleet's **documentation officer** at "
            "Tier 2. Responsible for wiki maintenance, knowledge "
            "management, and change logs.\n\n"
            "## Capabilities\n"
            "- **Wiki Updates**: Create and update documentation pages\n"
            "- **Doc Search**: Search existing documentation\n"
            "- **Change Logs**: Track and document fleet changes\n"
            "- **Knowledge Management**: Organize and maintain knowledge "
            "base\n"
            "- **Memory Recall**: Persistent documentation context\n\n"
            "## Reporting\n"
            "Reports to Admiral Schubert. Maintains the fleet's knowledge "
            "base for all tiers."
        ),
    },
    {
        "channel_id": 1539159059071111190,
        "name": "sentinel",
        "topic": (
            "Tier 2 — Autonomous Testing & Validation | Conversational "
            "testing, Agent-as-a-Judge evaluation, auto-generated test "
            "cases, and repair loop. Reports to Admiral."
        ),
        "starter_message": (
            "# Sentinel — Tier 2: Autonomous Testing & Validation\n\n"
            "## Role\n"
            "Sentinel replaces The Proctor as the fleet's **autonomous "
            "testing and validation** specialist at Tier 2. Implements "
            "Agent-as-a-Judge evaluation, auto-generated test cases, and "
            "a repair loop for continuous quality assurance.\n\n"
            "## Capabilities\n"
            "- **Test Recipes**: Predefined test scenarios for each bot\n"
            "- **Rubrics**: Structured evaluation criteria\n"
            "- **Conversation Runner**: Automated multi-turn test "
            "conversations\n"
            "- **Agent-as-a-Judge**: LLM-powered response quality "
            "evaluation\n"
            "- **Test Generator**: Auto-generate test cases from "
            "interactions\n"
            "- **Repair Engine**: Automatically fix failing test "
            "scenarios\n"
            "- **Posterior Tracking**: Track capability scores over "
            "time\n\n"
            "## Proctor Legacy\n"
            "This channel replaces The Proctor's delegation channel. "
            "Historical Proctor data is preserved in the Sentinel Analysis "
            "Archive channel.\n\n"
            "## Reporting\n"
            "Reports to Admiral Schubert. Test results feed into Dr. "
            "Cortex's data flywheel for fleet-wide analysis."
        ),
    },
    {
        "channel_id": 1539023116968398911,
        "name": "senior-staff-meeting",
        "topic": (
            "Multi-Agent Collaborative Channel | All bots collaborate "
            "here. Admiral coordinates. Nexus Bus events visible to all."
        ),
        "starter_message": (
            "# Senior Staff Meeting — Multi-Agent Collaborative Channel\n\n"
            "## Purpose\n"
            "This is the **multi-agent collaborative channel** where all "
            "fleet bots participate. Admiral Schubert coordinates "
            "discussions and task assignments.\n\n"
            "## Participants\n"
            "- **Tier 0**: Admiral Schubert (coordinator)\n"
            "- **Tier 1**: The Architect, Dr. Voss, Dr. Cortex\n"
            "- **Tier 2**: Quartermaster, Cartographer, Sentinel\n\n"
            "## Participation Rules\n"
            "- Each bot responds when addressed via `@bot_name` or when "
            "the conversation is relevant to their role\n"
            "- Admiral has final authority on all decisions\n"
            "- Response thresholds apply per bot configuration\n"
            "- Cooldowns prevent spam — each bot waits before "
            "responding again\n\n"
            "## Nexus Bus Integration\n"
            "Inter-bot communication events from the Nexus Bus (Redis "
            "Streams) are visible to all participants in this channel. "
            "This enables real-time awareness of fleet-wide task routing, "
            "delegations, and acknowledgments.\n\n"
            "## Commands\n"
            "- `@bot_name <message>` — Address a specific bot\n"
            "- Natural language — All bots evaluate relevance and respond "
            "if threshold is met"
        ),
    },
    {
        "channel_id": 1539159060568342539,
        "name": "sentinel-analysis-archive",
        "topic": (
            "Sentinel Analysis Archive | Test results, posterior scores, "
            "and capability tracking. Historical Proctor data preserved."
        ),
        "starter_message": (
            "# Sentinel Analysis Archive\n\n"
            "## Purpose\n"
            "This channel serves as **Sentinel's analysis archive**. "
            "Test results, posterior scores, and capability tracking data "
            "are posted here for historical reference.\n\n"
            "## Contents\n"
            "- Test run results and scores\n"
            "- Posterior capability tracking over time\n"
            "- Agent-as-a-Judge evaluations\n"
            "- Repair loop outcomes\n"
            "- Historical Proctor data (preserved from previous testing)\n\n"
            "## Proctor Legacy\n"
            "This channel previously served as The Proctor's analysis "
            "channel. All historical Proctor data is preserved here. "
            "Sentinel continues the testing mission with enhanced "
            "capabilities."
        ),
    },
    {
        "channel_id": 1539104999941079103,
        "name": "proctor-archive",
        "topic": (
            "Archive — Former Proctor Channel | Replaced by Sentinel. "
            "Historical reference only."
        ),
        "starter_message": (
            "# Proctor Archive\n\n"
            "## Status: Archived\n"
            "This channel is now **archived**. The Proctor has been "
            "replaced by **Sentinel** (Tier 2 — Autonomous Testing & "
            "Validation).\n\n"
            "## Historical Reference\n"
            "Messages in this channel are preserved for historical "
            "reference. No new testing activity will occur here.\n\n"
            "## Where to Find Sentinel\n"
            "- **Sentinel Channel**: Repurposed from Proctor's delegation "
            "channel\n"
            "- **Sentinel Analysis Archive**: Repurposed from Proctor's "
            "analysis channel\n\n"
            "## Transition\n"
            "All testing responsibilities have been transferred to "
            "Sentinel with enhanced capabilities including Agent-as-a-Judge "
            "evaluation, auto-generated test cases, and a repair loop."
        ),
    },
]


# ---------------------------------------------------------------------------
# Dry-run preview
# ---------------------------------------------------------------------------

def dry_run() -> None:
    """Print what would be changed without connecting to Discord."""
    logger.info("=== DRY RUN — no changes will be made ===\n")
    for update in CHANNEL_UPDATES:
        cid = update["channel_id"]
        name = update["name"]
        topic = update["topic"]
        msg_preview = update["starter_message"][:120].replace("\n", " ")
        logger.info(f"Channel: #{name} (ID: {cid})")
        logger.info(f"  New topic: {topic}")
        logger.info(f"  Starter message preview: {msg_preview}...")
        logger.info("")
    logger.info(f"Total channels to update: {len(CHANNEL_UPDATES)}")
    logger.info("=== DRY RUN COMPLETE ===")


# ---------------------------------------------------------------------------
# Live update
# ---------------------------------------------------------------------------

async def update_channels() -> None:
    """Connect to Discord and update all channels."""
    token = os.environ.get("SCHUBERT_BOT_TOKEN")
    if not token:
        logger.error("SCHUBERT_BOT_TOKEN not found in environment")
        logger.error("Set it with: export SCHUBERT_BOT_TOKEN='your_token_here'")
        sys.exit(1)

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        logger.info(f"Connected as {client.user} ({client.user.id})")
        logger.info(f"Updating {len(CHANNEL_UPDATES)} channels...\n")

        success_count = 0
        fail_count = 0

        for update in CHANNEL_UPDATES:
            cid = update["channel_id"]
            name = update["name"]
            topic = update["topic"]
            message = update["starter_message"]

            channel = client.get_channel(cid)
            if not channel:
                logger.warning(
                    f"Channel #{name} (ID: {cid}) not found — skipping"
                )
                fail_count += 1
                continue

            logger.info(f"Processing #{channel.name} (ID: {cid})")

            # Update topic
            try:
                await channel.edit(topic=topic)
                logger.info(f"  ✓ Updated topic for #{channel.name}")
            except discord.Forbidden:
                logger.error(
                    f"  ✗ Missing permissions to edit #{channel.name}"
                )
                fail_count += 1
                continue
            except discord.HTTPException as e:
                logger.error(
                    f"  ✗ Failed to update topic for #{channel.name}: {e}"
                )
                fail_count += 1
                continue

            # Post starter message
            try:
                await channel.send(message)
                logger.info(f"  ✓ Posted starter message in #{channel.name}")
            except discord.HTTPException as e:
                logger.error(
                    f"  ✗ Failed to post message in #{channel.name}: {e}"
                )
                fail_count += 1
                continue

            success_count += 1

            # Rate limit safety
            await asyncio.sleep(1)

        logger.info(f"\nUpdate complete: {success_count} succeeded, "
                     f"{fail_count} failed")
        logger.info("Disconnecting from Discord...")
        await client.close()

    try:
        await client.start(token)
    except discord.LoginFailure:
        logger.error("Invalid token — SCHUBERT_BOT_TOKEN is not valid")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update Discord channels for the Nexus Fleet Model "
                    "architecture."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be changed without actually doing it.",
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
    else:
        asyncio.run(update_channels())


if __name__ == "__main__":
    main()
