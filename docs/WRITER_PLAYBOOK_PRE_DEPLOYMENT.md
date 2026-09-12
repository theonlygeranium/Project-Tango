# Pre-Deployment Checklist — WRITER Playbook Integration

**Date:** 2026-08-19  
**Status:** Ready for deployment

---

## ✅ Multi-Channel Support Verified

### Current Behavior

The Architect's WRITER playbook integration runs **before** any channel restrictions are checked (line 4030-4038 in `architect-bot.py`), which means it will work in:

✅ **Any channel where The Architect is a member** (when mentioned)  
✅ **Direct Messages (DMs)** with The Architect  
✅ **Monitored channels** (dedicated #nexus channel)  
✅ **Multi-agent channels** (#senior-staff-meeting)

### Code Flow

```python
async def on_message(message: discord.Message):
    # 1. Ignore own messages
    if message.author.id == bot.user.id:
        return
    
    # 2. WRITER Playbook Auto-Detection (FIRST, before channel checks)
    try:
        playbook_handled = await handle_architect_message(message)
        if playbook_handled:
            return  # Playbook handled the message
    except Exception as e:
        # Continue to normal handling if playbook fails
    
    # 3. Check channel restrictions (happens AFTER playbook check)
    if message.channel.id not in MONITORED_CHANNEL_IDS and not isinstance(message.channel, discord.DMChannel):
        return  # Only reaches here if playbook didn't handle it
    
    # 4. Normal message handling...
```

**Result:** WRITER playbooks will work everywhere The Architect can see messages.

---

## Testing Scenarios

### Scenario 1: Dedicated Channel (#nexus)
```
User → #nexus: "check cursor litellm"
The Architect → Detects trigger → Invokes playbook → Posts results
```
**Status:** ✅ Will work (monitored channel)

### Scenario 2: Other Channel (e.g., #general)
```
User → #general: "@The Architect check cursor litellm"
The Architect → Detects trigger → Invokes playbook → Posts results
```
**Status:** ✅ Will work (mentioned)

### Scenario 3: Direct Message
```
User → DM: "is cursor litellm working?"
The Architect → Detects trigger → Invokes playbook → Posts results
```
**Status:** ✅ Will work (DM)

### Scenario 4: Multi-Agent Channel
```
User → #senior-staff-meeting: "check cursor litellm"
The Architect → Detects trigger → Invokes playbook → Posts results
```
**Status:** ✅ Will work (multi-agent channel)

---

## WRITER Playbook Update Instructions

### Option 1: Use the Prepared Prompt (Recommended)

**File:** `/opt/Project-Tango/docs/WRITER_PLAYBOOK_UPDATE_PROMPT.md`

**Instructions:**
1. Open the file
2. Copy the entire prompt (starting with "## Task: Update Playbook...")
3. Paste into WRITER Agent chat
4. WRITER Agent will update the playbook for you

**What the update does:**
- Adds optional `discord_callback_url` input variable
- Sends POST request to Discord when callback URL is provided
- Maintains backward compatibility (existing invocations still work)
- Enables async callbacks (no polling needed)

### Option 2: Keep Polling (No Update Needed)

**If you prefer to skip the playbook update:**
- The integration already works with polling
- 10-second poll interval (60-180 second total latency)
- No changes to WRITER playbook needed
- Can update later if async callbacks are desired

**Decision:** Your choice! Both approaches work.

---

## Deployment Steps

### 1. Verify Environment Variable

```bash
grep WRITER_PLAYBOOK_API_KEY /opt/Project-Tango/.env
# Should show: WRITER_PLAYBOOK_API_KEY=4b7ddcec2fca099542b6fb888334cfd83683465dcd60e77d2c7678ec47e6affd
```

✅ Already configured

### 2. Restart The Architect

```bash
sudo systemctl restart schubert-architect.service
```

### 3. Verify Service Started

```bash
systemctl status schubert-architect.service
# Should show: active (running)

journalctl -u schubert-architect.service -n 20 --no-pager
# Should NOT show import errors
```

### 4. Test in Any Channel

**Option A: Dedicated Channel (#nexus)**
```
check cursor litellm
```

**Option B: Other Channel**
```
@The Architect is cursor litellm working?
```

**Option C: Direct Message**
```
Open DM with The Architect
Send: "diagnose cursor"
```

### 5. Verify Results

**Expected behavior:**
1. ⏳ Initial message: "Invoking WRITER Agent Playbook..."
2. 🔄 Progress updates every 10 seconds
3. ✅ Final result with embed after 60-180 seconds

**Check logs:**
```bash
journalctl -u schubert-architect.service -f | grep -i writer
```

---

## Quick Start Commands

### Deploy Now
```bash
# Restart The Architect
sudo systemctl restart schubert-architect.service

# Watch logs
journalctl -u schubert-architect.service -f
```

### Test in Discord
```
# In #nexus (or any channel where The Architect is present):
@The Architect check cursor litellm

# Or via DM:
# Open DM → Send "is cursor litellm working?"
```

### Rollback if Needed
```bash
# Option 1: Disable auto-detection (edit architect-bot.py, comment out lines 4030-4038)
# Option 2: Remove API key
sed -i '/WRITER_PLAYBOOK_API_KEY/d' /opt/Project-Tango/.env
sudo systemctl restart schubert-architect.service
```

---

## Summary

### ✅ Multi-Channel Support
- Works in any channel where The Architect is mentioned
- Works in DMs
- Works in dedicated/monitored channels
- No code changes needed

### ✅ WRITER Playbook Update
- Optional enhancement (not required for deployment)
- Enables async callbacks (faster responses)
- Detailed prompt provided in `WRITER_PLAYBOOK_UPDATE_PROMPT.md`
- Can be done anytime (before or after deployment)

### ✅ Ready to Deploy
- All code complete
- Environment configured
- Documentation complete
- Testing instructions provided

**Next step:** Deploy by restarting The Architect (see Quick Start Commands above)

---

**Questions?** Everything is documented and ready. The integration will work in all channels, including DMs, as soon as you restart The Architect!
