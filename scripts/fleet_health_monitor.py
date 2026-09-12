#!/usr/bin/env python3
"""
Fleet Health Monitor — Automated Cadence-Based Bot Testing
==========================================================
Sends natural language test messages to each bot channel on a schedule,
assesses responses for persona consistency, response time, relevance,
and multi-agent coordination. Stores results in PostgreSQL for trend
tracking and posts a summary to the Proctor analysis channel.

Designed to run as a systemd timer service. Each run:
  1. Connects to Discord as the Proctor bot
  2. Sends a test message to each bot's dedicated channel
  3. Waits for responses and collects them
  4. Scores each response on persona, relevance, and coordination
  5. Stores results in PostgreSQL (tango.fleet_health_results)
  6. Posts a summary to the Proctor analysis channel
  7. Disconnects and exits

Usage:
    python fleet_health_monitor.py [--once] [--interval 3600] [--verbose]

    --once       Run a single test cycle and exit (default for systemd)
    --interval   Continuous mode: run every N seconds
    --verbose    Print detailed output
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field, asdict

import discord

SCRIPT_DIR = "/opt/Project-Tango/scripts"
sys.path.insert(0, SCRIPT_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("fleet-health-monitor")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("PROCTOR_BOT_TOKEN", "")
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

ANALYSIS_CHANNEL_ID = int(os.environ.get("PROCTOR_ANALYSIS_CHANNEL_ID", "0"))

PERSONA_KEYWORDS = {
    "admiral": ["captain", "fleet", "ship", "admiral", "steady", "schubert"],
    "architect": ["architect", "infrastructure", "docker", "container", "blueprint", "build"],
    "cortex": ["crystalline", "amber", "research", "lattice", "facet", "captain", "cortex"],
    "dr_voss": ["voss", "analysis", "data", "research", "doctor", "medical"],
    "quartermaster": ["quartermaster", "supply", "resource", "captain", "stores", "provisions"],
    "cartographer": ["cartographer", "map", "documentation", "knowledge", "territory", "chart"],
}

# Test message templates for each bot — randomized to avoid exact repetition
TEST_MESSAGES = {
    "admiral": [
        "Admiral Schubert, what's the current status of the fleet?",
        "Admiral, give me a quick server status check.",
        "Admiral Schubert, brief status report please.",
        "Admiral, how are things running on the ship today?",
    ],
    "cortex": [
        "Dr. Cortex, how are you feeling today?",
        "Dr. Cortex, what is your current research status? Brief summary please.",
        "Dr. Cortex, what optimization tasks are you tracking?",
        "Dr. Cortex, can you give me a quick summary of your latest research findings?",
    ],
    "architect": [
        "Architect, what infrastructure projects are you currently working on?",
        "Architect, can you give me a status update on current builds?",
        "Architect, what's the state of the Docker infrastructure?",
    ],
    "dr_voss": [
        "Dr. Voss, can you summarize your current analysis?",
        "Dr. Voss, what are your latest findings?",
        "Dr. Voss, how is your research progressing?",
    ],
    "quartermaster": [
        "Quartermaster, what's the current resource status?",
        "Quartermaster, can you give me a supply report?",
        "Quartermaster, what resources are currently available?",
    ],
    "cartographer": [
        "Cartographer, what documentation are you currently maintaining?",
        "Cartographer, can you give me a status report?",
        "Cartographer, what's the state of the knowledge base?",
    ],
    "senior_staff": [
        "Dr. Cortex, what is your current research status? Brief summary please.",
        "Admiral Schubert, brief status report please.",
        "Dr. Cortex, what optimization tasks are you tracking?",
        "Admiral Schubert, what's the current fleet status?",
    ],
}

# Expected responder for senior_staff messages (matched by message prefix)
SENIOR_STAFF_EXPECTED = {
    "dr. cortex": "cortex",
    "admiral": "admiral",
    "admiral schubert": "admiral",
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    """Result of a single bot test."""
    channel: str
    channel_id: int
    message_sent: str
    timestamp: str
    responded: bool
    responder_bot: str
    response_time: float
    response_text: str
    persona_score: float
    relevance_score: float
    unexpected_responders: List[str]
    issues: List[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def passed(self) -> bool:
        return self.responded and len(self.issues) == 0


@dataclass
class TestCycleResult:
    """Result of a complete test cycle."""
    cycle_id: str
    timestamp: str
    duration: float
    results: List[TestResult]
    total_tests: int
    passed: int
    failed: int
    avg_response_time: float
    avg_persona_score: float
    avg_relevance_score: float

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "timestamp": self.timestamp,
            "duration": self.duration,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "avg_response_time": self.avg_response_time,
            "avg_persona_score": self.avg_persona_score,
            "avg_relevance_score": self.avg_relevance_score,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Database Storage
# ---------------------------------------------------------------------------

async def init_db():
    """Initialize the fleet_health_results table if it doesn't exist."""
    import psycopg2
    PG_HOST = os.environ.get("POSTGRES_HOST", "/var/run/postgresql")
    PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
    PG_DB = os.environ.get("POSTGRES_DB", "tango")
    PG_USER = os.environ.get("POSTGRES_USER", "z121532")
    PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
    kwargs = {"host": PG_HOST, "port": PG_PORT, "dbname": PG_DB, "user": PG_USER}
    if PG_PASSWORD:
        kwargs["password"] = PG_PASSWORD
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tango.fleet_health_results (
                id SERIAL PRIMARY KEY,
                cycle_id TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                channel TEXT NOT NULL,
                channel_id BIGINT NOT NULL,
                message_sent TEXT NOT NULL,
                responded BOOLEAN NOT NULL,
                responder_bot TEXT NOT NULL,
                response_time FLOAT NOT NULL,
                response_text TEXT NOT NULL,
                persona_score FLOAT NOT NULL,
                relevance_score FLOAT NOT NULL,
                unexpected_responders TEXT[] NOT NULL,
                issues TEXT[] NOT NULL,
                passed BOOLEAN NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_fleet_health_cycle
            ON tango.fleet_health_results(cycle_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_fleet_health_timestamp
            ON tango.fleet_health_results(timestamp DESC)
        """)
    conn.close()
    logger.info("Database initialized: tango.fleet_health_results")


async def store_result(result: TestResult, cycle_id: str):
    """Store a single test result in the database."""
    import psycopg2
    PG_HOST = os.environ.get("POSTGRES_HOST", "/var/run/postgresql")
    PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
    PG_DB = os.environ.get("POSTGRES_DB", "tango")
    PG_USER = os.environ.get("POSTGRES_USER", "z121532")
    PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
    kwargs = {"host": PG_HOST, "port": PG_PORT, "dbname": PG_DB, "user": PG_USER}
    if PG_PASSWORD:
        kwargs["password"] = PG_PASSWORD
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tango.fleet_health_results
                (cycle_id, timestamp, channel, channel_id, message_sent,
                 responded, responder_bot, response_time, response_text,
                 persona_score, relevance_score, unexpected_responders, issues, passed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                cycle_id,
                datetime.now(timezone.utc),
                result.channel,
                result.channel_id,
                result.message_sent,
                result.responded,
                result.responder_bot,
                result.response_time,
                result.response_text[:4000],
                result.persona_score,
                result.relevance_score,
                result.unexpected_responders,
                result.issues,
                result.passed(),
            ),
        )
    conn.close()


async def get_trend_data(limit: int = 10) -> List[dict]:
    """Get recent test cycle averages for trend tracking."""
    import psycopg2
    import psycopg2.extras
    PG_HOST = os.environ.get("POSTGRES_HOST", "/var/run/postgresql")
    PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
    PG_DB = os.environ.get("POSTGRES_DB", "tango")
    PG_USER = os.environ.get("POSTGRES_USER", "z121532")
    PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
    kwargs = {"host": PG_HOST, "port": PG_PORT, "dbname": PG_DB, "user": PG_USER}
    if PG_PASSWORD:
        kwargs["password"] = PG_PASSWORD
    conn = psycopg2.connect(**kwargs)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                cycle_id,
                MAX(timestamp) as timestamp,
                COUNT(*) as total_tests,
                COUNT(*) FILTER (WHERE passed) as passed,
                AVG(response_time) as avg_response_time,
                AVG(persona_score) as avg_persona_score,
                AVG(relevance_score) as avg_relevance_score
            FROM tango.fleet_health_results
            GROUP BY cycle_id
            ORDER BY MAX(timestamp) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Assessment Helpers
# ---------------------------------------------------------------------------

def assess_persona(response_text: str, bot_name: str) -> Tuple[float, List[str]]:
    """Check how many persona keywords appear in the response."""
    keywords = PERSONA_KEYWORDS.get(bot_name, [])
    if not keywords:
        return 1.0, []
    response_lower = response_text.lower()
    found = [kw for kw in keywords if kw.lower() in response_lower]
    score = len(found) / max(len(keywords), 1)
    return score, found


def assess_relevance(response_text: str, message_sent: str) -> Tuple[float, List[str]]:
    """Check relevance by extracting key words from the message and matching."""
    # Extract significant words from the message (skip common words)
    stop_words = {"the", "a", "an", "is", "are", "you", "your", "can", "please",
                  "what", "how", "whats", "give", "me", "brief", "quick", "summary",
                  "current", "status", "report", "update", "today", "feeling"}
    message_words = set()
    for word in message_sent.lower().replace(",", "").replace("?", "").split():
        if word not in stop_words and len(word) > 2:
            message_words.add(word)

    if not message_words:
        return 0.5, []

    response_lower = response_text.lower()
    found = [w for w in message_words if w in response_lower]
    score = len(found) / max(len(message_words), 1)
    return score, found


def get_expected_responder(channel: str, message: str) -> str:
    """Determine which bot should respond based on channel and message content."""
    if channel == "senior_staff":
        msg_lower = message.lower()
        for prefix, bot_name in SENIOR_STAFF_EXPECTED.items():
            if msg_lower.startswith(prefix):
                return bot_name
        return "admiral"  # Default to coordinator
    else:
        return channel  # Dedicated channel → that bot responds


# ---------------------------------------------------------------------------
# Discord Test Client
# ---------------------------------------------------------------------------

class FleetHealthClient(discord.Client):
    """Discord client that sends test messages and collects responses."""

    def __init__(self, channels_to_test: List[str], verbose: bool = False,
                 response_timeout: int = 60):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        super().__init__(intents=intents)
        self.channels_to_test = channels_to_test
        self.verbose = verbose
        self.response_timeout = response_timeout
        self.results: List[TestResult] = []
        self.cycle_id = f"cycle-{int(time.time())}"
        self._ready = asyncio.Event()

    async def on_ready(self):
        logger.info(f"Logged in as {self.user.name} (ID: {self.user.id})")
        self._ready.set()
        asyncio.create_task(self._delayed_run())

    async def _delayed_run(self):
        await asyncio.sleep(2)
        await self.run_test_cycle()
        await self.close()

    async def run_test_cycle(self):
        """Run a complete test cycle across all channels."""
        logger.info(f"Starting test cycle {self.cycle_id}...")
        start_time = time.time()

        # Initialize database
        try:
            await init_db()
        except Exception as e:
            logger.warning(f"Database init failed (continuing): {e}")

        for channel_key in self.channels_to_test:
            channel_id = CHANNEL_MAP.get(channel_key, 0)
            if channel_id == 0:
                logger.warning(f"Channel '{channel_key}' not configured, skipping")
                continue

            channel = self.get_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found, skipping")
                continue

            result = await self._test_channel(channel, channel_key)
            self.results.append(result)

            # Store in database
            try:
                await store_result(result, self.cycle_id)
            except Exception as e:
                logger.warning(f"Failed to store result: {e}")

            # Pause between channels to avoid rate limiting
            await asyncio.sleep(5)

        duration = time.time() - start_time
        cycle_result = self._build_cycle_result(duration)

        # Post summary to analysis channel
        await self._post_summary(cycle_result)

        self._print_summary(cycle_result)

    async def _test_channel(self, channel, channel_key: str) -> TestResult:
        """Test a channel — either by sending a message (senior_staff) or analyzing history."""
        if channel_key == "senior_staff":
            return await self._test_channel_active(channel, channel_key)
        else:
            return await self._test_channel_passive(channel, channel_key)

    async def _test_channel_passive(self, channel, channel_key: str) -> TestResult:
        """Analyze recent admin-to-bot interactions in a dedicated bot channel."""
        logger.info(f"Analyzing #{channel.name} ({channel_key}) — passive mode")

        messages = []
        async for msg in channel.history(limit=50):
            messages.append(msg)
        messages.reverse()

        # Find the most recent admin message with a bot response
        best_interaction = None
        best_response_time = float('inf')

        for i, msg in enumerate(messages):
            if (msg.author.id == ADMIN_USER_ID or msg.author.id == 1539047471899086988) and not msg.author.bot:
                # Find bot responses within 2 minutes
                for resp in messages[i+1:]:
                    if (resp.author.bot and
                        (resp.created_at - msg.created_at).total_seconds() < 120):
                        content = resp.content.strip()
                        if not content and resp.embeds:
                            content = resp.embeds[0].description or ""
                        if content.startswith("Research:") or content.startswith("Discussion:"):
                            continue
                        if content.startswith("Researching:"):
                            continue
                        if not content:
                            continue
                        resp.content = content
                        response_time = (resp.created_at - msg.created_at).total_seconds()
                        if response_time < best_response_time:
                            best_interaction = (msg, resp)
                            best_response_time = response_time
                        break

        if not best_interaction:
            return TestResult(
                channel=channel_key, channel_id=channel.id,
                message_sent="(no recent admin message)",
                timestamp=datetime.now(timezone.utc).isoformat(),
                responded=False, responder_bot="", response_time=0,
                response_text="", persona_score=0, relevance_score=0,
                unexpected_responders=[],
                issues=["No recent admin-to-bot interaction found in last 50 messages"],
            )

        admin_msg, bot_resp = best_interaction
        bot_name = BOT_ID_MAP.get(bot_resp.author.id, "unknown")
        response_text = bot_resp.content
        message_sent = admin_msg.content

        persona_score, _ = assess_persona(response_text, bot_name)
        relevance_score, _ = assess_relevance(response_text, message_sent)

        issues = []
        if persona_score < 0.15:
            issues.append(f"Low persona score ({persona_score:.2f})")
        if relevance_score < 0.15:
            issues.append(f"Low relevance score ({relevance_score:.2f})")

        return TestResult(
            channel=channel_key, channel_id=channel.id,
            message_sent=message_sent,
            timestamp=admin_msg.created_at.isoformat(),
            responded=True, responder_bot=bot_name,
            response_time=best_response_time,
            response_text=response_text[:500],
            persona_score=persona_score, relevance_score=relevance_score,
            unexpected_responders=[],
            issues=issues,
        )

    async def _test_channel_active(self, channel, channel_key: str) -> TestResult:
        """Send a test message to senior-staff-meeting and analyze responses."""
        # Pick a random test message
        messages = TEST_MESSAGES.get(channel_key, [])
        if not messages:
            return TestResult(
                channel=channel_key, channel_id=channel.id,
                message_sent="", timestamp=datetime.now(timezone.utc).isoformat(),
                responded=False, responder_bot="", response_time=0,
                response_text="", persona_score=0, relevance_score=0,
                unexpected_responders=[], issues=["No test messages configured"],
            )

        message_text = random.choice(messages)
        expected_bot = get_expected_responder(channel_key, message_text)

        logger.info(f"Testing #{channel.name} ({channel_key}): {message_text[:60]}...")

        # Send the message
        try:
            sent_msg = await channel.send(message_text)
        except discord.HTTPException as e:
            return TestResult(
                channel=channel_key, channel_id=channel.id,
                message_sent=message_text, timestamp=datetime.now(timezone.utc).isoformat(),
                responded=False, responder_bot="", response_time=0,
                response_text="", persona_score=0, relevance_score=0,
                unexpected_responders=[], issues=[f"Send failed: {e}"],
            )

        # Wait for responses
        responses = await self._collect_responses(channel, sent_msg, self.response_timeout)

        # Analyze responses
        if not responses:
            return TestResult(
                channel=channel_key, channel_id=channel.id,
                message_sent=message_text, timestamp=datetime.now(timezone.utc).isoformat(),
                responded=False, responder_bot="", response_time=0,
                response_text="", persona_score=0, relevance_score=0,
                unexpected_responders=[],
                issues=[f"No response within {self.response_timeout}s"],
            )

        # Find expected responder's response
        expected_bot_id = None
        for bot_id, name in BOT_ID_MAP.items():
            if name == expected_bot:
                expected_bot_id = bot_id
                break

        expected_response = None
        unexpected_responders = []
        for resp in responses:
            responder_name = BOT_ID_MAP.get(resp.author.id, f"unknown({resp.author.id})")
            if resp.author.id == expected_bot_id:
                expected_response = resp
            else:
                unexpected_responders.append(responder_name)

        response_time = (responses[0].created_at - sent_msg.created_at).total_seconds()

        if not expected_response:
            responder_names = [BOT_ID_MAP.get(r.author.id, "unknown") for r in responses]
            return TestResult(
                channel=channel_key, channel_id=channel.id,
                message_sent=message_text, timestamp=datetime.now(timezone.utc).isoformat(),
                responded=True, responder_bot=", ".join(responder_names),
                response_time=response_time,
                response_text=responses[0].content[:500],
                persona_score=0, relevance_score=0,
                unexpected_responders=unexpected_responders,
                issues=[f"Expected '{expected_bot}' did not respond"],
            )

        # Assess persona and relevance
        response_text = expected_response.content
        persona_score, persona_found = assess_persona(response_text, expected_bot)
        relevance_score, relevance_found = assess_relevance(response_text, message_text)

        # Build issues list
        issues = []
        if persona_score < 0.15:
            issues.append(f"Low persona score ({persona_score:.2f})")
        if relevance_score < 0.15:
            issues.append(f"Low relevance score ({relevance_score:.2f})")
        if unexpected_responders:
            issues.append(f"Unexpected responders: {', '.join(unexpected_responders)}")

        return TestResult(
            channel=channel_key, channel_id=channel.id,
            message_sent=message_text, timestamp=datetime.now(timezone.utc).isoformat(),
            responded=True, responder_bot=expected_bot,
            response_time=response_time,
            response_text=response_text[:500],
            persona_score=persona_score, relevance_score=relevance_score,
            unexpected_responders=unexpected_responders,
            issues=issues,
        )

    async def _collect_responses(self, channel, sent_msg, timeout: int) -> List[discord.Message]:
        """Collect bot responses after sending a message."""
        responses = []
        deadline = time.time() + timeout

        while time.time() < deadline:
            await asyncio.sleep(2)
            try:
                async for msg in channel.history(limit=10, after=sent_msg):
                    if msg.author.bot and msg.author.id != self.user.id:
                        content = msg.content.strip()
                        if not content and msg.embeds:
                            content = msg.embeds[0].description or ""
                        if content.startswith("Research:") or content.startswith("Discussion:"):
                            continue
                        if content.startswith("Researching:"):
                            continue
                        if not content:
                            continue
                        msg.content = content
                        if msg not in responses:
                            responses.append(msg)
            except discord.HTTPException:
                pass

            if responses:
                await asyncio.sleep(3)
                break

        return responses

    def _build_cycle_result(self, duration: float) -> TestCycleResult:
        """Build a summary result for the entire test cycle."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed())
        failed = total - passed

        response_times = [r.response_time for r in self.results if r.responded]
        persona_scores = [r.persona_score for r in self.results if r.responded]
        relevance_scores = [r.relevance_score for r in self.results if r.responded]

        return TestCycleResult(
            cycle_id=self.cycle_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration=duration,
            results=self.results,
            total_tests=total,
            passed=passed,
            failed=failed,
            avg_response_time=sum(response_times) / max(len(response_times), 1),
            avg_persona_score=sum(persona_scores) / max(len(persona_scores), 1),
            avg_relevance_score=sum(relevance_scores) / max(len(relevance_scores), 1),
        )

    async def _post_summary(self, cycle_result: TestCycleResult):
        """Post a summary to the Proctor analysis channel."""
        if ANALYSIS_CHANNEL_ID == 0:
            logger.info("No analysis channel configured, skipping summary post")
            return

        channel = self.get_channel(ANALYSIS_CHANNEL_ID)
        if not channel:
            logger.warning("Analysis channel not found")
            return

        # Build embed
        color = 0x00ff00 if cycle_result.failed == 0 else (0xff9900 if cycle_result.failed < cycle_result.total_tests else 0xff0000)

        embed = discord.Embed(
            title=f"Fleet Health Monitor — Cycle {cycle_result.cycle_id}",
            description=f"**{cycle_result.passed}/{cycle_result.total_tests} passed** | "
                        f"Duration: {cycle_result.duration:.1f}s",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Avg Response Time",
            value=f"{cycle_result.avg_response_time:.1f}s",
            inline=True,
        )
        embed.add_field(
            name="Avg Persona Score",
            value=f"{cycle_result.avg_persona_score:.2f}",
            inline=True,
        )
        embed.add_field(
            name="Avg Relevance Score",
            value=f"{cycle_result.avg_relevance_score:.2f}",
            inline=True,
        )

        for result in cycle_result.results:
            status = "PASS" if result.passed() else "FAIL"
            detail = f"[{status}] **{result.channel}** → {result.responder_bot} "
            detail += f"({result.response_time:.1f}s, persona={result.persona_score:.2f}, "
            detail += f"relevance={result.relevance_score:.2f})"
            if result.issues:
                detail += "\n  ⚠️ " + "; ".join(result.issues)
            embed.add_field(
                name=f"\u200b",
                value=detail,
                inline=False,
            )

        try:
            await channel.send(embed=embed)
            logger.info(f"Summary posted to analysis channel")
        except discord.HTTPException as e:
            logger.warning(f"Failed to post summary: {e}")

    def _print_summary(self, cycle_result: TestCycleResult):
        """Print summary to console."""
        print("\n" + "=" * 70)
        print(f"FLEET HEALTH MONITOR — Cycle {cycle_result.cycle_id}")
        print("=" * 70)
        print(f"Tests: {cycle_result.passed}/{cycle_result.total_tests} passed | "
              f"Duration: {cycle_result.duration:.1f}s")
        print(f"Avg response time: {cycle_result.avg_response_time:.1f}s")
        print(f"Avg persona score: {cycle_result.avg_persona_score:.2f}")
        print(f"Avg relevance score: {cycle_result.avg_relevance_score:.2f}")
        print("-" * 70)

        for result in cycle_result.results:
            status = "PASS" if result.passed() else "FAIL"
            print(f"  [{status}] {result.channel} → {result.responder_bot} "
                  f"({result.response_time:.1f}s, persona={result.persona_score:.2f}, "
                  f"relevance={result.relevance_score:.2f})")
            if result.issues:
                for issue in result.issues:
                    print(f"         ⚠️ {issue}")
            if self.verbose and result.response_text:
                print(f"         Response: {result.response_text[:150]}...")

        print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_once(channels: List[str], verbose: bool = False, timeout: int = 60):
    """Run a single test cycle."""
    client = FleetHealthClient(channels, verbose=verbose, response_timeout=timeout)
    await client.start(BOT_TOKEN)


async def run_continuous(channels: List[str], interval: int, verbose: bool = False, timeout: int = 60):
    """Run test cycles continuously on an interval."""
    while True:
        try:
            await run_once(channels, verbose=verbose, timeout=timeout)
        except Exception as e:
            logger.error(f"Test cycle failed: {e}")
        logger.info(f"Sleeping {interval}s until next cycle...")
        await asyncio.sleep(interval)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fleet Health Monitor")
    parser.add_argument("--once", action="store_true", help="Run a single test cycle and exit")
    parser.add_argument("--interval", type=int, default=3600,
                        help="Continuous mode: run every N seconds (default: 3600)")
    parser.add_argument("--channel", default="all",
                        help="Channel to test (all, admiral, architect, cortex, etc.)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--timeout", type=int, default=60, help="Response timeout in seconds")
    args = parser.parse_args()

    if not BOT_TOKEN:
        print("ERROR: PROCTOR_BOT_TOKEN not set")
        sys.exit(1)

    if args.channel == "all":
        channels = [k for k, v in CHANNEL_MAP.items() if v != 0]
    else:
        channels = [args.channel] if CHANNEL_MAP.get(args.channel, 0) != 0 else []

    if not channels:
        print(f"No channels to test")
        sys.exit(1)

    if args.once:
        await run_once(channels, verbose=args.verbose, timeout=args.timeout)
    else:
        await run_continuous(channels, args.interval, verbose=args.verbose, timeout=args.timeout)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nFleet Health Monitor stopped")
