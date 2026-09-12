"""
Discord UX Utilities — Shared Helper Functions for Bot UX
==========================================================
Provides reusable Discord-specific utilities for typing indicators,
silent messaging, thread heuristics, and embed validation.

Functions:
    keep_typing(channel, stop_event, interval=8.0)
        Continuously trigger Discord typing indicator until stop_event is set.

    send_silent(channel, **kwargs)
        Send a message with silent=True to suppress push notifications.

    should_use_thread(user_input) -> bool
        Heuristic to decide if an agent task should get its own thread.

    session_channel_id(channel) -> int
        Parent-channel session key so threads share conversation history.

    safe_create_thread(message, name, auto_archive_duration=60)
        create_thread wrapper that never raises on thread/DM/guild-missing.

    validate_embed_limits(title, description, fields) -> (bool, str)
        Validate Discord embed field limits before sending.

Constants:
    SUPPRESS_NOTIFICATIONS — Discord message flag (1 << 12)
    IS_COMPONENTS_V2 — Discord message flag (1 << 15)

Usage:
    from discord_ux_utils import keep_typing, send_silent, should_use_thread

    # Typing indicator
    stop_event = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(channel, stop_event))
    # ... do work ...
    stop_event.set()
    await typing_task

    # Silent message
    await send_silent(channel, content="Background task complete")

    # Thread decision
    if should_use_thread(user_message):
        thread = await channel.create_thread(name="Agent Task")
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from discord.abc import Messageable

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Discord Message Flags
# ---------------------------------------------------------------------------

SUPPRESS_NOTIFICATIONS = 1 << 12  # Silent message (no push notification)
IS_COMPONENTS_V2 = 1 << 15        # Components v2 flag


# ---------------------------------------------------------------------------
# Typing Indicator
# ---------------------------------------------------------------------------

async def keep_typing(
    channel: Messageable,
    stop_event: asyncio.Event,
    interval: float = 8.0,
) -> None:
    """
    Continuously trigger Discord typing indicator until stop_event is set.

    Discord's typing indicator expires after 10 seconds, so this function
    re-triggers it every `interval` seconds (default 8.0) to maintain
    the visual feedback during long-running operations.

    Args:
        channel: Discord channel or thread to send typing indicator to
        stop_event: asyncio.Event to signal when to stop typing
        interval: seconds between typing triggers (default 8.0)

    Raises:
        No exceptions — handles asyncio.CancelledError and discord errors gracefully

    Usage:
        stop_event = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(channel, stop_event))
        try:
            # ... perform long operation ...
        finally:
            stop_event.set()
            await typing_task

    Example:
        async def handle_long_task(channel):
            stop_event = asyncio.Event()
            typing_task = asyncio.create_task(
                keep_typing(channel, stop_event, interval=8.0)
            )
            try:
                await some_long_operation()
            finally:
                stop_event.set()
                await typing_task
    """
    typing_cm = None
    try:
        while not stop_event.is_set():
            typing_cm = channel.typing()
            try:
                await typing_cm.__aenter__()
            except discord.HTTPException as exc:
                logger.debug(f"Typing indicator failed: {exc}")
                typing_cm = None
                continue
            except discord.Forbidden:
                logger.warning(
                    f"No permission to send typing indicator in {channel}"
                )
                break
            except Exception as exc:
                logger.error(f"Unexpected error in keep_typing: {exc}", exc_info=True)
                break

            # Wait for interval or until stop_event is set
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=interval,
                )
                # stop_event was set — exit the typing context before breaking
                await typing_cm.__aexit__(None, None, None)
                typing_cm = None
                break
            except asyncio.TimeoutError:
                # Interval elapsed — exit this typing context and re-trigger
                await typing_cm.__aexit__(None, None, None)
                typing_cm = None
                continue

    except asyncio.CancelledError:
        logger.debug("keep_typing task cancelled")
        raise  # Re-raise to propagate cancellation
    finally:
        # Ensure the typing context is always exited
        if typing_cm is not None:
            try:
                await typing_cm.__aexit__(None, None, None)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Silent Messaging
# ---------------------------------------------------------------------------

async def send_silent(channel: Messageable, **kwargs) -> discord.Message:
    """
    Send a message with silent=True to suppress push notifications.

    Wrapper around channel.send() that forces the SUPPRESS_NOTIFICATIONS
    flag, preventing push notifications on mobile devices. Useful for
    background updates, status messages, and non-urgent notifications.

    Args:
        channel: Discord channel or thread to send message to
        **kwargs: all arguments to pass through to channel.send()

    Returns:
        discord.Message: the sent message

    Raises:
        discord errors propagate to caller

    Usage:
        await send_silent(channel, content="Background task complete")
        await send_silent(channel, embed=status_embed)

    Example:
        # Silent status update
        await send_silent(
            channel,
            content="Deployment finished",
            embed=discord.Embed(
                title="Status",
                description="All services restarted successfully",
            ),
        )
    """
    kwargs["silent"] = True
    return await channel.send(**kwargs)


# ---------------------------------------------------------------------------
# Thread Heuristics
# ---------------------------------------------------------------------------

def should_use_thread(user_input: str) -> bool:
    """
    Heuristic to decide if an agent task should get its own thread.

    Creates threads for:
    - Explicit user request ("in a thread")
    - Long inputs (> 200 characters)
    - Multi-step tasks (contains "then", "after that", "also", etc.)

    Threads help keep the main channel clean and allow parallel agent
    tasks without message interleaving.

    Args:
        user_input: the user's message text

    Returns:
        bool: True if a thread should be created, False otherwise

    Usage:
        if should_use_thread(user_message):
            thread = await channel.create_thread(
                name=f"Agent Task {datetime.now().strftime('%H:%M')}",
                auto_archive_duration=60,
            )
            # ... run agent in thread ...

    Example:
        >>> should_use_thread("!status")
        False
        >>> should_use_thread("deploy the backend then restart nginx")
        True
        >>> should_use_thread("in a thread: check logs")
        True
        >>> should_use_thread("a" * 250)
        True
    """
    # Explicit thread request
    if "in a thread" in user_input.lower():
        return True

    # Long input suggests complex task
    if len(user_input) > 200:
        return True

    # Multi-step indicators (case-insensitive word boundary matches)
    multi_step_pattern = re.compile(
        r"\b(then|after that|also|additionally|next|finally)\b",
        re.IGNORECASE,
    )
    if multi_step_pattern.search(user_input):
        return True

    return False


# ---------------------------------------------------------------------------
# Thread-safe Discord helpers (guild-info / already-in-thread / session key)
# ---------------------------------------------------------------------------

def session_channel_id(channel) -> int:
    """Stable session key: Discord threads share their parent channel history."""
    parent = getattr(channel, "parent_id", None)
    if parent:
        return int(parent)
    cid = getattr(channel, "id", channel)
    return int(cid)


def can_create_thread(message) -> bool:
    """False if already in a thread, DM, or the message cannot spawn a thread.

    discord.py raises ValueError("This message does not have guild info attached.")
    when create_thread is called on a thread/DM/uncached message. That is NOT
    an HTTPException, so callers that only catch HTTPException leak it as an
    agent error after a successful reply.
    """
    if message is None:
        return False
    channel = getattr(message, "channel", None)
    if channel is None:
        return False
    if isinstance(channel, discord.Thread):
        return False
    if isinstance(channel, discord.DMChannel):
        return False
    if getattr(message, "guild", None) is None:
        return False
    if not hasattr(message, "create_thread"):
        return False
    if getattr(message, "thread", None) is not None:
        return False
    flags = getattr(message, "flags", None)
    if flags is not None and getattr(flags, "has_thread", False):
        return False
    return True


async def safe_create_thread(
    message,
    name: str,
    auto_archive_duration: int = 60,
):
    """Create a thread from a channel message. Returns None on any failure."""
    if not can_create_thread(message):
        return None
    name = (name or "Discussion").replace(chr(10), " ")[:100]
    try:
        return await message.create_thread(
            name=name,
            auto_archive_duration=auto_archive_duration,
        )
    except discord.HTTPException as e:
        if getattr(e, "code", None) == 160004:
            logger.debug("create_thread already exists: %s", e)
            return getattr(message, "thread", None)
        logger.warning("create_thread skipped: %s", e)
        return None
    except (ValueError, TypeError) as e:
        logger.warning("create_thread skipped: %s", e)
        return None


# ---------------------------------------------------------------------------
# Embed Validation
# ---------------------------------------------------------------------------

def validate_embed_limits(
    title: str,
    description: str,
    fields: list[dict],
) -> tuple[bool, str]:
    """
    Validate Discord embed field limits before sending.

    Discord enforces strict limits on embed fields. This function checks
    all constraints and returns a validation result with a descriptive
    error message if validation fails.

    Limits:
        - Title: max 256 characters
        - Description: max 4096 characters
        - Fields: max 25 fields
        - Field name: max 256 characters
        - Field value: max 1024 characters
        - Total text: max 6000 characters across all fields

    Args:
        title: embed title string
        description: embed description string
        fields: list of field dicts with "name" and "value" keys

    Returns:
        tuple[bool, str]: (is_valid, error_message)
            - is_valid: True if all limits satisfied, False otherwise
            - error_message: empty string if valid, descriptive error if not

    Usage:
        title = "Status Report"
        description = "Full system health check results"
        fields = [
            {"name": "CPU", "value": "45%", "inline": True},
            {"name": "Memory", "value": "8.2 GB / 16 GB", "inline": True},
        ]

        is_valid, error = validate_embed_limits(title, description, fields)
        if not is_valid:
            logger.error(f"Embed validation failed: {error}")
            return

        embed = discord.Embed(title=title, description=description)
        for field in fields:
            embed.add_field(
                name=field["name"],
                value=field["value"],
                inline=field.get("inline", False),
            )
        await channel.send(embed=embed)

    Example:
        >>> validate_embed_limits("OK", "OK", [])
        (True, '')
        >>> validate_embed_limits("x" * 300, "OK", [])
        (False, 'Title exceeds 256 characters (got 300)')
        >>> validate_embed_limits("OK", "x" * 5000, [])
        (False, 'Description exceeds 4096 characters (got 5000)')
    """
    # Title limit: 256 characters
    if len(title) > 256:
        return False, f"Title exceeds 256 characters (got {len(title)})"

    # Description limit: 4096 characters
    if len(description) > 4096:
        return False, f"Description exceeds 4096 characters (got {len(description)})"

    # Max 25 fields
    if len(fields) > 25:
        return False, f"Exceeds 25 fields limit (got {len(fields)})"

    # Field name and value limits, plus total text calculation
    total_text_length = len(title) + len(description)

    for i, field in enumerate(fields):
        field_name = field.get("name", "")
        field_value = field.get("value", "")

        # Field name limit: 256 characters
        if len(field_name) > 256:
            return (
                False,
                f"Field {i} name exceeds 256 characters (got {len(field_name)})",
            )

        # Field value limit: 1024 characters
        if len(field_value) > 1024:
            return (
                False,
                f"Field {i} value exceeds 1024 characters (got {len(field_value)})",
            )

        total_text_length += len(field_name) + len(field_value)

    # Total text limit: 6000 characters
    if total_text_length > 6000:
        return (
            False,
            f"Total embed text exceeds 6000 characters (got {total_text_length})",
        )

    return True, ""
