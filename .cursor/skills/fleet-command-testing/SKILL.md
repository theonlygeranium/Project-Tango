---
name: fleet-command-testing
description: >-
  Run the comprehensive Fleet Command API test suite against the Schubert bot
  fleet. Validates all 19 API endpoints, ~200+ configurable parameters across
  7 bots, config persistence to disk, service restart reliability, Discord
  bot behavioral changes, and edge cases. Use when the user asks to test the
  fleet, run API tests, validate config changes, check bot health, or run
  the full test suite.
---

# Fleet Command Testing

Run the comprehensive Fleet Command API test suite against the Schubert
Discord bot fleet. The suite validates the entire UI → API → Config → Bot
pipeline end-to-end.

## What This Tests

| Phase | Tests | What |
|-------|-------|------|
| Phase 0 | 6 | Prerequisites: API health, auth, UI live, Discord token, all bots online, config snapshot |
| Phase 1 | 6 | Authentication: no token, wrong token, correct token, health, PUT/POST without auth |
| Phase 2 | 36 | Read-only: all GET endpoints for fleet, bots, scheduler, memory |
| Phase 3 | 83 | Bot config writes: LLM, prompt, guardrails, memory, MCP, multi-agent, voice, self-healing, self-improvement params |
| Phase 4 | 27 | Fleet section writes: protocol, conversation, context_builder, scheduler, memory config |
| Phase 5 | 11 | Service restarts: individual, cooldown, config change + restart, sequential |
| Phase 7 | 16 | Discord behavioral: responsiveness, temperature, system prompt, rate limit, max length, delegation, scheduler |
| Phase 8 | 12 | Edge cases: invalid values, non-existent bots, partial updates, concurrent writes, file integrity |
| Phase 9 | 3 | Cleanup: restore config, restart all, verify |
| **Total** | **~200** | |

## Quick Start — Run Full Suite

```bash
# Set environment variables
export FLEET_API_TOKEN=dmL5dDLoLelxvmiqyVqBAowP5EJ-2fOpDUBVcPtIhhM
export DISCORD_BOT_TOKEN=$(grep DISCORD_TOKEN /opt/Project-Tango/.env | cut -d= -f2)

# Run all phases (takes ~30 min due to restart cooldowns)
cd /opt/Project-Tango/scripts
python3 fleet_command_test.py --output /tmp/fleet-test-results.json
```

## Run Specific Phases

```bash
# Only API tests (no Discord, no restarts — fast, ~2 min)
python3 fleet_command_test.py --phase 0 --phase 1 --phase 2 --phase 3 --phase 4 --phase 8

# Only Phase 0 (prerequisites check — ~10 sec)
python3 fleet_command_test.py --phase 0

# Only Phase 3 (bot config writes — ~30 sec)
python3 fleet_command_test.py --phase 3

# Only Phase 8 (edge cases — ~10 sec)
python3 fleet_command_test.py --phase 8

# Skip Discord behavioral tests (saves ~20 min)
python3 fleet_command_test.py --no-discord

# Skip service restart tests (saves ~10 min)
python3 fleet_command_test.py --no-restart

# Skip both Discord and restarts (API-only smoke test — ~3 min)
python3 fleet_command_test.py --no-discord --no-restart
```

## Environment Variables

| Variable | Required | Default | Where to Find |
|----------|----------|---------|---------------|
| `FLEET_API_TOKEN` | Yes | — | `fleet-api.service` systemd env |
| `DISCORD_BOT_TOKEN` | For Phase 7 | — | `/opt/Project-Tango/.env` `DISCORD_TOKEN` |
| `FLEET_API` | No | `https://api-command.schubert.life` | — |

## Bot Channel and ID Reference

| Bot | Channel ID | Bot User ID | Service |
|-----|-----------|-------------|---------|
| Admiral | 1538476446157115442 | 1538476585445892179 | schubert-bot.service |
| Architect | 1539473266400432208 | 1538766501035642890 | schubert-architect.service |
| Quartermaster | 1538818248542396428 | 1538817623045832746 | schubert-quartermaster.service |
| Cartographer | 1538818895706718269 | 1538818587119067206 | schubert-cartographer.service |
| Dr. Voss | 1539104998821068880 | 1539047086597873684 | schubert-dr-voss.service |
| Proctor | 1539159059071111190 | 1539047471899086988 | schubert-proctor.service |
| Cortex | 1539173946698498088 | 1539172849569243217 | cortex-bot.service |

## Test Methodology

Every parameter test follows this pattern:

1. **READ** — GET current value via API
2. **SAVE** — Record original value for cleanup
3. **WRITE** — PUT new value via API
4. **VERIFY FILE** — Check `fleet-config.json` on disk
5. **RESTART** — POST restart (if behavioral test)
6. **VERIFY ACTIVE** — Poll status until online
7. **VERIFY READBACK** — GET confirms new value persisted
8. **DISCORD CHECK** — Send test message, observe response (if behavioral)
9. **REVERT** — PUT original value back
10. **RESTART** — Apply revert

## Known Issues

- **No input validation**: The API accepts invalid values (temp=-1, max_tokens=0) without rejection
- **PUT /api/fleet/config full replace**: Endpoint does full config replace, not deep merge — must send full config for partial updates
- **30-second restart cooldown**: Consecutive restarts on the same bot must wait 30s
- **Config cached at startup**: Changes require a service restart to take effect
- **Proctor high threshold**: Proctor may not respond to simple messages (response_threshold=0.9)

## Related Files

| File | Purpose |
|------|---------|
| `scripts/fleet_command_test.py` | Main test suite (this skill) |
| `scripts/fleet_test_suite.py` | Static analysis tests (26 tests) |
| `scripts/fleet_health_monitor.py` | Automated health monitor (systemd timer) |
| `scripts/cortex_conversation_test.py` | Cortex conversation test |
| `config/fleet-config.json` | Fleet configuration file |
| `fleet-api/` | Fleet API backend source |

## Using /loop for Recurring Tests

```
/loop 2h Run Phase 0 and Phase 2 of the fleet command test suite and report any failures
```

This will run a quick health check every 2 hours and alert on any issues.
