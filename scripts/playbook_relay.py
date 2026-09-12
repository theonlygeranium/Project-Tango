"""
Playbook Webhook Relay Service for Schubert Bot V2
====================================================
Bridges WRITER Agent playbook webhooks to Discord, enabling:
1. Discord bots to trigger playbooks via webhook
2. Playbooks to relay questions back to Discord via HTTP Request blocks
3. Discord users to answer questions, with responses flowing back to the playbook

Architecture:
  Discord user: !run-playbook <key> [inputs_json]
    -> Bot calls relay.trigger_playbook(key, inputs)
    -> Relay POSTs to WRITER webhook, gets thread_id
    -> Playbook runs in WRITER cloud

  When playbook needs input (via HTTP Request block):
    -> Playbook POSTs to https://webhook.schubert.life/playbook/ask
    -> Relay posts question to Discord, blocks HTTP response
    -> Discord user replies to the question message
    -> Bot detects reply, resolves the Future
    -> Relay returns answer as HTTP response
    -> Playbook continues with the answer

  When playbook completes (two paths):
    Push-based (HTTP Request block in playbook step-5):
      -> Playbook POSTs to https://webhook.schubert.life/playbook/result
      -> Relay posts result to Discord
    Poll-based (watchdog polls status endpoint):
      -> Watchdog polls {WEBHOOK_URL}/threads/{thread_id}/status
      -> On "completed": download deliverables, post to Discord
      -> On "failed"/"stopped": post error to Discord
      -> On "awaiting_user_response": post notification to Discord

Robustness safeguards:
  - Persistent thread tracking: active_threads saved to JSON file, restored on restarts
  - Direct Discord webhook fallback: if bot channel send fails, posts to Discord webhook URL
  - Watchdog timer: background task detects stuck threads and notifies Discord
  - Status polling: watchdog polls WRITER status endpoint for completion/failure detection
  - Deliverables download: on completion, fetches ZIP deliverables and posts to Discord
  - Double-post prevention: result_posted flag prevents both push and poll paths notifying

Endpoints (added to existing webhook handler aiohttp app on port 8095):
  POST /playbook/ask     — receive a question from a playbook
  POST /playbook/result  — receive a final result from a playbook
  POST /playbook/log     — receive a progress update from a playbook
  GET  /playbook/health  — health check
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from aiohttp import web
import discord

logger = logging.getLogger("schubert-bot.playbook-relay")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PLAYBOOK_CONFIG_PATH = "/opt/Project-Tango/data/playbook_webhooks.json"
THREAD_STATE_PATH = "/opt/Project-Tango/data/playbook_thread_state.json"
DEFAULT_TIMEOUT = 300  # 5 minutes for user response
WEBHOOK_BASE = "https://app.writer.com/webhook/triggers/playbook"

# Watchdog: notify if a thread has been active longer than this
WATCHDOG_THRESHOLD_SEC = 1800  # 30 minutes
WATCHDOG_INTERVAL_SEC = 300    # check every 5 minutes

# Status polling: poll each active thread's status on every watchdog tick
POLL_STATUS_ENABLED = True
POLL_STATUS_INTERVAL_SEC = WATCHDOG_INTERVAL_SEC  # poll alongside watchdog

# Direct Discord webhook fallback (loaded from environment)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_WEBHOOK_FALLBACK_CHANNEL_NAME = os.environ.get(
    "DISCORD_WEBHOOK_FALLBACK_CHANNEL_NAME", "Schubert Bot Channel"
)

# Deliverables download delay after completion (seconds)
DELIVERABLES_START_DELAY_SEC = 5
DELIVERABLES_MAX_ATTEMPTS = 10
DELIVERABLES_RETRY_INTERVAL_SEC = 10


class PlaybookRelay:
    """
    Bridges WRITER Agent playbook webhooks to Discord.

    Add routes to the existing webhook handler's aiohttp app via
    ``relay.add_routes(app)`` so they're accessible at
    ``https://webhook.schubert.life/playbook/*``.
    """

    def __init__(self, bot: discord.Client, channel_id: int):
        self.bot = bot
        self.channel_id = channel_id

        # question_id -> asyncio.Future (the blocking HTTP response)
        self.pending_questions: dict[str, asyncio.Future] = {}
        # discord_message_id -> question_id (for reply detection)
        self.question_messages: dict[int, str] = {}
        # thread_id -> metadata
        self.active_threads: dict[str, dict] = {}
        # playbook_key -> config
        self.playbook_configs: dict[str, dict] = {}

        # Watchdog task
        self._watchdog_task: Optional[asyncio.Task] = None

        self._load_configs()
        self._load_thread_state()

    # -------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------

    def _load_configs(self):
        """Load playbook webhook configurations from JSON file."""
        try:
            with open(PLAYBOOK_CONFIG_PATH) as f:
                self.playbook_configs = json.load(f)
            logger.info(
                "Loaded %d playbook configs: %s",
                len(self.playbook_configs),
                ", ".join(self.playbook_configs.keys()),
            )
        except FileNotFoundError:
            self.playbook_configs = {}
            logger.warning("Playbook config not found at %s", PLAYBOOK_CONFIG_PATH)
        except Exception as e:
            self.playbook_configs = {}
            logger.error("Failed to load playbook configs: %s", e)

    def reload_configs(self):
        """Reload playbook configs (call after editing the config file)."""
        self._load_configs()

    def list_playbooks(self) -> list[dict]:
        """Return a list of available playbook configs for display."""
        result = []
        for key, cfg in self.playbook_configs.items():
            result.append({
                "key": key,
                "name": cfg.get("name", key),
                "description": cfg.get("description", ""),
            })
        return result

    # -------------------------------------------------------------------
    # Persistent thread state
    # -------------------------------------------------------------------

    def _load_thread_state(self):
        """Load active_threads from persistent JSON file (survives bot restarts)."""
        try:
            with open(THREAD_STATE_PATH) as f:
                self.active_threads = json.load(f)
            logger.info(
                "Restored %d active thread(s) from persistent state",
                len(self.active_threads),
            )
        except FileNotFoundError:
            self.active_threads = {}
        except Exception as e:
            logger.error("Failed to load thread state: %s", e)
            self.active_threads = {}

    def _save_thread_state(self):
        """Save active_threads to persistent JSON file."""
        try:
            with open(THREAD_STATE_PATH, "w") as f:
                json.dump(self.active_threads, f, indent=2)
        except Exception as e:
            logger.error("Failed to save thread state: %s", e)

    # -------------------------------------------------------------------
    # Route registration
    # -------------------------------------------------------------------

    def add_routes(self, app: web.Application):
        """Add relay routes to an existing aiohttp app."""
        app.router.add_post("/playbook/ask", self._handle_ask)
        app.router.add_post("/playbook/result", self._handle_result)
        app.router.add_post("/playbook/log", self._handle_log)
        app.router.add_get("/playbook/health", self._health_check)
        logger.info("Playbook relay routes registered on port %d", 8095)

        # Start the watchdog background task (includes status polling)
        self._start_watchdog()

    # -------------------------------------------------------------------
    # Webhook trigger
    # -------------------------------------------------------------------

    async def trigger_playbook(self, playbook_key: str, inputs=None) -> dict:
        """
        Trigger a playbook via its webhook.

        Returns ``{"thread_id": "...", "status": "running"}`` on success,
        or ``{"error": "..."}`` on failure.
        """
        config = self.playbook_configs.get(playbook_key)
        if not config:
            available = ", ".join(self.playbook_configs.keys()) or "(none configured)"
            return {"error": f"Unknown playbook '{playbook_key}'. Available: {available}"}

        playbook_id = config["playbook_id"]
        api_key = config["api_key"]
        url = f"{WEBHOOK_BASE}/{playbook_id}"

        payload = {"inputs": inputs if inputs is not None else []}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.json()
                    if resp.status == 200:
                        thread_id = body.get("thread_id", "")
                        self.active_threads[thread_id] = {
                            "playbook": playbook_key,
                            "playbook_name": config.get("name", playbook_key),
                            "playbook_id": playbook_id,
                            "started_at": datetime.now(timezone.utc).isoformat(),
                            "notified_stuck": False,
                            "result_posted": False,
                            "status": "running",
                            # Store webhook_url and api_key for polling access
                            "webhook_url": url,
                            "api_key": api_key,
                        }
                        self._save_thread_state()
                        logger.info(
                            "Playbook '%s' triggered: thread_id=%s",
                            playbook_key, thread_id,
                        )
                        return body
                    else:
                        logger.error(
                            "Playbook trigger failed: HTTP %d %s",
                            resp.status, body,
                        )
                        return {"error": f"HTTP {resp.status}: {body}"}
        except asyncio.TimeoutError:
            return {"error": "Webhook request timed out (30s)"}
        except Exception as e:
            logger.error("Playbook trigger error: %s", e)
            return {"error": str(e)}

    # -------------------------------------------------------------------
    # HTTP endpoints
    # -------------------------------------------------------------------

    async def _health_check(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "service": "playbook-relay",
            "pending_questions": len(self.pending_questions),
            "active_threads": len(self.active_threads),
            "configured_playbooks": len(self.playbook_configs),
            "discord_webhook_fallback": bool(DISCORD_WEBHOOK_URL),
            "watchdog_running": self._watchdog_task is not None and not self._watchdog_task.done(),
            "status_polling_enabled": POLL_STATUS_ENABLED,
        })

    async def _handle_ask(self, request: web.Request) -> web.Response:
        """
        Handle a question from a playbook.

        Posts the question to Discord, then blocks the HTTP response until
        the Discord user replies (or timeout).
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"error": "invalid JSON body"}, status=400,
            )

        question_id = data.get("question_id") or str(uuid.uuid4())
        thread_id = data.get("thread_id", "unknown")
        q_type = data.get("type", "ask")
        message_text = data.get("message", "No message provided")
        options = data.get("options", [])
        suggestion = data.get("suggestion", "")
        timeout = data.get("timeout", DEFAULT_TIMEOUT)

        logger.info(
            "Playbook question: id=%s type=%s thread=%s",
            question_id[:8], q_type, thread_id[:8],
        )

        # Create a Future for the answer
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self.pending_questions[question_id] = future

        # Build and post the Discord embed
        embed = self._build_question_embed(
            q_type, message_text, options, suggestion, thread_id, question_id,
        )

        discord_msg = None
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.channel_id)

            discord_msg = await channel.send(embed=embed)
            self.question_messages[discord_msg.id] = question_id

            # Add number reactions for choice questions
            if q_type == "choice" and options:
                number_emojis = [
                    "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
                    "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
                ]
                for i in range(min(len(options), 10)):
                    try:
                        await discord_msg.add_reaction(number_emojis[i])
                    except Exception:
                        pass  # reaction add can fail if emoji is unavailable

        except Exception as e:
            logger.error("Failed to post question to Discord: %s", e)
            self.pending_questions.pop(question_id, None)
            return web.json_response(
                {"error": f"Discord post failed: {e}"}, status=500,
            )

        # Block until the Discord user answers or timeout
        try:
            answer = await asyncio.wait_for(future, timeout=timeout)
            self._cleanup_question(question_id, discord_msg)

            # Edit the Discord message to show the answer
            try:
                answered_embed = self._build_answered_embed(embed, answer)
                await discord_msg.edit(embed=answered_embed)
            except Exception:
                pass  # edit is best-effort

            return web.json_response({
                "question_id": question_id,
                "answer": answer,
                "status": "answered",
            })

        except asyncio.TimeoutError:
            self._cleanup_question(question_id, discord_msg)

            # Edit the Discord message to show timeout
            try:
                timeout_embed = self._build_timeout_embed(embed)
                await discord_msg.edit(embed=timeout_embed)
            except Exception:
                pass

            logger.warning("Question %s timed out after %ds", question_id[:8], timeout)
            return web.json_response(
                {
                    "question_id": question_id,
                    "answer": None,
                    "status": "timeout",
                },
                status=408,
            )

    async def _handle_result(self, request: web.Request) -> web.Response:
        """Handle a final result from a playbook (push-based). Posts to Discord."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        thread_id = data.get("thread_id", "unknown")
        result_text = data.get("result", "")
        playbook_name = data.get("playbook_name", "")

        thread_meta = self.active_threads.get(thread_id, {})
        if not playbook_name:
            playbook_name = thread_meta.get("playbook_name", "Unknown Playbook")

        logger.info("Playbook result received (push): thread=%s", thread_id[:8])

        # Double-post prevention: skip if polling already posted the result
        if thread_meta.get("result_posted", False):
            logger.info("Result already posted for thread %s, skipping push", thread_id[:8])
            return web.json_response({"status": "already_posted"})

        # Mark as posted to prevent polling from double-posting
        self.active_threads[thread_id]["result_posted"] = True
        self.active_threads[thread_id]["status"] = "completed"
        self._save_thread_state()

        # Post the result to Discord
        await self._post_result_to_discord(thread_id, playbook_name, result_text, "Push (step-5)")

        self.active_threads.pop(thread_id, None)
        self._save_thread_state()
        return web.json_response({"status": "posted"})

    async def _handle_log(self, request: web.Request) -> web.Response:
        """Handle a progress update from a playbook. Posts to Discord."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        thread_id = data.get("thread_id", "unknown")
        message_text = data.get("message", "")

        logger.info("Playbook log: thread=%s msg=%s", thread_id[:8], message_text[:100])

        posted = False
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.channel_id)
            await channel.send(
                f"📋 **Playbook Update** (`{thread_id[:8]}`): {message_text[:1900]}"
            )
            posted = True
        except Exception as e:
            logger.error("Failed to post log to Discord via bot: %s", e)

        if not posted:
            await self._post_to_discord_webhook(
                f"📋 **Playbook Update** (`{thread_id[:8]}`): {message_text[:1900]}"
            )

        return web.json_response({"status": "posted"})

    # -------------------------------------------------------------------
    # Status polling
    # -------------------------------------------------------------------

    async def _poll_thread_status(self, thread_id: str, webhook_url: str, api_key: str) -> Optional[dict]:
        """
        Poll the WRITER status endpoint for a single thread.

        Returns the status JSON dict on success, None on failure.
        """
        status_url = f"{webhook_url}/threads/{thread_id}/status"
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    status_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(
                            "Status poll failed for %s: HTTP %d",
                            thread_id[:8], resp.status,
                        )
                        return None
        except Exception as e:
            logger.error("Status poll error for %s: %s", thread_id[:8], e)
            return None

    async def _download_deliverables(self, thread_id: str, webhook_url: str, api_key: str) -> Optional[bytes]:
        """
        Download deliverables ZIP for a completed thread.

        Retries up to DELIVERABLES_MAX_ATTEMPTS times with DELIVERABLES_RETRY_INTERVAL_SEC
        delay between attempts (the server returns 202 while processing).

        Returns the ZIP bytes on success, None if no ZIP is available.
        """
        deliverables_url = f"{webhook_url}/threads/{thread_id}/deliverables"
        headers = {"Authorization": f"Bearer {api_key}"}

        # Wait before first attempt
        await asyncio.sleep(DELIVERABLES_START_DELAY_SEC)

        for attempt in range(1, DELIVERABLES_MAX_ATTEMPTS + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        deliverables_url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 202:
                            # Not ready yet, retry
                            logger.info(
                                "Deliverables not ready for %s (attempt %d/%d)",
                                thread_id[:8], attempt, DELIVERABLES_MAX_ATTEMPTS,
                            )
                            await asyncio.sleep(DELIVERABLES_RETRY_INTERVAL_SEC)
                            continue

                        if resp.status == 200:
                            content_type = resp.headers.get("content-type", "")
                            body = await resp.read()

                            if "application/zip" in content_type or "application/octet-stream" in content_type:
                                logger.info(
                                    "Deliverables downloaded for %s: %d bytes",
                                    thread_id[:8], len(body),
                                )
                                return body
                            else:
                                # 200 but not a ZIP — likely JSON saying no deliverables
                                logger.info(
                                    "Deliverables for %s returned 200 but content-type=%s",
                                    thread_id[:8], content_type,
                                )
                                return None

                        logger.warning(
                            "Deliverables fetch failed for %s: HTTP %d",
                            thread_id[:8], resp.status,
                        )
                        return None
            except Exception as e:
                logger.error("Deliverables download error for %s: %s", thread_id[:8], e)
                await asyncio.sleep(DELIVERABLES_RETRY_INTERVAL_SEC)

        logger.warning("Deliverables download timed out for %s", thread_id[:8])
        return None

    async def _handle_polled_completion(self, thread_id: str, meta: dict, status_data: dict):
        """
        Handle a thread that polling detected as completed.

        Downloads deliverables and posts results to Discord.
        """
        playbook_name = meta.get("playbook_name", "Unknown Playbook")
        webhook_url = meta.get("webhook_url", "")
        api_key = meta.get("api_key", "")

        # Double-post prevention
        if meta.get("result_posted", False):
            logger.info("Result already posted for %s, skipping poll completion", thread_id[:8])
            return

        # Mark as posted
        self.active_threads[thread_id]["result_posted"] = True
        self.active_threads[thread_id]["status"] = "completed"
        self._save_thread_state()

        # Try to download deliverables
        deliverables_zip = None
        if webhook_url and api_key:
            deliverables_zip = await self._download_deliverables(thread_id, webhook_url, api_key)

        # Build result text
        if deliverables_zip:
            result_text = (
                f"Playbook completed successfully. Deliverables downloaded ({len(deliverables_zip)} bytes ZIP).\n"
                f"Completed at: {status_data.get('completed_at', 'unknown')}"
            )
        else:
            result_text = (
                f"Playbook completed successfully (no downloadable deliverables).\n"
                f"Completed at: {status_data.get('completed_at', 'unknown')}"
            )

        await self._post_result_to_discord(thread_id, playbook_name, result_text, "Poll (status endpoint)")

        # Clean up
        self.active_threads.pop(thread_id, None)
        self._save_thread_state()

    async def _handle_polled_failure(self, thread_id: str, meta: dict, status_data: dict):
        """
        Handle a thread that polling detected as failed or stopped.
        """
        playbook_name = meta.get("playbook_name", "Unknown Playbook")
        error = status_data.get("error", "No error details provided")
        status = status_data.get("status", "unknown")

        # Double-post prevention
        if meta.get("result_posted", False):
            logger.info("Result already posted for %s, skipping poll failure", thread_id[:8])
            return

        self.active_threads[thread_id]["result_posted"] = True
        self.active_threads[thread_id]["status"] = status
        self._save_thread_state()

        result_text = f"Playbook finished with status: **{status}**\nError: {error}"

        embed = discord.Embed(
            title=f"❌ Playbook {status.title()}: {playbook_name}",
            description=result_text[:4000],
            color=0xff0000,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
        embed.set_footer(text="WRITER Agent Playbook Webhook (poll-detected)")

        posted = False
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.channel_id)
            await channel.send(embed=embed)
            posted = True
        except Exception as e:
            logger.error("Failed to post failure to Discord via bot: %s", e)

        if not posted:
            await self._post_to_discord_webhook(
                f"❌ **Playbook {status.title()}: {playbook_name}**\n"
                f"Thread: `{thread_id}`\n\n"
                f"{result_text[:1800]}"
            )

        self.active_threads.pop(thread_id, None)
        self._save_thread_state()

    async def _handle_polled_awaiting(self, thread_id: str, meta: dict, status_data: dict):
        """
        Handle a thread that polling detected as awaiting_user_response.

        Posts a notification to Discord so the user knows the playbook
        is waiting for input in the WRITER app.
        """
        playbook_name = meta.get("playbook_name", "Unknown Playbook")

        # Only notify once per awaiting state
        if meta.get("notified_awaiting", False):
            return

        self.active_threads[thread_id]["notified_awaiting"] = True
        self.active_threads[thread_id]["status"] = "awaiting_user_response"
        self._save_thread_state()

        message = (
            f"⏸️ **Playbook Awaiting Input: {playbook_name}**\n"
            f"Thread: `{thread_id}`\n\n"
            f"This playbook is waiting for your input. "
            f"If a question appeared as an embed above, reply to it to continue.\n"
            f"If no question appeared, the playbook hit a native confirmation gate "
            f"before reaching the Discord relay step. Try running it again — the "
            f"updated playbook now asks its first question through Discord."
        )

        posted = False
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.channel_id)
            await channel.send(message)
            posted = True
        except Exception as e:
            logger.error("Failed to post awaiting notification to Discord via bot: %s", e)

        if not posted:
            await self._post_to_discord_webhook(message)

    # -------------------------------------------------------------------
    # Discord posting helpers
    # -------------------------------------------------------------------

    async def _post_result_to_discord(self, thread_id: str, playbook_name: str, result_text: str, source: str):
        """Post a completion result to Discord via bot channel or webhook fallback."""
        description = result_text[:4000] if result_text else "No result returned"

        embed = discord.Embed(
            title=f"✅ Playbook Complete: {playbook_name}",
            description=description,
            color=0x00ff00,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
        embed.add_field(name="Detected via", value=source, inline=True)
        embed.set_footer(text="WRITER Agent Playbook Webhook")

        posted = False
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.channel_id)
            await channel.send(embed=embed)
            posted = True
        except Exception as e:
            logger.error("Failed to post result to Discord via bot: %s", e)

        if not posted:
            await self._post_to_discord_webhook(
                f"✅ **Playbook Complete: {playbook_name}**\n"
                f"Thread: `{thread_id}`\n"
                f"Detected via: {source}\n\n"
                f"{description}"
            )

    async def _post_to_discord_webhook(self, content: str):
        """
        Post a message directly to the Discord webhook URL.

        This is a fallback that works independently of the bot's Discord
        gateway connection — it uses the raw Discord webhook REST API.
        """
        if not DISCORD_WEBHOOK_URL:
            logger.error("Discord webhook fallback URL not configured")
            return

        payload = {"content": content[:2000]}  # Discord message limit is 2000 chars
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    DISCORD_WEBHOOK_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 204):
                        logger.info("Posted to Discord via webhook fallback")
                    else:
                        body = await resp.text()
                        logger.error(
                            "Discord webhook fallback failed: HTTP %d %s",
                            resp.status, body[:200],
                        )
        except Exception as e:
            logger.error("Discord webhook fallback error: %s", e)

    # -------------------------------------------------------------------
    # Watchdog timer (with status polling)
    # -------------------------------------------------------------------

    def _start_watchdog(self):
        """Start the background watchdog task (includes status polling)."""
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            logger.info(
                "Watchdog started: threshold=%ds interval=%ds polling=%s",
                WATCHDOG_THRESHOLD_SEC, WATCHDOG_INTERVAL_SEC, POLL_STATUS_ENABLED,
            )

    async def _watchdog_loop(self):
        """Background loop that polls thread statuses and checks for stuck threads."""
        while True:
            try:
                await asyncio.sleep(WATCHDOG_INTERVAL_SEC)
                await self._poll_all_threads()
                await self._check_stuck_threads()
            except asyncio.CancelledError:
                logger.info("Watchdog task cancelled")
                break
            except Exception as e:
                logger.error("Watchdog error: %s", e)

    async def _poll_all_threads(self):
        """Poll the status endpoint for every active thread and handle state changes."""
        if not POLL_STATUS_ENABLED or not self.active_threads:
            return

        for thread_id, meta in list(self.active_threads.items()):
            # Skip threads that already had their result posted
            if meta.get("result_posted", False):
                continue

            webhook_url = meta.get("webhook_url", "")
            api_key = meta.get("api_key", "")

            if not webhook_url or not api_key:
                # Try to reconstruct from config
                playbook_key = meta.get("playbook", "")
                config = self.playbook_configs.get(playbook_key, {})
                playbook_id = config.get("playbook_id", meta.get("playbook_id", ""))
                api_key = config.get("api_key", "")
                webhook_url = f"{WEBHOOK_BASE}/{playbook_id}" if playbook_id else ""

                if not webhook_url or not api_key:
                    logger.warning("Cannot poll thread %s: no webhook_url/api_key", thread_id[:8])
                    continue

            status_data = await self._poll_thread_status(thread_id, webhook_url, api_key)
            if not status_data:
                continue

            status = status_data.get("status", "")
            prev_status = meta.get("status", "")

            # Log status changes
            if status != prev_status:
                logger.info(
                    "Thread %s status changed: %s -> %s",
                    thread_id[:8], prev_status, status,
                )
                self.active_threads[thread_id]["status"] = status
                self._save_thread_state()

            # Handle terminal and intermediate states
            if status == "completed":
                logger.info("Thread %s completed (detected via polling)", thread_id[:8])
                await self._handle_polled_completion(thread_id, meta, status_data)
            elif status in ("failed", "stopped"):
                logger.info("Thread %s %s (detected via polling)", thread_id[:8], status)
                await self._handle_polled_failure(thread_id, meta, status_data)
            elif status == "awaiting_user_response":
                await self._handle_polled_awaiting(thread_id, meta, status_data)
            # "running" — no action needed, watchdog will check elapsed time

    async def _check_stuck_threads(self):
        """Detect threads that have been active longer than the threshold."""
        if not self.active_threads:
            return

        now = datetime.now(timezone.utc)
        stuck = []

        for thread_id, meta in list(self.active_threads.items()):
            # Skip threads that already had their result posted
            if meta.get("result_posted", False):
                continue

            started_str = meta.get("started_at", "")
            if not started_str:
                continue

            try:
                started = datetime.fromisoformat(started_str)
                elapsed = (now - started).total_seconds()

                if elapsed > WATCHDOG_THRESHOLD_SEC and not meta.get("notified_stuck", False):
                    stuck.append((thread_id, meta, elapsed))
            except Exception:
                continue

        for thread_id, meta, elapsed in stuck:
            playbook_name = meta.get("playbook_name", "Unknown")
            elapsed_min = int(elapsed / 60)

            logger.warning(
                "Thread %s stuck for %d minutes (threshold: %d min)",
                thread_id[:8], elapsed_min, WATCHDOG_THRESHOLD_SEC // 60,
            )

            message = (
                f"⏰ **Playbook Watchdog Alert**\n"
                f"Playbook **{playbook_name}** has been running for "
                f"**{elapsed_min} minutes** without completing.\n"
                f"Thread: `{thread_id}`\n\n"
                f"This may indicate the playbook is stuck or still processing. "
                f"The watchdog is polling the status endpoint — if the playbook "
                f"completes or fails, you will be notified automatically."
            )

            # Try bot channel first, then webhook fallback
            posted = False
            try:
                channel = self.bot.get_channel(self.channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(self.channel_id)
                await channel.send(message)
                posted = True
            except Exception as e:
                logger.error("Watchdog: failed to post to Discord via bot: %s", e)

            if not posted:
                await self._post_to_discord_webhook(message)

            # Mark as notified so we don't spam
            self.active_threads[thread_id]["notified_stuck"] = True
            self._save_thread_state()

    # -------------------------------------------------------------------
    # Discord reply resolution
    # -------------------------------------------------------------------

    def resolve_question(self, question_id: str, answer: str) -> bool:
        """
        Resolve a pending question with the user's answer.

        Called by the bot's on_message handler when a user replies to
        a relay question message.
        """
        future = self.pending_questions.get(question_id)
        if future and not future.done():
            future.set_result(answer)
            logger.info("Question %s resolved", question_id[:8])
            return True
        logger.warning("Question %s not found or already resolved", question_id[:8])
        return False

    def get_question_id_for_message(self, discord_msg_id: int) -> Optional[str]:
        """Look up the question_id for a Discord message (for reply detection)."""
        return self.question_messages.get(discord_msg_id)

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _cleanup_question(self, question_id: str, discord_msg=None):
        """Remove a question from pending state."""
        self.pending_questions.pop(question_id, None)
        if discord_msg:
            self.question_messages.pop(discord_msg.id, None)

    def _build_question_embed(
        self, q_type, message_text, options, suggestion, thread_id, question_id,
    ) -> discord.Embed:
        """Build a Discord embed for a playbook question."""
        type_emojis = {"ask": "❓", "choice": "🔀", "form": "📝"}
        emoji = type_emojis.get(q_type, "❓")

        embed = discord.Embed(
            title=f"{emoji} Playbook Question",
            description=message_text[:4000],
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Thread", value=f"`{thread_id[:8]}`", inline=True)
        embed.add_field(name="Type", value=q_type, inline=True)

        if q_type == "choice" and options:
            options_text = "\n".join(
                f"{i + 1}. {opt}" for i, opt in enumerate(options[:10])
            )
            embed.add_field(name="Options", value=options_text, inline=False)
            embed.add_field(
                name="How to answer",
                value="Reply to this message with the option number or name",
                inline=False,
            )
        elif suggestion:
            embed.add_field(name="Suggestion", value=suggestion[:1024], inline=False)
            embed.add_field(
                name="How to answer",
                value="Reply to this message with your answer",
                inline=False,
            )
        else:
            embed.add_field(
                name="How to answer",
                value="Reply to this message with your answer",
                inline=False,
            )

        embed.set_footer(text=f"QID: {question_id[:8]} · Reply to answer")
        return embed

    def _build_answered_embed(self, original: discord.Embed, answer) -> discord.Embed:
        """Update the question embed to show the answer."""
        embed = original.copy()
        embed.color = 0x00ff00
        embed.add_field(name="✅ Answer", value=str(answer)[:1024], inline=False)
        embed.set_footer(text="Answered")
        return embed

    def _build_timeout_embed(self, original: discord.Embed) -> discord.Embed:
        """Update the question embed to show timeout."""
        embed = original.copy()
        embed.color = 0xff0000
        embed.set_footer(text="⏰ Timed out — no answer received")
        return embed
