# Native Discord Poll Creation - Quick Start

## What This Does

Adds a `create_poll` agent tool that creates native Discord polls with voting buttons. The agent can now gather human feedback, make team decisions, and get consensus on design choices.

## Example Conversations

### Senior Staff Meeting Decision

```
User: "Admiral, we need to decide on the database migration strategy. 
       Can you create a poll with these options:
       1. Migrate all at once this weekend
       2. Gradual migration over 2 weeks  
       3. Postpone until Q4
       Keep it open for 48 hours."

Agent: 📊 Creating poll...
       [Native Discord poll appears with voting buttons]
       ✅ Poll created! It will close in 48 hours.
```

### Feature Rating

```
User: "Create a poll asking the team to rate the new auth flow from 1 to 5"

Agent: 📊 Creating poll: "Rate the new authentication flow"
       [Poll with options: 1 - Poor, 2 - Fair, 3 - Good, 4 - Great, 5 - Excellent]
       ✅ Poll posted! Duration: 24 hours
```

### Bug Prioritization

```
User: "Which bug should we fix first? Create a poll with:
       - Bug #123: Login timeout
       - Bug #456: Data sync
       - Bug #789: UI rendering"

Agent: 📊 Creating priority poll...
       [Native Discord poll with 3 bug options]
       ✅ Team can now vote on the priority!
```

## Files Changed

### New Files
- `scripts/poll_tools.py` - Poll creation implementation
- `docs/POLL_TOOLS.md` - Full documentation
- `docs/POLL_TOOLS_QUICKSTART.md` - This file

### Modified Files
- `scripts/schubert-bot-v2.py` - Added poll tool integration
- `scripts/tool_descriptions.py` - Added poll progress descriptions

## Technical Details

### Discord API Constraints

- **Question**: Max 300 characters
- **Answers**: 2-10 options, max 55 characters each
- **Duration**: 1-768 hours (1 hour to 32 days)
- **Multi-select**: Optional (default: single-select)

### Validation Examples

✅ **Valid:**
```json
{
  "question": "What's your favorite color?",
  "answers": ["Red", "Blue", "Green", "Yellow"],
  "duration_hours": 24,
  "allow_multiselect": false
}
```

❌ **Invalid - Question too long:**
```json
{
  "question": "This is a very long question that exceeds the 300 character limit imposed by Discord's native poll API which means this poll creation will fail validation and return an error message to the agent so it can try again with a shorter question...",
  "answers": ["A", "B"]
}
```

❌ **Invalid - Too many answers:**
```json
{
  "question": "Pick your favorites",
  "answers": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]
}
```

## Testing Checklist

### Before Deployment

- [x] Tool definition in OpenAI function calling format
- [x] Parameter validation (question, answers, duration)
- [x] Integration with schubert-bot-v2.py agent loop
- [x] Memory storage for poll creation events
- [x] Progress descriptions for live updates
- [x] Error handling and clear error messages
- [x] Documentation written

### After Deployment

- [ ] Create a test poll in a Discord channel
- [ ] Verify native Discord voting UI appears
- [ ] Verify votes are tracked in real-time
- [ ] Test validation errors (too long question, too many answers)
- [ ] Check logs for poll creation events
- [ ] Test multi-select polls
- [ ] Test different durations (1h, 24h, 7 days)

### Manual Test Commands

```bash
# Check if bot service is running
sudo systemctl status schubert-bot.service

# View recent logs
sudo journalctl -u schubert-bot.service -n 50 | grep -i poll

# Restart bot (if needed for hot reload)
sudo systemctl restart schubert-bot.service
```

## Integration Status

✅ **Completed:**
- Core poll creation function with validation
- OpenAI function calling tool definition
- Integration in `execute_tool_v2()` (text mode)
- Integration in `execute_tool_v2_voice()` (voice mode)
- Memory storage for poll events
- Progress descriptions in `tool_descriptions.py`
- System prompt addition explaining poll usage
- Error handling with clear messages
- Dual-strategy API calling (discord.py + aiohttp fallback)

## Usage Examples for Agents

### When to Use Polls

The agent should create polls when:
- **Multiple valid options exist** and human preference is needed
- **Team consensus** is required for a decision
- **Feedback collection** on a feature or design
- **Priority ranking** of tasks or issues
- **Simple surveys** with predefined answer options

### When NOT to Use Polls

Don't create polls for:
- **Yes/no questions** that need immediate answers (use confirmation dialogs)
- **Open-ended questions** (use regular chat messages)
- **Questions requiring detailed explanations** (use discussion threads)
- **Time-sensitive decisions** that can't wait for votes

## Troubleshooting

### Poll Creation Fails

**Error:** `"Bot token required for poll creation"`
- **Fix:** Ensure `DISCORD_BOT_TOKEN` is set in environment

**Error:** `"HTTP 403: Missing permissions"`
- **Fix:** Check bot has "Send Messages" and "Embed Links" permissions in the channel

**Error:** `"Validation failed: Question exceeds 300 characters"`
- **Fix:** Agent will automatically retry with a shorter question

### No Voting UI Appears

**Issue:** Poll message sent but no voting buttons
- **Cause:** Discord.py version doesn't support poll format
- **Fix:** Fallback to aiohttp should handle this automatically
- **Verify:** Check logs for "fallback" or "raw aiohttp" messages

### Votes Not Updating

**Issue:** Vote counts don't update in real-time
- **Cause:** This is a Discord client issue, not API
- **Fix:** Users need to refresh Discord or click the poll to see updated counts

## Next Steps

1. **Deploy:** Restart schubert-bot.service to load the new tool
2. **Test:** Create a test poll in a dev channel
3. **Monitor:** Watch logs for any errors
4. **Document:** Add any learned lessons to this file

## Support

- **Documentation:** `docs/POLL_TOOLS.md`
- **Implementation:** `scripts/poll_tools.py`
- **Integration:** `scripts/schubert-bot-v2.py` (lines ~93-96, ~1720-1740, ~1908-1920)
- **Logs:** `sudo journalctl -u schubert-bot.service -f | grep poll`

---

**Ready for Testing:** ✅  
**Production Ready:** Pending testing  
**Version:** 1.0  
**Date:** 2026-08-19
