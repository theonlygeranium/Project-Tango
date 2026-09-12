# ADR 015: Discord Bot Fleet UI/UX Enhancements

**Date:** 2026-08-19
**Status:** Accepted
**Decided by:** Cursor Agent (implementing Writer Agent specifications)

## Context

The Project Tango Discord bot fleet (8 bots: Admiral Schubert, The Architect, Dr. Voss, The Proctor, The Quartermaster, The Cartographer, Dr. Cortex, and Tango Discord Agent) faced several user experience challenges:

1. **Lack of visual feedback during long operations** — Users could not tell if a bot was actively processing a request or had frozen/crashed, particularly during multi-step agent loops that could take 30+ seconds.

2. **Notification fatigue** — Progress updates from `AgentProgressView` generated push notifications for every status change, overwhelming users during long workflows with dozens of pings.

3. **Channel organization difficulties** — Complex multi-step tasks created long conversation threads in main channels, making it hard to follow multiple concurrent discussions or locate specific work contexts.

4. **Limited agent autonomy** — Bots lacked native tools for common Discord workflows:
   - Could not create polls for user feedback or decision-making
   - Could not manage pinned messages for important references
   - Had no mechanism to organize work into threads

5. **Poor channel onboarding** — New users joining bot channels had no context about bot capabilities, purpose, or available commands, leading to confusion and inefficient usage.

These issues were identified through user feedback and operational observations over 3 months of deployment (June-August 2026).

## Decision

Implemented six complementary enhancements to improve Discord bot UX:

### 1. Native Typing Indicators (Spec 1)
- Bots send periodic `POST /channels/{id}/typing` requests (10-second cadence) during agent loops
- Implemented via `keep_typing()` async context manager in `discord_ux_utils.py`
- Provides real-time visual feedback using Discord's native typing indicator UI
- Controlled by `DISCORD_TYPING_ENABLED` environment variable (default: true)

### 2. Channel Onboarding System (Spec 2)
- Automated setup in each bot's `on_ready` handler via `channel_onboarding.py`
- Sets channel topic describing bot purpose and expertise domain
- Creates and pins welcome embed with capability summary, command list, and usage guidelines
- Applies to all 8 bot channels with persona-appropriate content
- Controlled by `DISCORD_ONBOARDING_ENABLED` environment variable (default: true)
- Requires `MANAGE_CHANNELS` permission

### 3. Silent Progress Notifications (Spec 3)
- `AgentProgressView.send_progress_update()` now sets `silent=True` on all messages
- Uses Discord's `SUPPRESS_NOTIFICATIONS` message flag
- Messages remain visible in channel but do not trigger push notifications
- Controlled by `DISCORD_SILENT_PROGRESS` environment variable (default: true)
- Zero code changes required in individual bot scripts (centralized in `ui_components.py`)

### 4. Native Discord Polls (Spec 4)
- Added `create_poll()` agent tool in `poll_tools.py`
- Wraps Discord Poll API (requires discord.py 2.7.1+)
- Supports up to 10 options, customizable duration (max 168 hours)
- Enables bots to autonomously gather user feedback and votes
- Uses Discord's native poll UI with automatic vote tallying

### 5. Pinned Resource Management (Spec 5)
- Added three agent tools in `pinned_resources_tools.py`:
  - `pin_message()` — Pin message by ID to channel
  - `unpin_message()` — Unpin message by ID
  - `list_pinned_messages()` — List all pinned messages in channel
- Enables bots to manage important references, documentation links, status dashboards
- Requires `MANAGE_MESSAGES` permission
- Respects Discord's 50-pin limit per channel

### 6. Thread-Based Task Isolation (Spec 6)
- Complex requests auto-create Discord threads via `auto_create_thread_if_needed()`
- Heuristic triggers:
  - Message length >200 characters
  - Multi-step keywords detected ("then", "after that", "next", "finally")
  - Explicit threading request
- Thread name auto-generated from task summary (first 100 chars)
- Controlled by `DISCORD_AUTO_THREADING` environment variable (default: true)
- Requires `CREATE_PUBLIC_THREADS` permission

All features share utilities in `scripts/discord_ux_utils.py` with common helpers for typing indicators, input validation, thread creation, and Discord API error handling.

## Rationale

### Why These Features

1. **Native typing indicators over custom progress embeds**:
   - Users already understand Discord's typing indicator (universal UI pattern)
   - No additional screen real estate consumed
   - Native implementation requires only periodic API calls (low overhead)
   - Custom progress embeds would add message clutter and require more complex UI

2. **Silent notifications over disabling progress updates entirely**:
   - Preserves full transparency of agent operations (important for trust)
   - Message history remains searchable and auditable
   - Users can still monitor progress by checking the channel
   - Eliminates notification spam without hiding information

3. **Native polls over custom reaction-based voting**:
   - Discord's poll UI is richer (vote counts, percentages, time remaining)
   - Automatic vote tallying and duplicate prevention
   - Better mobile experience
   - No custom vote-counting logic required

4. **Discord threads over always-in-main-channel**:
   - Threads are purpose-built for focused conversations
   - Preserves main channel readability
   - Enables parallel work without context switching
   - Threads auto-archive after inactivity (self-cleaning)

5. **Channel onboarding over external documentation**:
   - Information is discoverable in-context (users don't need to leave Discord)
   - Pinned embeds remain visible as channel reference
   - Topics provide at-a-glance bot identification
   - Reduces support burden and onboarding friction

6. **Heuristic threading over always-thread or never-thread**:
   - Balances cleanliness (complex tasks in threads) vs simplicity (quick queries in main channel)
   - User override available ("create a thread for this")
   - Prevents thread sprawl from simple questions
   - Adapts to task complexity automatically

### Why Discord Native Features Over Custom Solutions

- **Consistency**: Users already know how typing indicators, polls, pins, and threads work
- **Maintenance**: No custom UI components to maintain or debug
- **Mobile compatibility**: Discord's native features work well on mobile (custom embeds often don't)
- **Accessibility**: Native features support screen readers and keyboard navigation
- **API stability**: Discord maintains these features; custom solutions can break with API changes

## Alternatives Considered

### 1. Custom Progress Indicators Instead of Typing

**Rejected because:**
- Adds message clutter (every progress update is a new message)
- Users must learn a custom UI pattern
- Higher API usage (embed updates vs simple typing endpoint)
- Does not look as clean as native typing indicator

**When we might reconsider:**
- If Discord deprecates the typing endpoint
- If we need more granular progress information (typing only shows "working", not specific status)

### 2. Always Create Threads Instead of Heuristic-Based

**Rejected because:**
- Creates thread sprawl (hundreds of threads for simple questions)
- Extra friction for quick queries ("type question → wait for bot to create thread → type question again")
- Discord's thread UI is heavier than message history
- Thread archiving creates hidden content users may not find

**When we might reconsider:**
- If users request it as an option
- For specific high-traffic channels where main channel is too noisy

### 3. Bot-Managed Pin Lists Instead of Native Pins

**Rejected because:**
- Requires custom embed maintenance and refresh logic
- Users can't pin their own messages (bots own the embed)
- Doesn't integrate with Discord's native pin viewer
- More complex implementation (database, UI, refresh triggers)

**When we might reconsider:**
- If we exceed Discord's 50-pin limit per channel
- If we need pin categories or complex organization

### 4. Disable Progress Updates Instead of Silent Notifications

**Rejected because:**
- Loses transparency into agent operations
- No message history for auditing or debugging
- Users have no way to check progress if they want to
- Creates "black box" perception (reduces trust)

**When we might reconsider:**
- If users explicitly request a "quiet mode"
- For specific bots where operations are always fast (<5s)

### 5. External Documentation Wiki Instead of Channel Onboarding

**Rejected because:**
- Requires users to leave Discord and remember/bookmark external URL
- Documentation gets stale (separate from code)
- No in-context discovery (users don't know wiki exists)
- Higher maintenance burden (two places to update)

**When we might reconsider:**
- For detailed technical documentation that doesn't fit in a channel topic
- For cross-bot workflows that span multiple channels

## Consequences

### Positive

1. **Improved user experience**:
   - Users know when bots are working (typing indicators)
   - Reduced notification fatigue (silent progress)
   - Cleaner channels (threads for complex work)
   - Better onboarding (topics + pinned embeds)

2. **Enhanced bot autonomy**:
   - Bots can gather user feedback via polls
   - Bots can organize important resources via pins
   - Bots can structure work into threads

3. **Lower support burden**:
   - Channel onboarding answers common questions
   - Typing indicators reduce "is the bot working?" questions
   - Threads contain context (easier to debug and follow up)

4. **Better mobile experience**:
   - Native features work well on Discord mobile app
   - Silent notifications don't spam mobile lock screens

### Negative

1. **API rate limit concerns**:
   - Typing endpoint: 5 requests per 5 seconds per channel (well within limits for our usage)
   - Pin management: 50 pins per channel max (must be managed carefully)
   - Thread creation: No explicit limit but could create clutter if heuristic fails

2. **Permission requirements**:
   - Requires `MANAGE_CHANNELS` for topics/onboarding (may not be granted in all servers)
   - Requires `MANAGE_MESSAGES` for pin management (more privileged)
   - Requires `CREATE_PUBLIC_THREADS` for auto-threading (usually granted)

3. **Version requirements**:
   - Discord.py 2.7.1+ required for native poll support (deployed on Schubert, but constraint for future deployments)

4. **Thread sprawl risk**:
   - Heuristic may create threads too aggressively (mitigated by tunable thresholds + env var disable)
   - Users may not know to check threads for their responses (mitigated by @mention in thread creation message)

5. **Pin management complexity**:
   - 50-pin limit requires active management (bots must unpin old content)
   - No automatic expiration (requires manual cleanup or future auto-unpin logic)

### Neutral

1. **Configuration complexity**:
   - Five new environment variables (`DISCORD_TYPING_ENABLED`, `DISCORD_SILENT_PROGRESS`, `DISCORD_AUTO_THREADING`, `DISCORD_ONBOARDING_ENABLED`, plus poll/pin tool availability)
   - All have sensible defaults (no action required for standard deployments)

2. **Code organization**:
   - Three new modules (`discord_ux_utils.py`, `channel_onboarding.py`, `pinned_resources_tools.py`, `poll_tools.py`)
   - Shared utilities reduce duplication across bot scripts
   - Adds ~800 lines of code (well-structured, well-documented)

3. **Testing surface**:
   - More features = more edge cases to test
   - All features are Discord API thin wrappers (limited custom logic to test)
   - Graceful degradation on permission failures (try/except with logging)

## Implementation Notes

All 8 bot scripts were updated with consistent patterns:

1. Import shared utilities from `discord_ux_utils.py`
2. Wrap agent loops with `keep_typing(channel)` context manager
3. Add channel onboarding in `on_ready` handler
4. Auto-thread detection in message handlers
5. Register poll and pin tools with LLM (where appropriate for bot persona)

Configuration defaults ensure zero-config deployments work out of the box, while power users can fine-tune behavior via environment variables.

## References

- **Implementation Specification**: Writer Agent wiki (Discord Bot Fleet UI/UX Enhancement Specifications)
- **Discord API Documentation**:
  - Typing endpoint: https://discord.com/developers/docs/resources/channel#trigger-typing-indicator
  - Poll API: https://discord.com/developers/docs/resources/poll
  - Thread creation: https://discord.com/developers/docs/resources/channel#start-thread-without-message
  - Pin management: https://discord.com/developers/docs/resources/channel#pin-message
  - Message flags: https://discord.com/developers/docs/resources/channel#message-object-message-flags
- **Related ADRs**:
  - ADR-014: WRITER Playbook Integration
  - ADR-013: Slack MCP Migration
  - ADR-008: Cross-Platform Notifications
- **Discord.py Documentation**: https://discordpy.readthedocs.io/en/stable/
