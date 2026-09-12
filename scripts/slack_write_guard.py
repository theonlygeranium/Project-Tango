#!/usr/bin/env python3
"""Slack write guard — fleet bots may not post/DM without explicit user approval.

Policy (2026-08-22):
  * Reads (list channels, history, users) are allowed.
  * Any Slack write (post, reply, DM, upload, react, delete, schedule) is
    blocked unless the CURRENT Discord message explicitly asks to write
    to Slack AND names the destination.
  * #general is extra-locked: the user must name #general (or C02AJRK9H).
  * DMs require the user to say DM/direct message (or name the user id).
  * Fail closed: no bound user prompt => deny.

Preferred destinations when named: tango-ops, tango-dev, tango-reports.
"""
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from typing import Any, Optional

_user_prompt: ContextVar[str] = ContextVar("slack_user_prompt", default="")
_approved_bypass: ContextVar[bool] = ContextVar("slack_write_bypass", default=False)

GENERAL_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_GENERAL", "C02AJRK9H")
GENERAL_NAMES = {"general", "#general"}

WRITE_NEEDLES = (
    "post_message",
    "postmessage",
    "reply_to_thread",
    "send_message",
    "add_reaction",
    "upload",
    "create_canvas",
    "schedule",
    "delete_message",
    "update_message",
    "chat_post",
    "conversations_open",
    "open_dm",
    "whisper",
    "files_upload",
)

_INTENT = re.compile(
    r"(?:"
    r"\b(?:please\s+)?"
    r"(?:post|send|share|publish|upload|dm|message|ping)\b"
    r".{0,80}\bslack\b"
    r"|"
    r"\bslack\b.{0,80}\b(?:post|send|share|publish|upload)\b"
    r"|"
    r"\b(?:post|send|share|publish)\b.{0,40}#[\w-]+"
    r"|"
    r"\bslack_post_message\b"
    r"|"
    r"\b(?:dm|direct message|im)\b.{0,40}\bslack\b"
    r"|"
    r"\bslack\b.{0,40}\b(?:dm|direct message|im)\b"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_NEGATION = re.compile(
    r"\b(?:don'?t|do not|never|stop|without)\b.{0,40}\b(?:post|send|share).{0,30}\bslack\b",
    re.IGNORECASE | re.DOTALL,
)

_CHANNEL_HASH = re.compile(r"#([a-z0-9][\w-]{0,79})", re.IGNORECASE)
_SLACK_ID = re.compile(r"\b([CDG][A-Z0-9]{8,})\b")
_USER_ID = re.compile(r"\b(U[A-Z0-9]{8,})\b")
_DM_WORD = re.compile(
    r"\b(dm|dms|direct message|direct messages|im|private message)\b",
    re.IGNORECASE,
)
_NAMED_CHANNELS = (
    "tango-ops",
    "tango-dev",
    "tango-reports",
    "demo-cape-webinars",
    "general",
)


def bind_user_prompt(text: str | None) -> None:
    """Attach the current Discord user message to this asyncio task."""
    _user_prompt.set((text or "").strip())


def bind_user_prompt_from_messages(messages: list | None) -> None:
    """Use the last user-role message (Admiral/Cortex v2 loops)."""
    text = ""
    for item in reversed(messages or []):
        if isinstance(item, dict) and item.get("role") == "user":
            content = item.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            text = str(content)
            break
    bind_user_prompt(text)


def approve_explicit_write() -> None:
    """Bypass for a real UI click (Discord button). Not used by the LLM path."""
    _approved_bypass.set(True)


def current_user_prompt() -> str:
    return _user_prompt.get() or ""


def is_slack_write_tool(name: str) -> bool:
    n = (name or "").lower().replace("-", "_")
    if "slack" not in n:
        return False
    return any(needle in n for needle in WRITE_NEEDLES)


def _target_from_args(arguments: dict[str, Any] | None) -> dict[str, str]:
    args = arguments or {}
    channel = str(
        args.get("channel_id")
        or args.get("channel")
        or args.get("channel_name")
        or args.get("conversation")
        or ""
    ).strip()
    user = str(args.get("user_id") or args.get("user") or "").strip()
    name = ""
    cid = ""
    if channel.startswith("#"):
        name = channel.lower()
    elif len(channel) > 1 and channel[0] in "CDG" and channel[1:].isalnum():
        cid = channel
    elif channel:
        name = "#" + channel.lstrip("#").lower()
    return {
        "channel_id": cid,
        "channel_name": name.lower(),
        "user": user,
        "raw": channel,
    }


def _is_dm(target: dict[str, str], arguments: dict[str, Any] | None) -> bool:
    raw = (target.get("raw") or "") + (target.get("channel_id") or "")
    if raw.startswith("D"):
        return True
    args = arguments or {}
    if args.get("user") or args.get("user_id"):
        if not (target.get("channel_id") or "").startswith("C"):
            return True
    return False


def extract_named_destinations(prompt: str) -> dict[str, set[str]]:
    text = prompt or ""
    names = {("#" + m.group(1).lower()) for m in _CHANNEL_HASH.finditer(text)}
    ids = {m.group(1) for m in _SLACK_ID.finditer(text)}
    users = {m.group(1) for m in _USER_ID.finditer(text)}
    lower = text.lower()
    for alias in _NAMED_CHANNELS:
        if re.search(r"\b" + re.escape(alias) + r"\b", lower):
            names.add("#" + alias)
    return {"names": names, "ids": ids, "users": users}


def has_post_intent(prompt: str) -> bool:
    text = prompt or ""
    if not text.strip():
        return False
    if _NEGATION.search(text):
        return False
    return bool(_INTENT.search(text))


def has_dm_intent(prompt: str) -> bool:
    return bool(_DM_WORD.search(prompt or ""))


def check_slack_write(
    tool_name: str, arguments: dict[str, Any] | None = None
) -> Optional[str]:
    """Return an error string to block the call, or None to allow."""
    if not is_slack_write_tool(tool_name):
        return None
    if os.environ.get("SLACK_WRITE_GUARD_BYPASS", "").lower() in {"1", "true", "yes"}:
        return None
    if _approved_bypass.get():
        return None

    prompt = current_user_prompt()
    target = _target_from_args(arguments)
    dest_label = (
        target.get("channel_name")
        or target.get("channel_id")
        or target.get("user")
        or target.get("raw")
        or "(unspecified)"
    )
    is_general = (
        target.get("channel_id") == GENERAL_CHANNEL_ID
        or target.get("channel_name") in GENERAL_NAMES
        or (target.get("raw") or "").lower() in GENERAL_NAMES
        or (target.get("raw") or "") == GENERAL_CHANNEL_ID
    )
    dm = _is_dm(target, arguments)

    if not prompt.strip():
        return _deny(
            tool_name,
            dest_label,
            "no Discord prompt bound — Slack writes fail closed",
        )

    if not has_post_intent(prompt) and not (
        dm and has_dm_intent(prompt) and "slack" in prompt.lower()
    ):
        return _deny(
            tool_name,
            dest_label,
            "current message does not explicitly ask to post/send to Slack",
        )

    named = extract_named_destinations(prompt)

    if dm:
        if not has_dm_intent(prompt):
            return _deny(tool_name, dest_label, "DMs require an explicit DM request")
        user = target.get("user") or ""
        if user and user not in named["users"] and user.lower() not in prompt.lower():
            if not re.search(r"\bdm\s+me\b", prompt, re.I):
                return _deny(
                    tool_name,
                    dest_label,
                    "DM target was not named in the user message",
                )
        return None

    if is_general:
        if "#general" not in named["names"] and GENERAL_CHANNEL_ID not in named["ids"]:
            return _deny(
                tool_name,
                "#general",
                "posting to #general requires the user to name #general in this message",
            )
        return None

    cid = target.get("channel_id") or ""
    cname = target.get("channel_name") or ""
    if cid and cid in named["ids"]:
        return None
    if cname and cname in named["names"]:
        return None
    if not named["names"] and not named["ids"]:
        return _deny(
            tool_name,
            dest_label,
            "user asked to post to Slack but did not name a channel — ask which channel first",
        )
    return _deny(
        tool_name,
        dest_label,
        "destination was not named in the user message (named: "
        + ", ".join(sorted(named["names"] | named["ids"]))
        + ")",
    )


def _deny(tool_name: str, dest: str, reason: str) -> str:
    return (
        "BLOCKED by slack_write_guard: refused Slack write "
        f"({tool_name} -> {dest}). {reason}. "
        "Ask the captain to name the Slack channel or DM in this Discord message. "
        "#general, other work channels, and DMs are never posted to without that explicit approval."
    )


def annotate_tool_description(name: str, description: str) -> str:
    if not is_slack_write_tool(name):
        return description
    extra = (
        " REQUIRES EXPLICIT USER APPROVAL in the current Discord message: "
        "they must ask to post/send to Slack AND name the channel or DM. "
        "Never post to #general unless they named #general. "
        "Never DM anyone unless they asked to DM."
    )
    if extra.strip() in (description or ""):
        return description
    return (description or "").rstrip() + extra