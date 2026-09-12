"""Slack write-guard policy (2026-08-22)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("/opt/Project-Tango")
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from slack_write_guard import (  # noqa: E402
    bind_user_prompt,
    check_slack_write,
    has_post_intent,
    is_slack_write_tool,
)


POST = "slack__slack_post_message"
GENERAL = "C02AJRK9H"
OPS = "C0TANGOOPS1"


def setup_function():
    bind_user_prompt("")


def test_reads_are_allowed():
    bind_user_prompt("list my channels")
    assert check_slack_write("slack__slack_list_channels", {}) is None
    assert check_slack_write("slack__slack_get_channel_history", {"channel_id": GENERAL}) is None
    assert not is_slack_write_tool("slack__slack_list_channels")
    assert is_slack_write_tool(POST)


def test_conversation_test_cannot_post_to_general():
    bind_user_prompt("Can you perform a conversation test?")
    blocked = check_slack_write(POST, {"channel_id": GENERAL, "text": "test"})
    assert blocked and "BLOCKED" in blocked


def test_fail_closed_without_prompt():
    bind_user_prompt("")
    blocked = check_slack_write(POST, {"channel_id": "C0TANGOOPS1", "text": "hi"})
    assert blocked and "fail closed" in blocked


def test_post_to_slack_without_channel_is_blocked():
    bind_user_prompt("Please post this to Slack")
    blocked = check_slack_write(POST, {"channel_id": "C0TANGOOPS1", "text": "hi"})
    assert blocked and "did not name a channel" in blocked


def test_named_tango_ops_is_allowed():
    bind_user_prompt("Please post this to Slack in #tango-ops")
    assert check_slack_write(POST, {"channel_id": "", "channel": "#tango-ops", "text": "hi"}) is None
    assert check_slack_write(POST, {"channel": "tango-ops", "text": "hi"}) is None


def test_named_ops_cannot_spill_into_general():
    bind_user_prompt("Please post this to Slack in #tango-ops")
    blocked = check_slack_write(POST, {"channel_id": GENERAL, "text": "hi"})
    assert blocked and "#general" in blocked


def test_explicit_general_is_allowed():
    bind_user_prompt("Please post this to Slack in #general")
    assert check_slack_write(POST, {"channel_id": GENERAL, "text": "hi"}) is None


def test_yes_does_not_authorize_slack():
    bind_user_prompt("Yes")
    blocked = check_slack_write(POST, {"channel": "#tango-dev", "text": "hi"})
    assert blocked and "BLOCKED" in blocked


def test_dm_blocked_without_dm_request():
    bind_user_prompt("Please post this to Slack in #tango-ops")
    blocked = check_slack_write(POST, {"channel_id": "D0123456789", "text": "hi"})
    assert blocked and "DM" in blocked


def test_explicit_dm_allowed():
    bind_user_prompt("Please DM me on Slack with the status")
    assert check_slack_write(POST, {"channel_id": "D0123456789", "text": "hi"}) is None


def test_negation_blocks():
    bind_user_prompt("Don't post this to Slack in #tango-ops")
    assert not has_post_intent("Don't post this to Slack in #tango-ops")
    blocked = check_slack_write(POST, {"channel": "#tango-ops", "text": "hi"})
    assert blocked and "BLOCKED" in blocked

def test_thread_replies_read_is_allowed():
    bind_user_prompt("Can you perform a conversation test?")
    assert check_slack_write("slack__slack_get_thread_replies", {"channel_id": "C02AJRK9H"}) is None
    assert not is_slack_write_tool("slack__slack_get_thread_replies")
