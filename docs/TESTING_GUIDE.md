# Testing Guide: Discord-Slack Integration & WRITER Playbooks

## Current Status Overview

### ✅ Phase 1: Discord→Slack Notifications
**Status:** Code integrated, **NOT YET ACTIVE** (waiting for Slack webhook URLs)

**What's Built:**
- `slack_notifier.py` module ✅
- Integrated into Architect, Dr. Voss, Proctor bots ✅
- Documentation complete ✅

**What's Missing:**
- Slack incoming webhook URLs in `.env`
- Once added, requires bot restart to activate

### ✅ Phase 2: WRITER Playbook Integration
**Status:** **FULLY WORKING** (tested with real webhook invocation)

**What's Built:**
- `writer_playbook.py` module ✅
- Natural language parsing ✅
- Real webhook invocation tested ✅
- Test suite passing ✅

**What's Missing:**
- Integration into Architect Discord bot (waiting for Phase 1 deployment)

---

## How to Test Phase 1 (Discord→Slack Notifications)

### Current State: Code Verification

**✅ You can verify the code is integrated:**

```bash
# Check Slack notifier imports are in place
grep "from slack_notifier import" /opt/Project-Tango/scripts/*-bot.py

# Check notification calls exist
grep "send_.*_alert\|send_.*_report" /opt/Project-Tango/scripts/*-bot.py

# Verify all 3 bots are running
systemctl status schubert-architect schubert-dr-voss schubert-proctor
```

**Expected output:** All 3 bots show "active (running)"

### After Getting Webhook URLs: Full Testing

**Step 1: Add webhooks to .env**
```bash
sudo -u z121532 nano /opt/Project-Tango/.env
```

Add these lines:
```
SLACK_WEBHOOK_TANGO_OPS=https://hooks.slack.com/services/REPLACE_ME.../B.../xxx
SLACK_WEBHOOK_TANGO_REPORTS=https://hooks.slack.com/services/REPLACE_ME.../B.../yyy
```

**Step 2: Restart bots**
```bash
sudo systemctl restart schubert-architect schubert-dr-voss schubert-proctor
```

**Step 3: Test Architect Deployment Notification**

In Discord #architect channel, send:
```
@The Architect deploy a test file at /tmp/slack_test.txt with content "testing slack integration"
```

**Expected:** 
- Architect creates the file
- Slack `#tango-ops` receives notification: "🚀 File Deployed: slack_test.txt"

**Step 4: Test Dr. Voss Health Alert**

Health alerts trigger automatically when services fail. To simulate:
```bash
# Stop a non-critical service temporarily
sudo systemctl stop tango-tts.service

# Wait 1-2 minutes for Dr. Voss health check to detect it
```

**Expected:**
- Dr. Voss posts alert to Discord #dr-voss channel
- Slack `#tango-ops` receives notification: "⚠️ Health Alert: Service tango-tts.service is inactive"

**Step 5: Test Proctor Performance Report**

Proctor sends daily reports at 8:00 UTC. To test immediately:

*This one is harder to test manually - it runs on a schedule. Best to wait for natural daily report.*

---

## How to Test Phase 2 (WRITER Playbook Integration)

### Current State: Fully Functional (Standalone)

**✅ Test Natural Language Parsing:**

```bash
cd /opt/Project-Tango/scripts
/opt/Project-Tango/backend/venv/bin/python test_writer_integration.py
```

**Expected output:**
- ✓ Natural language parsing works
- ✓ Playbook registry configured
- ⚠ Real invocation NOT tested (dry run mode)

**✅ Test Real Webhook Invocation:**

```bash
cd /opt/Project-Tango/scripts
/opt/Project-Tango/backend/venv/bin/python test_writer_integration.py --invoke
```

**Expected output:**
- ✓ Natural language parsing works
- ✓ Playbook registry configured
- ✓ Real invocation tested
- Thread ID: `<uuid>`
- Status: `running`

**Verify in WRITER app:**
1. Go to https://app.writer.com
2. Navigate to Writer Agent sessions
3. Look for session with thread ID from output
4. Confirm it's running with inputs:
   - `SESSION_PART_OVERRIDE`: test-from-schubert-{timestamp}
   - `SEND_EMAILS_OVERRIDE`: NO

### After Full Integration: Discord Testing

**Once Architect bot is updated, you can test from Discord:**

In Discord #architect-work channel (ID: `1539473266400432208`), send:
```
@The Architect invoke cape playbook session=my-test
```

**Expected:**
- Architect responds: "Triggering WRITER playbook..."
- Architect provides thread ID and session URL
- Slack #work-channel receives: "🚀 WRITER Playbook Triggered: CAPE Email Workflow"
- Session appears in WRITER app

**Alternative natural language formats that should work:**
```
@The Architect run the cape email workflow
@The Architect trigger writer playbook cape
@The Architect can you invoke the cape playbook?
```

---

## Quick Verification Checklist

### Phase 1 Readiness
- [x] `slack_notifier.py` exists
- [x] Architect bot imports slack_notifier
- [x] Dr. Voss bot imports slack_notifier
- [x] Proctor bot imports slack_notifier
- [x] All 3 bots are running
- [ ] Slack webhooks in `.env` (BLOCKED: waiting for admin approval)
- [ ] Bots restarted with new webhooks
- [ ] Test notification sent successfully

### Phase 2 Readiness
- [x] `writer_playbook.py` exists
- [x] Natural language parsing works
- [x] Playbook registry configured
- [x] Real webhook invocation tested
- [x] Test session created in WRITER
- [ ] Integrated into Architect bot (waiting on Phase 1)
- [ ] Discord command test successful
- [ ] End-to-end Discord→WRITER→Slack tested

---

## Common Issues & Troubleshooting

### Issue: Bot doesn't send Slack notifications

**Check 1: Webhooks configured?**
```bash
grep SLACK_WEBHOOK /opt/Project-Tango/.env
```
Should show webhook URLs. If empty, add them.

**Check 2: Bots restarted after adding webhooks?**
```bash
sudo systemctl status schubert-architect | grep "Active"
```
If "Active since" timestamp is before you added webhooks, restart:
```bash
sudo systemctl restart schubert-architect
```

**Check 3: Check bot logs for errors**
```bash
sudo journalctl -u schubert-architect -n 50 --no-pager | grep -i slack
```

### Issue: WRITER playbook doesn't trigger

**Check 1: Test standalone script works**
```bash
cd /opt/Project-Tango/scripts
/opt/Project-Tango/backend/venv/bin/python test_writer_integration.py --invoke
```

**Check 2: Check API key is valid**
- API key in `writer_playbook.py`: `36373b4f...20e8`
- If expired, get new one from WRITER app

**Check 3: Check playbook ID is correct**
- Playbook ID: `ccbaeea5-22ea-4ed7-86f8-99ddb30535cb`
- Verify in WRITER app webhook settings

---

## Testing Timeline

### Now (Before Webhook Approval)
✅ Phase 2 fully testable with standalone script  
⚠️ Phase 1 code complete but not active  

### After Webhook Approval (30 min deployment)
✅ Phase 1 activates - test Discord→Slack notifications  
✅ Architect bot updated with WRITER integration  
✅ Full end-to-end testing available  

### Final Validation
1. Discord #architect → deploy file → Slack notification ✓
2. Discord #architect-work → invoke playbook → WRITER session ✓
3. Discord #architect-work → invoke playbook → Slack notification ✓
4. Dr. Voss health alert → Slack notification ✓

---

**Created:** 2026-08-18  
**Status:** Phase 2 ready for testing NOW, Phase 1 waiting on webhooks
