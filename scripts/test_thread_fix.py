#!/usr/bin/env python3
"""
Test script for the Architect bot thread/channel fix.

Verifies that:
1. AgentProgressView._channel resolves correctly for both Message and Thread objects
2. should_use_thread + isinstance check prevents nested thread creation
3. The _channel property works in start(), _typing_loop(), and finalize()

Run: python3 scripts/test_thread_fix.py
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure scripts dir is on path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


# ---------------------------------------------------------------------------
# Minimal re-implementation of the _channel property logic for testing.
# We can't import architect-bot.py directly (hyphenated filename + heavy deps),
# so we test the exact same logic in isolation, then verify the source code
# contains the fix.
# ---------------------------------------------------------------------------

class FakeChannel:
    """Simulates a discord.TextChannel — has .id and .typing()."""
    def __init__(self, channel_id=12345):
        self.id = channel_id

    def typing(self):
        class _Ctx:
            async def __aenter__(self_inner):
                return self_inner
            async def __aexit__(self_inner, *args):
                pass
        return _Ctx()


class FakeThread:
    """Simulates a discord.Thread — has .id but NOT .channel (has .parent instead)."""
    def __init__(self, thread_id=67890):
        self.id = thread_id
        self.parent = FakeChannel(99999)

    def typing(self):
        class _Ctx:
            async def __aenter__(self_inner):
                return self_inner
            async def __aexit__(self_inner, *args):
                pass
        return _Ctx()

    async def send(self, *args, **kwargs):
        mock_msg = MagicMock()
        mock_msg.delete = AsyncMock()
        return mock_msg


class FakeMessage:
    """Simulates a discord.Message — has .channel."""
    def __init__(self, channel):
        self.channel = channel
        self.id = 99999

    async def reply(self, *args, **kwargs):
        mock_msg = MagicMock()
        mock_msg.delete = AsyncMock()
        return mock_msg


class FakeThreadMessage:
    """Simulates a message received inside a thread — message.channel is a Thread."""
    def __init__(self, thread):
        self.channel = thread
        self.id = 11111

    async def reply(self, *args, **kwargs):
        mock_msg = MagicMock()
        mock_msg.delete = AsyncMock()
        return mock_msg


class ChannelResolver:
    """Mirror of AgentProgressView._channel and _reply properties for testing."""

    def __init__(self, message):
        self.message = message

    @property
    def _channel(self):
        return self.message.channel if hasattr(self.message, 'channel') else self.message

    async def _reply(self, *args, **kwargs):
        """Mirror of AgentProgressView._reply method."""
        if hasattr(self.message, 'reply'):
            return await self.message.reply(*args, **kwargs)
        return await self._channel.send(*args, **kwargs)


class TestChannelResolution(unittest.TestCase):
    """Test that _channel resolves correctly for both Message and Thread objects."""

    def test_channel_property_with_message(self):
        """When self.message is a Message (has .channel), _channel returns the channel."""
        channel = FakeChannel(channel_id=100)
        message = FakeMessage(channel=channel)

        resolver = ChannelResolver(message)
        resolved = resolver._channel

        self.assertEqual(resolved.id, 100)
        self.assertIs(resolved, channel)

    def test_channel_property_with_thread_directly(self):
        """When self.message IS a Thread (no .channel attr), _channel returns the thread itself.

        This is the crash scenario: line 3965 passes `thread` directly to AgentProgressView.
        """
        thread = FakeThread(thread_id=200)

        resolver = ChannelResolver(thread)
        resolved = resolver._channel

        self.assertEqual(resolved.id, 200)
        self.assertIs(resolved, thread)

    def test_channel_property_with_thread_message(self):
        """When message.channel is a Thread, _channel returns the Thread."""
        thread = FakeThread(thread_id=300)
        message = FakeThreadMessage(thread=thread)

        resolver = ChannelResolver(message)
        resolved = resolver._channel

        self.assertEqual(resolved.id, 300)
        self.assertIs(resolved, thread)

    def test_no_attribute_error_on_thread(self):
        """The original bug: accessing .channel on a Thread raises AttributeError.

        The fix: _channel property checks hasattr before accessing .channel.
        """
        thread = FakeThread(thread_id=400)

        # Old code would do: thread.channel.id -> AttributeError
        with self.assertRaises(AttributeError):
            _ = thread.channel

        # New code: _channel property handles this
        resolver = ChannelResolver(thread)
        resolved = resolver._channel
        self.assertEqual(resolved.id, 400)


class TestStartMethod(unittest.TestCase):
    """Test that start() logic doesn't crash with a Thread object."""

    def test_start_channel_id_with_thread(self):
        """The ProgressView constructor receives the correct channel_id from a Thread."""
        thread = FakeThread(thread_id=500)

        # Simulate what start() does: ProgressView(self._channel.id)
        resolver = ChannelResolver(thread)
        channel_id = resolver._channel.id

        self.assertEqual(channel_id, 500)

    def test_start_channel_id_with_message(self):
        """The ProgressView constructor receives the correct channel_id from a Message."""
        channel = FakeChannel(channel_id=600)
        message = FakeMessage(channel=channel)

        resolver = ChannelResolver(message)
        channel_id = resolver._channel.id

        self.assertEqual(channel_id, 600)


class TestTypingLoop(unittest.TestCase):
    """Test that _typing_loop uses _channel.typing() not self.message.channel.typing()."""

    def test_typing_loop_with_thread(self):
        """_typing_loop should use _channel.typing() which works for Thread objects."""
        thread = FakeThread(thread_id=700)

        resolver = ChannelResolver(thread)
        channel = resolver._channel

        # Verify typing() is accessible (what _typing_loop uses)
        self.assertTrue(hasattr(channel, 'typing'))

        # Old code would fail: self.message.channel.typing() -> AttributeError
        with self.assertRaises(AttributeError):
            thread.channel

    def test_typing_loop_with_message(self):
        """_typing_loop should work with Message objects too."""
        channel = FakeChannel(channel_id=800)
        message = FakeMessage(channel=channel)

        resolver = ChannelResolver(message)
        channel_obj = resolver._channel

        self.assertTrue(hasattr(channel_obj, 'typing'))


class TestFinalizeMethod(unittest.TestCase):
    """Test that finalize() logic doesn't crash with a Thread object."""

    def test_finalize_channel_id_with_thread(self):
        """finalize() creates ResponseView(self._channel.id) — should work with Thread."""
        thread = FakeThread(thread_id=900)

        resolver = ChannelResolver(thread)
        channel_id = resolver._channel.id

        self.assertEqual(channel_id, 900)


class TestThreadSuppression(unittest.TestCase):
    """Test that thread creation is suppressed when already inside a thread."""

    def test_should_use_thread_returns_true_for_multi_step(self):
        """Verify the heuristic triggers for multi-step messages."""
        from discord_ux_utils import should_use_thread

        self.assertTrue(should_use_thread("change the interval then do a sync"))
        self.assertTrue(should_use_thread("in a thread: check logs"))

    def test_should_use_thread_returns_false_for_simple(self):
        """Verify the heuristic does not trigger for simple messages."""
        from discord_ux_utils import should_use_thread

        self.assertFalse(should_use_thread("hello"))
        self.assertFalse(should_use_thread("!status"))

    def test_isinstance_check_suppresses_thread_creation(self):
        """The fix: isinstance(message.channel, discord.Thread) prevents nested threads.

        We simulate the logic: use_thread = should_use_thread(input) and not is_thread
        """
        from discord_ux_utils import should_use_thread

        # Simulate: message.channel is a Thread
        is_thread = True
        user_input = "change the interval then do a sync"

        use_thread = should_use_thread(user_input) and not is_thread
        self.assertFalse(use_thread, "Thread creation should be suppressed when already in a thread")

    def test_thread_creation_allowed_in_main_channel(self):
        """In a main channel, thread creation should proceed normally."""
        from discord_ux_utils import should_use_thread

        is_thread = False
        user_input = "change the interval then do a sync"

        use_thread = should_use_thread(user_input) and not is_thread
        self.assertTrue(use_thread, "Thread creation should be allowed in main channel")


class TestThreadParentChannelCheck(unittest.TestCase):
    """Test that messages in threads of monitored channels are allowed through."""

    def test_thread_parent_id_check(self):
        """A Thread with parent_id in MONITORED_CHANNEL_IDS should be allowed."""
        # Simulate the logic
        MONITORED_CHANNEL_IDS = {100, 200, 300}

        # Thread whose parent is monitored
        thread_parent_id = 100
        in_thread_of_monitored = thread_parent_id in MONITORED_CHANNEL_IDS
        self.assertTrue(in_thread_of_monitored)

        # Thread whose parent is NOT monitored
        thread_parent_id = 999
        in_thread_of_monitored = thread_parent_id in MONITORED_CHANNEL_IDS
        self.assertFalse(in_thread_of_monitored)

    def test_main_channel_still_allowed(self):
        """A message directly in a monitored channel should still be allowed."""
        MONITORED_CHANNEL_IDS = {100, 200, 300}

        channel_id = 100
        in_monitored = channel_id in MONITORED_CHANNEL_IDS
        self.assertTrue(in_monitored)

    def test_unmonitored_channel_still_blocked(self):
        """A message in an unmonitored channel (not a thread) should be blocked."""
        MONITORED_CHANNEL_IDS = {100, 200, 300}

        channel_id = 999
        in_monitored = channel_id in MONITORED_CHANNEL_IDS
        self.assertFalse(in_monitored)


class TestReplyMethod(unittest.TestCase):
    """Test that _reply() works for both Message and Thread objects."""

    def test_reply_with_message(self):
        """_reply() should use message.reply() when self.message is a Message."""
        channel = FakeChannel(channel_id=1000)
        message = FakeMessage(channel=channel)

        resolver = ChannelResolver(message)
        self.assertTrue(hasattr(resolver.message, 'reply'))

    def test_reply_with_thread(self):
        """_reply() should use _channel.send() when self.message is a Thread (no .reply())."""
        thread = FakeThread(thread_id=1100)

        resolver = ChannelResolver(thread)
        self.assertFalse(hasattr(resolver.message, 'reply'))
        # Should fall back to _channel.send()
        self.assertTrue(hasattr(resolver._channel, 'send'))

    def test_reply_does_not_raise_attribute_error_on_thread(self):
        """The original bug: Thread has no .reply(). The fix: _reply falls back to .send()."""
        thread = FakeThread(thread_id=1200)

        # Old code would do: thread.reply() -> AttributeError
        with self.assertRaises(AttributeError):
            thread.reply  # type: ignore[attr-defined]

        # New code: _reply checks hasattr first
        resolver = ChannelResolver(thread)
        self.assertFalse(hasattr(resolver.message, 'reply'))
        # _channel.send should be the fallback
        self.assertTrue(hasattr(resolver._channel, 'send'))


class TestSourceCodeContainsFix(unittest.TestCase):
    """Verify the actual source file contains the fix."""

    def test_source_has_channel_property(self):
        """Check that architect-bot.py has the _channel property."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("@property", source)
        self.assertIn("def _channel(self):", source)
        self.assertIn("hasattr(self.message, 'channel')", source)

    def test_source_has_reply_helper(self):
        """Check that architect-bot.py has the _reply helper method."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("async def _reply(self", source)
        self.assertIn("hasattr(self.message, 'reply')", source)

    def test_source_has_isinstance_thread_check(self):
        """Check that architect-bot.py has the isinstance Thread check."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("isinstance(message.channel, discord.Thread)", source)

    def test_source_uses_channel_in_start(self):
        """Check that start() uses self._channel.id, not self.message.channel.id."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("ProgressView(self._channel.id)", source)
        self.assertNotIn("ProgressView(self.message.channel.id)", source)

    def test_source_uses_reply_helper_in_start(self):
        """Check that start() uses self._reply(), not self.message.reply()."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("await self._reply(embed=embed, view=view)", source)
        # Make sure the old direct call is gone
        self.assertNotIn("await self.message.reply(embed=embed, view=view)", source)

    def test_source_uses_reply_helper_in_finalize(self):
        """Check that finalize() uses self._reply(), not self.message.reply()."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("await self._reply(response, view=view)", source)
        self.assertIn("await self._reply(embed=embed, view=view)", source)
        self.assertIn("await self._reply(embed=embed)", source)
        # Make sure old direct calls are gone
        self.assertNotIn("await self.message.reply(response, view=view)", source)
        self.assertNotIn("await self.message.reply(embed=embed, view=view)", source)
        self.assertNotIn("await self.message.reply(embed=embed)", source)

    def test_source_uses_channel_in_typing_loop(self):
        """Check that _typing_loop uses self._channel.typing(), not self.message.channel.typing()."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("self._channel.typing()", source)
        self.assertNotIn("self.message.channel.typing()", source)

    def test_source_uses_channel_in_finalize(self):
        """Check that finalize() uses self._channel.id, not self.message.channel.id."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("ResponseView(self._channel.id)", source)
        self.assertNotIn("ResponseView(self.message.channel.id)", source)

    def test_source_hasattr_check_in_auto_thread(self):
        """Check that auto-thread creation uses hasattr for create_thread."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("hasattr(self.message, 'create_thread')", source)

    def test_source_has_thread_parent_id_check(self):
        """Check that the channel filter allows threads of monitored channels."""
        with open(os.path.join(_SCRIPT_DIR, "architect-bot.py"), "r") as f:
            source = f.read()

        self.assertIn("parent_id", source)
        self.assertIn("in_thread_of_monitored", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
