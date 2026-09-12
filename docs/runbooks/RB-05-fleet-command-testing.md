# RB-05: Fleet Command API Testing

**Runbook ID:** RB-05
**Date:** 2026-08-20
**Status:** Active

## Purpose

Comprehensive end-to-end testing of the Fleet Command API and Discord bot fleet.
Validates all 19 API endpoints, ~200+ configurable parameters, config persistence,
service restart reliability, and Discord bot behavioral changes.

## Prerequisites

- Access to Schubert server (SSH or Cursor)
- Fleet API token: available in `fleet-api.service` systemd env
- Discord bot token: available in `/opt/Project-Tango/.env` (`DISCORD_TOKEN`)
- All 7 bot services running
- Fleet API online at `https://api-command.schubert.life`

## Quick Run

### Full Test Suite (~30 minutes)

```bash
export FLEET_API_TOKEN=dmL5dDLoLelxvmiqyVqBAowP5EJ-2fOpDUBVcPtIhhM
export DISCORD_BOT_TOKEN=$(grep DISCORD_TOKEN /opt/Project-Tango/.env | cut -d= -f2)

cd /opt/Project-Tango/scripts
python3 fleet_command_test.py --output /tmp/fleet-test-results.json
```

### API-Only Smoke Test (~3 minutes)

```bash
export FLEET_API_TOKEN=dmL5dDLoLelxvmiqyVqBAowP5EJ-2fOpDUBVcPtIhhM

cd /opt/Project-Tango/scripts
python3 fleet_command_test.py --no-discord --no-restart --output /tmp/fleet-smoke.json
```

### Single Phase

```bash
# Phase 0 only (prerequisites check)
python3 fleet_command_test.py --phase 0

# Phase 3 only (bot config writes)
python3 fleet_command_test.py --phase 3

# Phase 8 only (edge cases)
python3 fleet_command_test.py --phase 8
```

## Test Phases

| Phase | Tests | Duration | Risk | Description |
|-------|-------|----------|------|-------------|
| 0 | 6 | 5 min | Low | Prerequisites & connectivity |
| 1 | 6 | 1 min | Low | API authentication |
| 2 | 36 | 2 min | Low | Read-only endpoint validation |
| 3 | 83 | 1 min | Low | Bot config write + readback + file persistence |
| 4 | 27 | 1 min | Medium | Fleet section writes (protocol, conversation, scheduler, memory) |
| 5 | 11 | 10 min | Medium | Service restart reliability (30s cooldowns) |
| 7 | 16 | 20 min | Medium | Discord bot behavioral verification |
| 8 | 12 | 1 min | Low | Edge cases & input validation |
| 9 | 3 | 5 min | Low | Cleanup & restoration |

## What To Look For

### Critical Failures

- **API health down**: Fleet API is unreachable
- **Auth not working**: Token is invalid or expired
- **Bots offline**: One or more bot services are down
- **Config not persisting**: PUT succeeds but GET returns old value
- **Config file corrupted**: JSON parse error on `fleet-config.json`

### Known Issues (expected failures)

- **EDGE-01/02/03**: API accepts invalid values (temp=-1, max_tokens=0) — no input validation
- **AUTH-01-06**: API returns 401 instead of 403 for unauthorized requests
- **PUT /api/fleet/config**: Does full replace, not deep merge — partial updates cause 500

### Success Criteria

- 90%+ pass rate for API tests (Phases 0-4, 8)
- All 7 bots respond to Discord messages (Phase 7)
- Config restored to original after testing (Phase 9)
- All bots online after cleanup

## After Testing

### If All Tests Pass

1. Review the results file for any warnings
2. Archive results: `cp /tmp/fleet-test-results.json /opt/Project-Tango/docs/test-results/$(date +%Y%m%d)-fleet-test.json`
3. No further action needed

### If Tests Fail

1. Check which phase(s) failed
2. For API failures: check `fleet-api.service` logs: `journalctl -u fleet-api.service -n 50`
3. For bot failures: check individual bot service logs
4. For config issues: verify `fleet-config.json` is valid JSON
5. If config was corrupted: restore from backup at `/tmp/fleet-config-backup.json`

### Config Restoration

If the config was left in a bad state after testing:

```bash
# Restore from the backup taken during Phase 0
curl -s -X PUT \
  -H "Authorization: Bearer $FLEET_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/fleet-config-backup.json \
  https://api-command.schubert.life/api/fleet/config

# Restart all bots
for bot in admiral architect quartermaster cartographer dr_voss proctor cortex; do
  curl -s -X POST \
    -H "Authorization: Bearer $FLEET_API_TOKEN" \
    https://api-command.schubert.life/api/bots/$bot/restart
  sleep 32
done
```

## Related Documents

- [Fleet Command Testing Plan (Wiki)](https://wiki.edstratumlabs.ai/doc/fleet-command-testing-plan-aPtKtpFnx0)
- [Fleet Bot Testing Skill](../../.cursor/skills/fleet-command-testing/SKILL.md)
- [RB-02: Service Recovery](RB-02-service-recovery.md)
- [Architecture](../architecture.md)
