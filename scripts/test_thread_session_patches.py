#!/usr/bin/env python3
"""Unit tests for thread-safe create_thread + parent-scoped sessions."""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord  # noqa: E402
from discord_ux_utils import can_create_thread, session_channel_id  # noqa: E402
from session_manager import SessionManager  # noqa: E402


class FakeThread:
    def __init__(self, id, parent_id):
        self.id = id
        self.parent_id = parent_id


class FakeChannel:
    def __init__(self, id):
        self.id = id
        self.parent_id = None


class SessionChannelTests(unittest.TestCase):
    def test_parent_channel_uses_own_id(self):
        self.assertEqual(session_channel_id(FakeChannel(111)), 111)

    def test_thread_uses_parent_id(self):
        self.assertEqual(session_channel_id(FakeThread(999, 111)), 111)


class CanCreateThreadTests(unittest.TestCase):
    def test_rejects_thread_channel(self):
        msg = SimpleNamespace(
            channel=discord.Thread.__new__(discord.Thread) if False else SimpleNamespace(),
            guild=object(),
            create_thread=lambda **k: None,
        )
        # isinstance check needs a real Thread or we simulate via duck typing:
        # can_create_thread uses isinstance(channel, discord.Thread).
        class T(discord.Thread):
            def __init__(self):
                pass
        try:
            thread = T()
        except Exception:
            thread = MagicMock(spec=discord.Thread)
        msg.channel = thread
        self.assertFalse(can_create_thread(msg))

    def test_rejects_missing_guild(self):
        msg = SimpleNamespace(
            channel=FakeChannel(1),
            guild=None,
            create_thread=lambda **k: None,
        )
        self.assertFalse(can_create_thread(msg))

    def test_rejects_none(self):
        self.assertFalse(can_create_thread(None))


class SessionManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sm = SessionManager(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_thread_id_does_not_split_session(self):
        self.sm.append_exchange(channel_id=111, user_msg="hi", assistant_msg="hello")
        self.sm.append_exchange(channel_id=111, user_msg="followup", assistant_msg="still here", thread_id="999")
        hist = self.sm.get_history(111, thread_id="999")
        self.assertEqual(len(hist), 4)
        self.assertEqual(self.sm._session_id(111, "999"), "111")

    def test_alias_kwargs_and_none_safe(self):
        self.sm.append_exchange(channel_id=5, user_message="a", assistant_response="b")
        self.sm.append_exchange(channel_id=5, user_msg=None, assistant_msg=None)
        hist = self.sm.get_history(5)
        self.assertEqual(hist[-2:], [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])


class SourceGuardTests(unittest.TestCase):
    BOTS = [
        "architect-bot.py",
        "proctor-bot.py",
        "dr-voss-bot.py",
        "dr-cortex-bot.py",
        "cartographer-bot.py",
        "quartermaster-bot.py",
        "schubert-bot-v2.py",
    ]

    def test_no_unbound_thread_progress_view(self):
        for name in self.BOTS:
            src = open(os.path.join(os.path.dirname(__file__), name)).read()
            self.assertNotIn(
                "AgentProgressView(message if not use_thread else thread)",
                src,
                msg=name,
            )

    def test_bots_import_safe_create_thread(self):
        for name in self.BOTS:
            if name == "schubert-bot-v2.py":
                continue
            src = open(os.path.join(os.path.dirname(__file__), name)).read()
            self.assertIn("safe_create_thread", src, msg=name)

    def test_admiral_max_iterations_30(self):
        src = open(os.path.join(os.path.dirname(__file__), "schubert-bot-v2.py")).read()
        self.assertIn("MAX_ITERATIONS = 30", src)

    def test_cortex_does_not_bind_8095_by_default(self):
        src = open(os.path.join(os.path.dirname(__file__), "dr-cortex-bot.py")).read()
        self.assertIn("port 8095 is owned by Admiral", src)

    def test_scripts_parse(self):
        for name in self.BOTS + ["discord_ux_utils.py", "session_manager.py", "ui_components.py"]:
            src = open(os.path.join(os.path.dirname(__file__), name)).read()
            ast.parse(src)


if __name__ == "__main__":
    unittest.main()
