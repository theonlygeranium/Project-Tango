"""Unified Discord message handling — fixes 4 production bugs.

Bug 1: 400 Invalid Form Body when content > 2000 chars.
Bug 2: 429 Rate Limited not handled — crashed the bot.
Bug 3: Dr. Cortex AttributeError — Thread.reply() doesn't exist.
Bug 4: Architect UnboundLocalError — thread var referenced before assignment.
Bug 5: Port conflict (8095) — OSError on bound port crashed the bot.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

logger = logging.getLogger(__name__)


class DiscordHandler:
    """Unified Discord send/reply/thread creation with circuit-breaker protection."""

    DISCORD_MESSAGE_LIMIT: int = 2000
    RATE_LIMIT_BACKOFF_BASE: float = 1.0
    RATE_LIMIT_BACKOFF_MAX: float = 30.0

    def __init__(
        self,
        client: Any,
        breakers: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._breakers = breakers
        self._logger = logger or logging.getLogger(__name__)

    async def send(self, target: Any, content: str) -> Any:
        """Send with length validation and rate-limit handling.

        FIX: 400 Invalid Form Body (content >2000 chars), 429 Rate Limited.
        """
        if len(content) > self.DISCORD_MESSAGE_LIMIT:
            return await self._send_chunked(target, content)
        try:
            return await self._breakers.call_discord("send", target.send, content)
        except discord.HTTPException as e:
            if e.status == 429:
                await self._handle_rate_limit(target, content, e)
                return None
            raise

    async def reply_in_thread(self, message: Any, content: str) -> Any:
        """Reply correctly regardless of thread source.

        FIX: Dr. Cortex AttributeError — Thread.reply() doesn't exist.
        """
        if isinstance(message.channel, discord.Thread):
            return await self.send(message.channel, content)
        return await self._breakers.call_discord("reply", message.reply, content)

    async def create_thread(self, parent: Any, name: str, starter_message: str) -> Any:
        """Create thread with null-checking.

        FIX: Architect UnboundLocalError — thread var referenced before assignment.
        """
        thread = await self._breakers.call_discord(
            "create_thread",
            parent.create_thread,
            name=name,
            content=starter_message,
        )
        if thread is None:
            self._logger.error(
                "Thread creation returned None for channel %s", parent.id
            )
            return None
        return thread

    async def bind_port(self, host: str, port: int) -> Any:
        """Bind TCP port with error handling.

        FIX: port conflict (8095) — OSError on bound port crashed the bot.
        """
        try:
            return await asyncio.start_server(
                self._handle_port_connection, host=host, port=port
            )
        except OSError as e:
            self._logger.error("Failed to bind %s:%s — %s", host, port, e)
            return None

    async def _send_chunked(self, target: Any, content: str) -> Any:
        """Split content into chunks under 2000 chars and send each."""
        last_message: Any = None
        for i in range(0, len(content), self.DISCORD_MESSAGE_LIMIT):
            chunk = content[i : i + self.DISCORD_MESSAGE_LIMIT]
            last_message = await self._breakers.call_discord(
                "send", target.send, chunk
            )
        return last_message

    async def _handle_rate_limit(
        self, target: Any, content: str, error: discord.HTTPException
    ) -> None:
        """Apply Retry-After backoff and retry."""
        retry_after = getattr(error, "retry_after", None)
        if retry_after is None:
            retry_after = self.RATE_LIMIT_BACKOFF_BASE
        backoff = min(float(retry_after), self.RATE_LIMIT_BACKOFF_MAX)
        self._logger.warning(
            "Rate limited on %s, backing off for %.2fs", target, backoff
        )
        await asyncio.sleep(backoff)
        try:
            await self._breakers.call_discord("send", target.send, content)
        except discord.HTTPException as e:
            self._logger.error("Retry after rate limit also failed: %s", e)

    async def _handle_port_connection(self, reader: Any, writer: Any) -> None:
        """Handle a port connection (no-op for health check)."""
        try:
            writer.close()
            await writer.wait_closed()
        except Exception as e:
            self._logger.debug("Port connection handler error: %s", e)
