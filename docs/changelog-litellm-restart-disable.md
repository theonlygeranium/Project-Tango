# LiteLLM Restart Guard — Change Log

**Date:** 2026-08-20
**Time:** 06:10 UTC (initial), 06:16 UTC (revised)
**Requested by:** Captain (via WRITER Agent)
**Performed by:** WRITER Agent (Thread 2245a8c4-808b-41ed-acfd-7834d59b0227)

## Problem

Autonomous agents on Schubert were restarting `polyglot-litellm.service` every 10–30
minutes without a clear operational reason. Each restart caused a ~2.4-second outage
of all LLM traffic (LiteLLM + both socat proxies, due to `Requires=` cascade in the
proxy unit files). The restarts were traced to explicit `systemctl restart
polyglot-litellm.service` commands issued from `/opt/Project-Tango` by autonomous bots.
LiteLLM showed zero errors, zero rate limits, and healthy latency.

## Design Principle

Autonomous restarts are blocked. Human-confirmed restarts are allowed. Each bot uses
its existing confirmation mechanism — no new code paths were introduced.

## Changes Made

### 1. tango-healthcheck.py — HARD BLOCK (automated, no human interaction)
- Removed `LITELLM_SERVICE` from `SAFE_SERVICES`
- Added `polyglot-litellm.service` to `FORBIDDEN_SERVICES` (alert-only, never restart)
- Added `SAFE_SERVICES` guard to Layer 2 endpoint health check
- **Rationale:** This script runs autonomously every 3 minutes with no human in the
  loop. It must never restart LiteLLM. It will log a warning if the endpoint is down.

### 2. tango-discord-bot.py — HUMAN-COMMANDED (double-type confirmation)
- Kept `LITELLM_SERVICE` in `SAFE_SERVICES` (with comment noting confirmation required)
- Not in `FORBIDDEN_SERVICES`
- **Rationale:** This bot only accepts commands from `DISCORD_ADMIN_USER_ID` and
  requires typing `!restart` twice within 30 seconds to confirm. Only the Captain
  can trigger this. `!restart polyglot-litellm.service` will work.

### 3. tango-discord-agent.py — CONFIRMATION REQUIRED (autonomous LLM agent)
- Removed `polyglot-litellm.service` from `FORBIDDEN_SERVICES` (was hard-blocked)
- Added `(r"systemctl\s+(restart|stop)\s+polyglot-litellm", "LiteLLM restart/stop")`
  to `CONFIRM_PATTERNS`
- Updated agent prompt: "requires human confirmation before restart"
- **Rationale:** The LLM can attempt a restart, but `ask_confirmation()` intercepts
  it and requires the Captain to reply `yes` within 60 seconds. Autonomous attempts
  that receive no confirmation are blocked.

### 4. schubert-bot-v2.py — CRITICAL SERVICE (confirmation required)
- Removed `polyglot-litellm.service` from `NEVER_TOUCH_SERVICES` (was hard-blocked)
- Added `polyglot-litellm.service` to `CRITICAL_SERVICES`
- Updated system prompt: "Requires confirmation: polyglot-litellm.service"
- **Rationale:** `is_critical_service_restart()` detects the restart command and
  triggers `ask_confirmation()`. The Captain must reply `yes` within 60 seconds.
  Autonomous attempts cannot self-confirm, so they are blocked.

### 5. schubert-bot.py (v1) — CRITICAL SERVICE (same as v2)
- Same changes as schubert-bot-v2.py

## Summary Table

| Bot/Script | Type | LiteLLM Protection | You Can Restart? |
|---|---|---|---|
| tango-healthcheck.py | Automated timer | FORBIDDEN (hard block) | No (automated, no human) |
| tango-discord-bot.py | Human-commanded | SAFE_SERVICES + double-type | Yes (`!restart polyglot-litellm.service`) |
| tango-discord-agent.py | Autonomous LLM | CONFIRM_PATTERNS | Yes (reply `yes` to confirm) |
| schubert-bot-v2.py | Autonomous | CRITICAL_SERVICES | Yes (reply `yes` to confirm) |
| schubert-bot.py | Autonomous | CRITICAL_SERVICES | Yes (reply `yes` to confirm) |

## Backups

Each file was backed up before editing:
- `*.bak.litellm-restart-disable` in `/opt/Project-Tango/scripts/`

## Services Restarted

tango-discord-bot, schubert-bot, schubert-architect, schubert-cortex — all active.
tango-healthcheck does not need a restart (oneshot timer, re-reads script each run).

## To Revert

Restore from backups:
```bash
cd /opt/Project-Tango/scripts
for f in *.bak.litellm-restart-disable; do
  original=$(echo $f | sed 's/.bak.litellm-restart-disable//')
  cp $f $original
done
```
Then restart the bot services.
