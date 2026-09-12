# Discord Typing Indicator Integration Summary

**Date:** 2026-08-19
**Task:** Integrate native Discord typing indicators in agent loops across all bots

## Implementation Pattern

All bot agent loops now use the following pattern:

```python
from discord_ux_utils import keep_typing

async def run_agent_loop(...):
    # ... setup code ...
    
    # Start typing indicator
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(keep_typing(channel, stop_typing))
    
    try:
        for iteration in range(MAX_ITERATIONS):
            # ... agent loop logic ...
    
    finally:
        # Stop typing indicator
        stop_typing.set()
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
```

## Modified Files

### 1. **scripts/schubert-bot.py**
- **Functions modified:**
  - `run_agent_loop()` - text mode agent loop
  - `run_agent_loop_voice()` - voice mode agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel` (or `text_channel` for voice)

### 2. **scripts/quartermaster-bot.py**
- **Functions modified:**
  - `run_agent()` - main agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel`

### 3. **scripts/architect-bot.py**
- **Functions modified:**
  - `run_agent_loop()` - main agent loop with streaming support
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel`

### 4. **scripts/proctor-bot.py**
- **Functions modified:**
  - `run_agent_loop()` - main agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel`

### 5. **scripts/dr-voss-bot.py**
- **Functions modified:**
  - `run_agent_loop()` - main agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel`

### 6. **scripts/cortex-bot.py**
- **Functions modified:**
  - `run_agent_loop()` - main agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel`

### 7. **scripts/cartographer-bot.py**
- **Functions modified:**
  - `run_agent()` - main agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel`

### 8. **scripts/dr-cortex-bot.py**
- **Functions modified:**
  - `run_agent_loop_v2()` - V2 agent loop with project context
  - `run_agent_loop_voice_v2()` - V2 voice mode agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel` (or `text_channel` for voice)

### 9. **scripts/tango-discord-agent.py**
- **Functions modified:**
  - `run_agent_loop()` - main agent loop
- **Import added:** `from discord_ux_utils import keep_typing`
- **Behavior:** Typing indicator targets `message.channel`

## Technical Details

### Background Task Approach
- Uses `asyncio.create_task()` to run typing indicator in background
- NOT using `async with channel.typing():` context manager because intermediate message sends would stop the indicator
- Typing indicator re-triggers every 8 seconds (Discord typing expires after 10 seconds)

### Cleanup Strategy
- Uses `finally` block to ensure typing indicator is always stopped
- Cancels the task and catches `asyncio.CancelledError` gracefully
- Typing indicator stops when agent completes (success, timeout, or error)

### Channel Targeting
- Typing indicator targets the `response_channel` (could be main channel or thread)
- Works alongside `AgentProgressView` updates where applicable
- No interference with intermediate message sends during agent loop

## Testing Checklist

- [x] Typing indicator implementation added to all agent loops
- [ ] Typing indicator appears within 1 second of agent start
- [ ] Persists through long LLM calls (>10 seconds)
- [ ] Stops cleanly when agent completes
- [ ] Works alongside AgentProgressView updates
- [ ] No errors in logs related to typing indicator
- [ ] Works in both direct messages and thread responses

## Verification Steps

To verify the typing indicator integration:

1. **Start any bot** (e.g., `sudo systemctl restart architect-bot`)
2. **Send a message** that triggers an agent loop
3. **Observe:** "Bot is typing..." indicator should appear immediately
4. **Monitor:** Indicator should persist throughout LLM processing
5. **Confirm:** Indicator stops when bot sends final response
6. **Check logs:** No errors related to typing indicator

## Notes

- The `keep_typing()` function is defined in `scripts/discord_ux_utils.py`
- It handles all error cases gracefully (permissions, HTTP errors, etc.)
- The typing indicator interval is configurable (default: 8.0 seconds)
- All bots share the same utility module for consistency

## Rollback Procedure

If typing indicators cause issues:

1. Remove the `stop_typing` / `typing_task` code from affected bot scripts
2. Remove the import: `from discord_ux_utils import keep_typing`
3. Restart the affected bot service
4. The bots will continue to function normally without typing indicators
