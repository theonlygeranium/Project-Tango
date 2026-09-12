"""Regression tests for DiscordHandler — fixes 4 production bugs."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from nexus.bot.discord_handler import DiscordHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_breakers() -> Any:
    breakers = MagicMock()
    breakers.call_discord = AsyncMock()
    return breakers


@pytest.fixture
def mock_client() -> Any:
    return MagicMock()


@pytest.fixture
def handler(mock_client: Any, mock_breakers: Any) -> DiscordHandler:
    return DiscordHandler(mock_client, mock_breakers)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_reply_in_thread_uses_thread_send(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """message in discord.Thread calls Thread.send(), not Thread.reply()."""
    message = MagicMock()
    thread = MagicMock(spec=discord.Thread)
    thread.id = 12345
    thread.send = AsyncMock(return_value="sent")
    message.channel = thread

    mock_breakers.call_discord.return_value = "sent"

    await handler.reply_in_thread(message, "hello")

    # Should route through breaker's send, not message.reply
    mock_breakers.call_discord.assert_called_once_with("send", thread.send, "hello")


async def test_reply_in_regular_channel_uses_message_reply(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """non-thread message calls Message.reply()."""
    message = MagicMock()
    message.channel = MagicMock()  # Not a Thread
    message.reply = AsyncMock(return_value="replied")

    mock_breakers.call_discord.return_value = "replied"

    await handler.reply_in_thread(message, "hello")

    mock_breakers.call_discord.assert_called_once_with(
        "reply", message.reply, "hello"
    )


async def test_create_thread_null_checks_result(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """create_thread() returning None doesn't raise UnboundLocalError."""
    parent = MagicMock()
    parent.id = 999
    mock_breakers.call_discord.return_value = None

    result = await handler.create_thread(parent, "test-thread", "starter")

    assert result is None


async def test_create_thread_returns_thread_on_success(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """create_thread() returns the thread when creation succeeds."""
    parent = MagicMock()
    parent.id = 999
    thread = MagicMock()
    mock_breakers.call_discord.return_value = thread

    result = await handler.create_thread(parent, "test-thread", "starter")

    assert result is thread


async def test_send_chunks_long_content(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """content >2000 chars is chunked."""
    target = MagicMock()
    target.send = AsyncMock()

    async def _call_discord(endpoint: str, fn: Any, content: str) -> Any:
        return await fn(content)

    mock_breakers.call_discord.side_effect = _call_discord

    long_content = "x" * 5000
    await handler.send(target, long_content)

    # 5000 / 2000 = 3 chunks
    assert mock_breakers.call_discord.call_count == 3


async def test_send_under_limit_sends_once(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """content <=2000 chars sends in single call."""
    target = MagicMock()
    target.send = AsyncMock()

    async def _call_discord(endpoint: str, fn: Any, content: str) -> Any:
        return await fn(content)

    mock_breakers.call_discord.side_effect = _call_discord

    await handler.send(target, "short message")

    assert mock_breakers.call_discord.call_count == 1


async def test_rate_limit_backoff_and_retry(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """429 response triggers backoff and retry."""
    target = MagicMock()
    target.send = AsyncMock()

    error = discord.HTTPException(
        MagicMock(), {"retry_after": 0.01}
    )
    error.status = 429

    mock_breakers.call_discord.side_effect = [
        error,
        "retry_succeeded",
    ]

    with patch("nexus.bot.discord_handler.asyncio.sleep", new_callable=AsyncMock):
        result = await handler.send(target, "hello")

    # First call raises 429, second call succeeds
    assert mock_breakers.call_discord.call_count == 2


async def test_bind_port_returns_none_on_conflict(handler: DiscordHandler) -> None:
    """OSError on bound port returns None."""
    with patch(
        "nexus.bot.discord_handler.asyncio.start_server",
        side_effect=OSError("Address already in use"),
    ):
        result = await handler.bind_port("0.0.0.0", 8095)

    assert result is None


async def test_send_wrapped_by_breaker(
    handler: DiscordHandler, mock_breakers: Any
) -> None:
    """send() routes through CircuitBreakerManager.call_discord."""
    target = MagicMock()
    target.send = AsyncMock()
    mock_breakers.call_discord.return_value = "sent"

    await handler.send(target, "hello")

    mock_breakers.call_discord.assert_called_once_with("send", target.send, "hello")
