#!/usr/bin/env python3
"""
Proctor Conversation Test Suite
===============================
Tactical test that uses the Proctor bot to send natural language commands
to each bot channel, carries conversations, and assesses the responses.

Since the bots only respond to ADMIN_USER_ID, this test uses the Proctor bot
to read channel history and analyze recent interactions. For channels where
the Proctor bot has send permissions, it can also send test messages.

Usage:
    python proctor_conversation_test.py [--channel all|admiral|architect|cortex|...]
                                         [--verbose]
                                         [--timeout 60]
                                         [--send]  # Send test messages (requires admin to be bot)
"""

import asyncio
import os
import re
import sys
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field

import discord

SCRIPT_DIR = "/opt/Project-Tango/scripts"
sys.path.insert(0, SCRIPT_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("proctor-conversation-test")

BOT_TOKEN = os.environ.get("PROCTOR_BOT_TOKEN", "")
if not BOT_TOKEN:
    print("ERROR: PROCTOR_BOT_TOKEN not set")
    sys.exit(1)

ADMIN_USER_ID = 1075596247966167131

CHANNEL_MAP = {
    "admiral": int(os.environ.get("FLEET_COMMAND_CHANNEL_ID", "1538476446157115442")),
    "architect": int(os.environ.get("ARCHITECT_CHANNEL_ID", "0")),
    "cortex": int(os.environ.get("CORTEX_CHANNEL_ID", "0")),
    "dr_voss": int(os.environ.get("DR_VOSS_CHANNEL_ID", "0")),
    "quartermaster": int(os.environ.get("QUARTERMASTER_CHANNEL_ID", "0")),
    "cartographer": int(os.environ.get("CARTOGRAPHER_CHANNEL_ID", "0")),
    "senior_staff": int(os.environ.get("SENIOR_STAFF_CHANNEL_ID", "0")),
}

BOT_ID_MAP = {
    1538476585445892179: "admiral",
    1538766501035642890: "architect",
    1538817623045832746: "quartermaster",
    1538818587119067206: "cartographer",
    1539047086597873684: "dr_voss",
    1539172849569243217: "cortex",
}

PERSONA_KEYWORDS = {
    "admiral": ["captain", "fleet", "ship", "admiral", "steady", "schubert"],
    "architect": ["architect", "infrastructure", "docker", "container", "blueprint", "build"],
    "cortex": ["crystalline", "amber", "research", "lattice", "facet", "captain", "cortex"],
    "dr_voss": ["voss", "analysis", "data", "research", "doctor", "medical"],
    "quartermaster": ["quartermaster", "supply", "resource", "captain", "stores", "provisions"],
    "cartographer": ["cartographer", "map", "documentation", "knowledge", "territory", "chart"],
}


@dataclass
class ChannelAnalysis:
    """Analysis of a Discord channel's recent bot interactions."""
    channel_name: str
    channel_id: int
    total_messages: int = 0
    admin_messages: int = 0
    bot_messages: int = 0
    bot_response_times: List[float] = field(default_factory=list)
    issues_found: List[str] = field(default_factory=list)
    persona_scores: Dict[str, float] = field(default_factory=dict)
    recent_interactions: List[dict] = field(default_factory=list)


class ConversationTestClient(discord.Client):
    """Discord client for conversation testing."""

    def __init__(self, channels_to_test: List[str], verbose: bool = False):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        super().__init__(intents=intents)
        self.channels_to_test = channels_to_test
        self.verbose = verbose
        self.results: List[ChannelAnalysis] = []
        self._ready = asyncio.Event()

    async def on_ready(self):
        logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        self._ready.set()
        asyncio.create_task(self._delayed_run())

    async def _delayed_run(self):
        await asyncio.sleep(2)
        await self.run_analysis()
        await self.close()

    async def run_analysis(self):
        """Analyze recent messages in each channel."""
        logger.info(f"Analyzing {len(self.channels_to_test)} channels...")

        for channel_key in self.channels_to_test:
            channel_id = CHANNEL_MAP.get(channel_key, 0)
            if channel_id == 0:
                logger.warning(f"Channel '{channel_key}' not configured")
                continue

            channel = self.get_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found")
                continue

            logger.info(f"Analyzing #{channel.name} ({channel_key})...")
            analysis = await self._analyze_channel(channel, channel_key)
            self.results.append(analysis)
            await asyncio.sleep(1)

        self.print_summary()

    async def _analyze_channel(self, channel, channel_key: str) -> ChannelAnalysis:
        """Analyze recent messages in a channel."""
        analysis = ChannelAnalysis(
            channel_name=channel.name,
            channel_id=channel.id,
        )

        # Fetch last 50 messages
        messages = []
        async for msg in channel.history(limit=50):
            messages.append(msg)

        messages.reverse()  # Chronological order

        analysis.total_messages = len(messages)

        # Find admin-to-bot interactions
        last_admin_msg_time = None
        for msg in messages:
            if msg.author.id == ADMIN_USER_ID and not msg.author.bot:
                analysis.admin_messages += 1
                last_admin_msg_time = msg.created_at

                # Find bot responses within 2 minutes
                bot_responses = []
                for resp in messages:
                    if (resp.author.bot and
                        resp.created_at > msg.created_at and
                        (resp.created_at - msg.created_at).total_seconds() < 120):
                        bot_responses.append(resp)

                if bot_responses:
                    response_time = (bot_responses[0].created_at - msg.created_at).total_seconds()
                    analysis.bot_response_times.append(response_time)

                    # Check persona consistency
                    for resp in bot_responses:
                        bot_name = BOT_ID_MAP.get(resp.author.id, "unknown")
                        if bot_name in PERSONA_KEYWORDS:
                            keywords = PERSONA_KEYWORDS[bot_name]
                            response_lower = resp.content.lower()
                            matches = sum(1 for kw in keywords if kw.lower() in response_lower)
                            score = matches / max(len(keywords), 1)
                            analysis.persona_scores[bot_name] = score

                            if score < 0.15:
                                analysis.issues_found.append(
                                    f"Low persona score for {bot_name} ({score:.2f}) "
                                    f"responding to: '{msg.content[:60]}...'"
                                )

                    # Check for multiple bots responding to a directed message
                    content_lower = msg.content.lower()
                    addressed_bot = None
                    for bot_name, keywords in PERSONA_KEYWORDS.items():
                        for kw in keywords[:3]:  # Check first few keywords
                            if content_lower.startswith(f"{kw},") or content_lower.startswith(f"{kw}:"):
                                addressed_bot = bot_name
                                break
                        if addressed_bot:
                            break

                    if addressed_bot and len(bot_responses) > 1:
                        responder_names = [BOT_ID_MAP.get(r.author.id, "unknown") for r in bot_responses]
                        unexpected = [n for n in responder_names if n != addressed_bot]
                        if unexpected:
                            analysis.issues_found.append(
                                f"Multiple bots responded to message addressed to {addressed_bot}: "
                                f"{', '.join(responder_names)} (unexpected: {', '.join(unexpected)})"
                            )

                    # Store interaction
                    analysis.recent_interactions.append({
                        "admin_msg": msg.content[:100],
                        "responders": [BOT_ID_MAP.get(r.author.id, "unknown") for r in bot_responses],
                        "response_time": response_time,
                        "first_response_preview": bot_responses[0].content[:200] if bot_responses else "",
                    })
                else:
                    analysis.issues_found.append(
                        f"No bot response to admin message: '{msg.content[:60]}...'"
                    )
            elif msg.author.bot:
                analysis.bot_messages += 1

        return analysis

    def print_summary(self):
        """Print analysis summary."""
        print("\n" + "=" * 70)
        print("PROCTOR CONVERSATION TEST — CHANNEL ANALYSIS")
        print("=" * 70)

        total_issues = 0
        for analysis in self.results:
            print(f"\n#{analysis.channel_name} (ID: {analysis.channel_id})")
            print(f"  Messages: {analysis.total_messages} total, "
                  f"{analysis.admin_messages} from admin, "
                  f"{analysis.bot_messages} from bots")
            print(f"  Interactions analyzed: {len(analysis.recent_interactions)}")

            if analysis.bot_response_times:
                avg_time = sum(analysis.bot_response_times) / len(analysis.bot_response_times)
                min_time = min(analysis.bot_response_times)
                max_time = max(analysis.bot_response_times)
                print(f"  Response times: avg={avg_time:.1f}s, "
                      f"min={min_time:.1f}s, max={max_time:.1f}s")

            if analysis.persona_scores:
                for bot_name, score in analysis.persona_scores.items():
                    status = "OK" if score >= 0.15 else "LOW"
                    print(f"  Persona score [{bot_name}]: {score:.2f} [{status}]")

            if analysis.issues_found:
                print(f"  Issues ({len(analysis.issues_found)}):")
                for issue in analysis.issues_found:
                    print(f"    - {issue}")
                    total_issues += 1
            else:
                print("  No issues found")

            if self.verbose and analysis.recent_interactions:
                print("  Recent interactions:")
                for interaction in analysis.recent_interactions[-3:]:
                    print(f"    Admin: {interaction['admin_msg']}")
                    print(f"    Responders: {', '.join(interaction['responders'])}")
                    print(f"    Response time: {interaction['response_time']:.1f}s")
                    if interaction['first_response_preview']:
                        print(f"    Response: {interaction['first_response_preview'][:150]}...")
                    print()

        print("\n" + "=" * 70)
        if total_issues == 0:
            print("NO ISSUES FOUND — All channels look healthy")
        else:
            print(f"{total_issues} ISSUE(S) FOUND")
        print("=" * 70)


async def main():
    parser = argparse.ArgumentParser(description="Proctor Conversation Test Suite")
    parser.add_argument(
        "--channel", default="all",
        help="Channel to test (all, admiral, architect, cortex, dr_voss, quartermaster, cartographer, senior_staff)"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--timeout", type=int, default=60, help="Timeout in seconds")
    args = parser.parse_args()

    if args.channel == "all":
        channels = list(CHANNEL_MAP.keys())
    else:
        channels = [args.channel]

    channels = [c for c in channels if CHANNEL_MAP.get(c, 0) != 0]
    if not channels:
        print(f"No channels found for '{args.channel}'")
        sys.exit(1)

    client = ConversationTestClient(channels, verbose=args.verbose)
    await client.start(BOT_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted")
