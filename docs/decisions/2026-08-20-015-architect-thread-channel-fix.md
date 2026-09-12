# ADR: Architect Bot Thread/Channel Fix

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Writer Agent (Cursor)

## Context

The Architect Discord bot (`scripts/architect-bot.py`) has a feature that automatically
creates Discord threads for multi-step tasks (messages containing "then", "after that",
etc.) or long responses (>8000 chars or 8+ tool calls). This is controlled by the
`should_use_thread()` heuristic from `discord_ux_utils.py`.

When a user sent a multi-step message to the Architect, the bot would:
1. Create a thread for the task
2. Pass the `Thread` object (instead of the `Message` object) to `AgentProgressView`
3. Crash with `AttributeError: 'Thread' object has no attribute 'channel'` when
   `AgentProgressView.start()` tried to access `self.message.channel.id`

Additionally, even if the crash were fixed, follow-up messages sent inside the
auto-created thread would be silently dropped because the thread's channel ID was
not in `MONITORED_CHANNEL_IDS`, causing the channel filter at line 3857 to reject
the message.

This manifested as the bot creating a thread and then going silent — it would never
respond to follow-up messages inside that thread.

## Decision

Three fixes were applied to `scripts/architect-bot.py`:

### 1. Suppress nested thread creation

Added `isinstance(message.channel, discord.Thread)` check to the `use_thread`
assignment so that messages already inside a thread do not trigger creation of
yet another thread.

### 2. Handle Thread objects in AgentProgressView

- Added a `_channel` property that resolves the Discord channel for both
  `Message` (returns `self.message.channel`) and `Thread` (returns `self.message`
  itself) objects.
- Added a `_reply()` helper method that uses `message.reply()` for `Message`
  objects and falls back to `channel.send()` for `Thread` objects.
- Replaced all `self.message.channel.id` references with `self._channel.id`.
- Replaced all `self.message.reply()` calls with `self._reply()`.
- Added `hasattr(self.message, 'create_thread')` guard in `finalize()` auto-thread
  creation to prevent `AttributeError` on `Thread` objects.

### 3. Allow messages from threads of monitored channels

Updated the channel filter in `handle_single_agent_message()` to check if a
message is from a thread whose `parent_id` is in `MONITORED_CHANNEL_IDS`. This
allows the bot to respond to follow-up messages inside auto-created threads.

## Rationale

- **Nested thread suppression**: Creating a thread inside a thread is unnecessary
  and confusing for users. Discord's thread model doesn't nest meaningfully.
- **Thread-safe AgentProgressView**: The `AgentProgressView` class was designed
  assuming `self.message` is always a `discord.Message`, but the thread creation
  code passes a `discord.Thread` object. The `_channel` and `_reply` helpers
  provide a clean abstraction that works for both.
- **Thread parent channel check**: The `MONITORED_CHANNEL_IDS` filter was too
  strict — it only allowed messages from the exact channel IDs, not from threads
  created within those channels. Since the bot itself creates these threads, it
  should respond to messages within them.

## Alternatives Considered

1. **Always use `message.channel` instead of passing `thread` to AgentProgressView**:
   Rejected because the progress indicator should appear in the thread, not the
   main channel. The thread is where the agent's work is being done.

2. **Add thread IDs to `MONITORED_CHANNEL_IDS` dynamically**: Rejected because
   thread IDs are not known ahead of time, and modifying a global set at runtime
   is fragile. The `parent_id` check is more robust.

3. **Disable thread creation entirely**: Rejected because thread creation is a
   useful UX feature for keeping the main channel clean during multi-step tasks.

## Consequences

- The Architect bot now correctly responds to follow-up messages inside
  auto-created threads.
- No more `AttributeError` crashes when processing messages in threads.
- Thread creation is suppressed inside threads, preventing nested threads.
- The `_channel` and `_reply` patterns should be applied to any future code
  that passes `Thread` objects to classes expecting `Message` objects.

## References

- Bug report: User conversation with Architect about MeetScribe cadence (2026-08-20 11:27 AM)
- Related code: `scripts/architect-bot.py` lines 871-1040 (AgentProgressView),
  lines 3946-3975 (handle_single_agent_message)
- Test files: `scripts/test_thread_fix.py`, `scripts/test_thread_fix_live.py`
