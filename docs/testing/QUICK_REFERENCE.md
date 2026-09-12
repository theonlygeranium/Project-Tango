# Proctor Test Framework — Quick Reference

## Quick Start

```bash
# In Proctor's Discord channel:
!test discover        # Find all active bots
!test run            # Run all tests (~1-2 min)
!test results        # View last results
```

## All Commands

| Command | Description |
|---------|-------------|
| `!test run` | Run all 5 test cases |
| `!test run CRITICAL` | Run only CRITICAL priority tests |
| `!test run HIGH` | Run CRITICAL + HIGH tests |
| `!test list` | Show all available tests |
| `!test results` | Display last test results |
| `!test discover` | Scan for active bots |
| `!test` | Show help |

## Test Cases

| Priority | Test Name | What It Tests | Timeout |
|----------|-----------|---------------|---------|
| CRITICAL | bot_responsiveness | All bots respond to health checks | 60s |
| HIGH | expertise_routing | Bots respond to relevant keywords | 45s |
| HIGH | fleet_protocol | FLEET delegation format works | 60s |
| MEDIUM | multi_agent_coordination | Multi-agent channels coordinate | 30s |
| MEDIUM | memory_persistence | Admiral stores/retrieves memories | 45s |

## Auto-Fix

The framework automatically fixes:
- **Offline bots** → Restarts their systemd services
- **Service crashes** → Detects and restarts
- **Transient failures** → Re-runs tests after fix

## Expected Output

### Success
```
🧪 Proctor Bot Test Suite Results

📊 Summary
✅ Passed: 5
❌ Failed: 0
⏭️ Skipped: 0
⏱️ Duration: 23.4s
```

### With Failures
```
📊 Summary
✅ Passed: 3
❌ Failed: 2
⏱️ Duration: 45.1s

❌ Failed Tests
• expertise_routing: Only 60% success rate
• memory_persistence: No response from Admiral

⚠️ Warnings
• Auto-fix applied successfully
• Test passed after auto-fix
```

## Troubleshooting

### Command Not Found
```bash
# Restart Proctor
sudo systemctl restart schubert-proctor.service

# Check status
sudo systemctl status schubert-proctor.service

# View logs
sudo journalctl -u schubert-proctor.service -n 50
```

### No Bots Discovered
```bash
# Check bot services
systemctl status schubert-*.service

# Verify bots are online in Discord
# Make sure Proctor is in same guild
```

### Tests Timing Out
```bash
# Check bot health
!status

# Check LiteLLM
curl http://localhost:4000/health

# Check individual bot channels
```

## Files

| File | Purpose |
|------|---------|
| `/opt/Project-Tango/scripts/proctor_test_framework.py` | Test framework code |
| `/opt/Project-Tango/scripts/proctor-bot.py` | Integration (modified) |
| `/opt/Project-Tango/docs/testing/proctor-test-framework.md` | Full documentation |
| `/opt/Project-Tango/docs/testing/TEST_IMPLEMENTATION_SUMMARY.md` | Implementation summary |

## Adding New Tests

1. Edit `proctor_test_framework.py`
2. Add test function: `async def test_new_feature(runner) -> bool:`
3. Add to `create_test_suite()` function
4. Restart Proctor bot

## Environment Required

Already configured in `/opt/Project-Tango/.env`:
- Bot tokens for all agents
- Channel IDs for all bot channels
- Admin user ID
- LiteLLM configuration

## Bot-to-Service Mapping

| Bot | Service |
|-----|---------|
| Admiral | `schubert-bot.service` |
| Architect | `schubert-architect.service` |
| Quartermaster | `schubert-quartermaster.service` |
| Cartographer | `schubert-cartographer.service` |
| Dr. Voss | `schubert-dr-voss.service` |
| Cortex | `schubert-cortex.service` |
| Proctor | `schubert-proctor.service` |

---

**Status:** ✅ Ready to Use  
**Last Updated:** 2026-08-18
