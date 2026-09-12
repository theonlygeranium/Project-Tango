"""
Webhook Handler — GitHub Integration (Phase 5.3)
================================================
Receives GitHub webhook events (PR notifications, CI failures, push events)
and forwards them as rich Discord embeds to the configured channel.

Runs a small aiohttp web server alongside the Discord bot, listening on a
local port. Caddy reverse-proxies webhook requests from the public URL to
this local endpoint.

Usage:
    webhook = WebhookHandler(bot, channel_id, port=8095)
    await webhook.start()  # starts the HTTP server
    await webhook.stop()   # stops the HTTP server
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import discord
from aiohttp import web

from meetscribe_client import MeetScribeWebhookCache, verify_webhook_signature

if TYPE_CHECKING:
    pass

logger = logging.getLogger("schubert-bot.webhook")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_PORT = 8095
WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")


class WebhookHandler:
    """
    GitHub webhook receiver that forwards events to Discord.

    Listens for POST requests on /webhook/github and renders rich embeds
    for PR events, push events, CI status changes, and issue events.
    """

    def __init__(self, bot: discord.Client, channel_id: int, port: int = DEFAULT_PORT, add_routes_fn=None):
        self.bot = bot
        self.channel_id = channel_id
        self.port = port
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.add_routes_fn = add_routes_fn

    async def start(self):
        """Start the webhook HTTP server."""
        app = web.Application()
        app.router.add_post("/webhook/github", self._handle_github_webhook)
        app.router.add_get("/webhook/health", self._health_check)
        # Register additional routes (e.g. playbook relay) before the router freezes
        if self.add_routes_fn:
            self.add_routes_fn(app)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await self.site.start()
        logger.info(f"Webhook handler listening on 127.0.0.1:{self.port}")

    async def stop(self):
        """Stop the webhook HTTP server."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Webhook handler stopped")

    async def _health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok", "service": "schubert-webhook"})

    async def _handle_github_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming GitHub webhook events."""
        try:
            # Verify signature if secret is configured
            if WEBHOOK_SECRET:
                signature = request.headers.get("X-Hub-Signature-256", "")
                body = await request.read()
                if not self._verify_signature(body, signature):
                    logger.warning("Webhook signature verification failed")
                    return web.json_response({"error": "invalid signature"}, status=403)
                payload = json.loads(body)
            else:
                payload = await request.json()

            event_type = request.headers.get("X-GitHub-Event", "unknown")
            action = payload.get("action", "")

            logger.info(f"GitHub webhook: {event_type}.{action}")

            # Build embed based on event type
            embed = self._build_event_embed(event_type, action, payload)
            if embed:
                await self._send_to_discord(embed)

            return web.json_response({"status": "received", "event": event_type})

        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify the GitHub webhook signature."""
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    def _build_event_embed(
        self, event_type: str, action: str, payload: dict,
    ) -> Optional[discord.Embed]:
        """Build a rich embed for a GitHub webhook event."""

        if event_type == "pull_request":
            return self._build_pr_embed(action, payload)
        elif event_type == "push":
            return self._build_push_embed(payload)
        elif event_type == "issues":
            return self._build_issue_embed(action, payload)
        elif event_type == "check_run" or event_type == "check_suite":
            return self._build_ci_embed(event_type, action, payload)
        elif event_type == "release":
            return self._build_release_embed(action, payload)
        elif event_type == "ping":
            return self._build_ping_embed(payload)
        else:
            return None

    def _build_pr_embed(self, action: str, payload: dict) -> Optional[discord.Embed]:
        """Build embed for pull request events."""
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        sender = payload.get("sender", {})

        number = pr.get("number", "?")
        title = pr.get("title", "Untitled PR")
        url = pr.get("html_url", "")
        state = pr.get("state", "unknown")
        author = sender.get("login", "unknown")
        repo_name = repo.get("full_name", "unknown")

        action_emojis = {
            "opened": "🟢",
            "closed": "🔴",
            "reopened": "🟡",
            "edited": "✏️",
            "synchronize": "🔄",
            "ready_for_review": "👁️",
            "converted_to_draft": "📝",
            "merged": "🟣",
            "labeled": "🏷️",
            "assigned": "👤",
        }
        emoji = action_emojis.get(action, "📋")

        embed = discord.Embed(
            title=f"{emoji} PR #{number} {action}: {title}",
            url=url,
            color=0x24292E,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Repository", value=repo_name, inline=True)
        embed.add_field(name="Author", value=author, inline=True)
        embed.add_field(name="State", value=state, inline=True)

        if action == "opened" or action == "reopened":
            body = pr.get("body", "")[:300] if pr.get("body") else "No description"
            embed.add_field(name="Description", value=body, inline=False)

        embed.set_footer(text="GitHub Webhook — Pull Request")
        return embed

    def _build_push_embed(self, payload: dict) -> Optional[discord.Embed]:
        """Build embed for push events."""
        repo = payload.get("repository", {})
        sender = payload.get("sender", {})
        ref = payload.get("ref", "")
        commits = payload.get("commits", [])
        repo_name = repo.get("full_name", "unknown")
        author = sender.get("login", "unknown")
        branch = ref.replace("refs/heads/", "") if ref else "unknown"
        compare_url = payload.get("compare", "")

        embed = discord.Embed(
            title=f"⬆️ Push to {branch}: {len(commits)} commit(s)",
            url=compare_url,
            color=0x24292E,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Repository", value=repo_name, inline=True)
        embed.add_field(name="Pushed by", value=author, inline=True)

        if commits:
            commit_lines = []
            for commit in commits[:5]:
                msg = commit.get("message", "No message").split("\n")[0][:80]
                sha = commit.get("id", "")[:7]
                commit_lines.append(f"`{sha}` {msg}")
            embed.add_field(
                name="Commits",
                value="\n".join(commit_lines),
                inline=False,
            )
            if len(commits) > 5:
                embed.add_field(name="More", value=f"... and {len(commits) - 5} more", inline=False)

        embed.set_footer(text="GitHub Webhook — Push")
        return embed

    def _build_issue_embed(self, action: str, payload: dict) -> Optional[discord.Embed]:
        """Build embed for issue events."""
        issue = payload.get("issue", {})
        repo = payload.get("repository", {})
        sender = payload.get("sender", {})

        number = issue.get("number", "?")
        title = issue.get("title", "Untitled Issue")
        url = issue.get("html_url", "")
        author = sender.get("login", "unknown")
        repo_name = repo.get("full_name", "unknown")

        action_emojis = {
            "opened": "🟢",
            "closed": "🔴",
            "reopened": "🟡",
            "edited": "✏️",
            "assigned": "👤",
            "labeled": "🏷️",
        }
        emoji = action_emojis.get(action, "📌")

        embed = discord.Embed(
            title=f"{emoji} Issue #{number} {action}: {title}",
            url=url,
            color=0x24292E,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Repository", value=repo_name, inline=True)
        embed.add_field(name="By", value=author, inline=True)

        if action == "opened":
            body = issue.get("body", "")[:300] if issue.get("body") else "No description"
            embed.add_field(name="Description", value=body, inline=False)

        embed.set_footer(text="GitHub Webhook — Issue")
        return embed

    def _build_ci_embed(self, event_type: str, action: str, payload: dict) -> Optional[discord.Embed]:
        """Build embed for CI check events."""
        if event_type == "check_run":
            check = payload.get("check_run", {})
            name = check.get("name", "Unknown Check")
            status = check.get("status", "unknown")
            conclusion = check.get("conclusion", "")
            url = check.get("html_url", "")
            repo = payload.get("repository", {})
            repo_name = repo.get("full_name", "unknown")

            status_emoji = "✅" if conclusion == "success" else "❌" if conclusion == "failure" else "🔄"
            embed = discord.Embed(
                title=f"{status_emoji} CI: {name} — {conclusion or status}",
                url=url,
                color=0x2ECC71 if conclusion == "success" else 0xE74C3C if conclusion == "failure" else 0xF39C12,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Repository", value=repo_name, inline=True)
            embed.add_field(name="Status", value=status, inline=True)
            embed.set_footer(text="GitHub Webhook — CI Check")
            return embed

        elif event_type == "check_suite":
            suite = payload.get("check_suite", {})
            conclusion = suite.get("conclusion", "")
            url = suite.get("html_url", "")
            repo = payload.get("repository", {})
            repo_name = repo.get("full_name", "unknown")

            status_emoji = "✅" if conclusion == "success" else "❌" if conclusion == "failure" else "🔄"
            embed = discord.Embed(
                title=f"{status_emoji} CI Suite: {conclusion or 'running'}",
                url=url,
                color=0x2ECC71 if conclusion == "success" else 0xE74C3C if conclusion == "failure" else 0xF39C12,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="Repository", value=repo_name, inline=True)
            embed.set_footer(text="GitHub Webhook — CI Suite")
            return embed

        return None

    def _build_release_embed(self, action: str, payload: dict) -> Optional[discord.Embed]:
        """Build embed for release events."""
        release = payload.get("release", {})
        repo = payload.get("repository", {})

        tag = release.get("tag_name", "unknown")
        name = release.get("name", tag)
        url = release.get("html_url", "")
        body = release.get("body", "")[:500] if release.get("body") else "No release notes"
        repo_name = repo.get("full_name", "unknown")
        prerelease = release.get("prerelease", False)

        emoji = "🏷️" if action == "published" else "📦"
        embed = discord.Embed(
            title=f"{emoji} Release {action}: {name}",
            url=url,
            description=body,
            color=0x1ABC9C,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Repository", value=repo_name, inline=True)
        embed.add_field(name="Tag", value=tag, inline=True)
        embed.add_field(name="Pre-release", value="Yes" if prerelease else "No", inline=True)
        embed.set_footer(text="GitHub Webhook — Release")
        return embed

    def _build_ping_embed(self, payload: dict) -> Optional[discord.Embed]:
        """Build embed for webhook ping events (sent when webhook is first configured)."""
        repo = payload.get("repository", {})
        zen = payload.get("zen", "")
        repo_name = repo.get("full_name", "unknown")

        embed = discord.Embed(
            title="🏓 Webhook Connected",
            description=f"GitHub webhook for **{repo_name}** is now active.\n\n*{zen}*",
            color=0x1ABC9C,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="GitHub Webhook — Ping")
        return embed

    async def _send_to_discord(self, embed: discord.Embed):
        """Send an embed to the configured Discord channel."""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send webhook embed to Discord: {e}")


class MeetScribeWebhookHandler:
    """
    MeetScribe webhook receiver that forwards notes.completed events to Discord.

    Adds a POST route at /webhook/meetscribe to the existing aiohttp app.
    Verifies HMAC-SHA256 signatures, caches session metadata, and posts
    rich Discord embeds announcing new meeting notes.

    Designed to be passed as ``add_routes_fn`` to ``WebhookHandler``.
    """

    def __init__(self, bot: discord.Client, channel_id: int):
        self.bot = bot
        self.channel_id = channel_id
        self.cache = MeetScribeWebhookCache()

    def add_routes(self, app: web.Application) -> None:
        """Register the MeetScribe webhook route on the aiohttp app."""
        app.router.add_post("/webhook/meetscribe", self._handle_meetscribe_webhook)

    async def _handle_meetscribe_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming MeetScribe webhook events."""
        try:
            body = await request.read()
            signature = request.headers.get("X-MeetScribe-Signature", "")

            if not verify_webhook_signature(body, signature):
                logger.warning("MeetScribe webhook signature verification failed")
                return web.json_response({"error": "invalid signature"}, status=401)

            payload = json.loads(body)
            event = payload.get("event", "")

            logger.info(f"MeetScribe webhook: {event}")

            if event == "notes.completed":
                await self.cache.handle_webhook(payload)
                embed = self._build_notes_embed(payload)
                if embed:
                    await self._send_to_discord(embed)

            return web.json_response({"status": "received"})

        except Exception as e:
            logger.error(f"MeetScribe webhook error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    def _build_notes_embed(self, payload: dict) -> Optional[discord.Embed]:
        """Build a rich Discord embed for a notes.completed event."""
        data = payload.get("data", {})

        title = data.get("title", "Untitled Meeting")
        session_id = data.get("session_id", "?")
        started_at = data.get("started_at", "")
        duration_seconds = data.get("duration_seconds")
        status = data.get("status", "completed")
        summary = data.get("summary", "")

        if started_at:
            date_str = started_at[:10] if len(started_at) >= 10 else started_at
        else:
            date_str = "—"

        if duration_seconds is not None:
            minutes, seconds = divmod(int(duration_seconds), 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                duration_str = f"{hours}h {minutes}m"
            else:
                duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = "—"

        description = summary[:1000] if summary else "No summary available."
        description = description + "\n\n*Ask me about this meeting!*"

        embed = discord.Embed(
            title=f"📝 New Meeting Notes: {title}",
            description=description,
            color=0x2930FF,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Session ID", value=str(session_id), inline=True)
        embed.add_field(name="Date", value=date_str, inline=True)
        embed.add_field(name="Duration", value=duration_str, inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.set_footer(text="MeetScribe Webhook — Notes Completed")
        return embed

    async def _send_to_discord(self, embed: discord.Embed):
        """Send an embed to the configured Discord channel."""
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send MeetScribe webhook embed to Discord: {e}")
