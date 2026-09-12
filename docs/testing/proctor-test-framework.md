# Proctor Bot Test Framework

**Date:** 2026-08-18  
**Purpose:** Comprehensive automated testing framework for Discord bot fleet validation

---

## Overview

The Proctor Test Framework provides comprehensive automated testing capabilities for validating all Discord bots in the Schubert fleet. It tests responsiveness, expertise routing, FLEET protocol delegation, multi-agent coordination, and memory persistence.

## Architecture

### Components

1. **ProctorTestRunner** — Core test execution engine
2. **TestCase** — Individual test definitions with priority levels
3. **TestResult** — Test execution results and diagnostics
4. **Auto-fix Functions** — Automated remediation for common failures

### Test Priorities

- **CRITICAL** (Priority 1): Core functionality tests (bot responsiveness)
- **HIGH** (Priority 2): Important features (expertise routing, FLEET protocol)
- **MEDIUM** (Priority 3): Standard tests (multi-agent coordination, memory)
- **LOW** (Priority 4): Nice-to-have validations

### Test Flow

```
1. Discover Bots → Scan Discord guild for active bot members
2. Register Tests → Load test cases by priority
3. Execute Tests → Run tests sequentially with dependencies
4. Auto-Fix → Apply fixes if tests fail
5. Re-test → Verify fixes worked
6. Report → Generate Discord embed summary
```

## Available Test Cases

### 1. Bot Responsiveness Test
**Priority:** CRITICAL  
**Timeout:** 60s  
**Auto-fix:** Restart offline bot services

Tests that all bots respond to basic health check messages within reasonable time.

**Success Criteria:** 80%+ of discovered bots respond within 20 seconds

**Auto-fix Logic:**
- Detect offline bots
- Map bot names to systemd services
- Restart services with `sudo systemctl restart`
- Wait 5 seconds for initialization
- Re-run test

### 2. Expertise Routing Test
**Priority:** HIGH  
**Timeout:** 45s  
**Depends on:** bot_responsiveness

Tests that bots respond to messages matching their expertise keywords.

**Test Cases:**
- Architect → "code bug needs fixing"
- Quartermaster → "restart docker service"
- Cartographer → "update documentation"
- Dr. Voss → "health check failed"

**Success Criteria:** 75%+ of test cases pass

### 3. FLEET Protocol Test
**Priority:** HIGH  
**Timeout:** 60s  
**Depends on:** bot_responsiveness

Tests that FLEET delegation protocol works correctly between Admiral and specialists.

**Validates:**
- FLEET message format recognition
- Chain ID tracking
- Turn counting
- Anti-loop protection

### 4. Multi-Agent Coordination Test
**Priority:** MEDIUM  
**Timeout:** 30s  
**Depends on:** bot_responsiveness

Tests that multi-agent channels coordinate turn-taking properly.

**Validates:**
- Only relevant experts respond
- No duplicate responses
- Cooldown timers work
- Addressed agent filter works

### 5. Memory Persistence Test
**Priority:** MEDIUM  
**Timeout:** 45s  
**Depends on:** bot_responsiveness

Tests that bots (specifically Admiral) can store and retrieve memories.

**Test Flow:**
1. Send memorable message to Admiral
2. Wait 2 seconds
3. Ask Admiral to recall the message
4. Verify response contains original content

## Usage

### Discord Commands

```bash
# Run all tests
!test run

# Run only CRITICAL priority tests
!test run CRITICAL

# Run CRITICAL and HIGH priority tests
!test run HIGH

# List all available tests
!test list

# Show last test results
!test results

# Discover active bots
!test discover

# Show help
!test
```

### Programmatic Usage

```python
from proctor_test_framework import initialize_test_framework, TestPriority

# Initialize framework
runner = await initialize_test_framework(discord_client, channel_id, admin_user_id)

# Discover bots
await runner.discover_bots()

# Run all tests
await runner.run_all_tests()

# Run only critical tests
await runner.run_all_tests(priority_filter=TestPriority.CRITICAL)

# Check results
for result in runner.results:
    print(f"{result.test_name}: {result.status.value}")
```

## Test Output

### Success Example

```
🧪 Proctor Bot Test Suite Results
Comprehensive bot fleet validation

📊 Summary
✅ Passed: 5
❌ Failed: 0
⏭️ Skipped: 0
⏱️ Duration: 23.4s

Proctor Test Framework • 5 tests executed
```

### Failure Example

```
🧪 Proctor Bot Test Suite Results
Comprehensive bot fleet validation

📊 Summary
✅ Passed: 3
❌ Failed: 2
⏭️ Skipped: 0
⏱️ Duration: 45.1s

❌ Failed Tests
• expertise_routing: Only 60% success rate (threshold: 75%)
• memory_persistence: No response from Admiral after 20s

⚠️ Warnings
• Auto-fix applied successfully
• Test passed after auto-fix

Proctor Test Framework • 5 tests executed
```

## Bot Discovery

The framework automatically discovers bots by scanning the Discord guild for bot members matching known patterns:

| Agent Name | Patterns | Channel Env Var |
|------------|----------|-----------------|
| Admiral | "schubert", "admiral" | `SCHUBERT_BOT_CHANNEL_ID` |
| Architect | "architect" | `ARCHITECT_CHANNEL_ID` |
| Quartermaster | "quartermaster" | `QUARTERMASTER_CHANNEL_ID` |
| Cartographer | "cartographer" | `CARTOGRAPHER_CHANNEL_ID` |
| Dr. Voss | "dr. voss", "dr voss", "voss" | `DR_VOSS_CHANNEL_ID` |
| Cortex | "cortex", "dr. cortex" | `CORTEX_CHANNEL_ID` |

## Auto-Fix Capabilities

### Bot Offline Fix

**Trigger:** Bot responsiveness test fails  
**Action:**
1. Detect which bots didn't respond
2. Map bot names to systemd services:
   - `admiral` → `schubert-bot.service`
   - `architect` → `schubert-architect.service`
   - `quartermaster` → `schubert-quartermaster.service`
   - `cartographer` → `schubert-cartographer.service`
   - `dr_voss` → `schubert-dr-voss.service`
3. Execute `sudo systemctl restart <service>`
4. Wait 5 seconds for initialization
5. Re-run responsiveness test

**Success Rate:** High for transient failures, manual intervention needed for config issues

## Integration with Proctor Bot

The test framework is integrated directly into the Proctor bot's command system:

**File:** `/opt/Project-Tango/scripts/proctor-bot.py`

**Integration Points:**
1. Import in header: `from proctor_test_framework import ...`
2. Global variable: `_test_runner: Optional[ProctorTestRunner] = None`
3. Initialization in `on_ready()`: `_test_runner = await initialize_test_framework(...)`
4. Command handler: `elif cmd == "test":`

## Environment Variables Required

```bash
# Bot tokens
PROCTOR_BOT_TOKEN=<Discord bot token>
SCHUBERT_BOT_ID=<Admiral's bot ID>

# Channel IDs
PROCTOR_CHANNEL_ID=<Proctor's dedicated channel>
SCHUBERT_BOT_CHANNEL_ID=<Admiral's channel>
ARCHITECT_CHANNEL_ID=<Architect's channel>
QUARTERMASTER_CHANNEL_ID=<Quartermaster's channel>
CARTOGRAPHER_CHANNEL_ID=<Cartographer's channel>
DR_VOSS_CHANNEL_ID=<Dr. Voss's channel>
CORTEX_CHANNEL_ID=<Dr. Cortex's channel>
SENIOR_STAFF_CHANNEL_ID=<Multi-agent channel>

# Admin
ADMIN_USER_ID=<Discord admin user ID>

# Infrastructure
LITELLM_BASE_URL=http://127.0.0.1:4000/v1
LITELLM_MASTER_KEY=<LiteLLM API key>
```

## Adding New Tests

### Step 1: Define Test Function

```python
async def test_new_feature(runner: ProctorTestRunner) -> bool:
    """Test description."""
    logger.info("Testing new feature...")
    
    # Test logic here
    result = await runner.send_message_to_bot(
        "admiral",
        "test message",
        wait_for_response=True,
        timeout=15
    )
    
    return result is not None
```

### Step 2: Define Auto-Fix (Optional)

```python
async def auto_fix_new_feature(runner: ProctorTestRunner) -> bool:
    """Auto-fix for new feature test failures."""
    logger.info("Attempting auto-fix...")
    
    # Fix logic here
    
    return True  # Return True if fix succeeded
```

### Step 3: Register Test Case

```python
def create_test_suite() -> List[TestCase]:
    return [
        # ... existing tests ...
        TestCase(
            name="new_feature",
            description="Test new feature functionality",
            test_function=test_new_feature,
            priority=TestPriority.MEDIUM,
            timeout_seconds=30,
            depends_on=["bot_responsiveness"],
            auto_fix_function=auto_fix_new_feature,
        ),
    ]
```

## Known Limitations

1. **Channel Access:** Tests require the Proctor bot to have access to all bot channels
2. **Permissions:** Auto-fixes that restart services require sudo permissions
3. **Timeouts:** Long-running tests may time out if bots are slow to respond
4. **Concurrency:** Tests run sequentially to avoid race conditions
5. **FLEET Testing:** Full FLEET protocol testing requires live delegation (currently placeholder)

## Troubleshooting

### Test Framework Not Initialized

**Symptom:** `!test` command returns "Test framework not initialized"

**Causes:**
- Import error in `proctor_test_framework.py`
- Missing dependencies
- Initialization failure in `on_ready()`

**Fix:**
1. Check Proctor bot logs: `sudo journalctl -u schubert-proctor.service -n 100`
2. Test import: `python3 -c "from scripts.proctor_test_framework import *"`
3. Restart Proctor: `sudo systemctl restart schubert-proctor.service`

### Bots Not Discovered

**Symptom:** `!test discover` finds 0 bots

**Causes:**
- Bots are offline
- Name patterns don't match
- Guild access issue

**Fix:**
1. Check bot services: `systemctl status schubert-*.service`
2. Verify bot names in Discord match patterns
3. Ensure Proctor is in same guild as other bots

### Tests Timing Out

**Symptom:** All tests show "Test timed out after Xs"

**Causes:**
- Bots are slow or unresponsive
- LiteLLM proxy overloaded
- Network issues

**Fix:**
1. Check bot health: `!status`
2. Check LiteLLM: `curl http://localhost:4000/health`
3. Increase timeout in test case definitions

### Auto-Fix Fails

**Symptom:** Auto-fix runs but test still fails on re-run

**Causes:**
- Underlying issue not transient
- Service restart didn't help
- Configuration problem

**Fix:**
1. Check service logs for errors
2. Manual investigation required
3. Update auto-fix logic if pattern emerges

## Future Enhancements

### Planned Features

1. **Performance Benchmarking** — Measure response times and establish baselines
2. **Load Testing** — Send multiple concurrent requests to test bot capacity
3. **Integration Testing** — Test end-to-end workflows (e.g., code deploy via Architect)
4. **Regression Testing** — Track test results over time to detect degradation
5. **Scheduled Testing** — Run tests automatically on a schedule (e.g., hourly)
6. **Detailed Reporting** — Export test results to JSON/CSV for analysis
7. **Health Score** — Calculate overall fleet health score (0-100)
8. **Alert Integration** — Send notifications to Discord/Slack on test failures

### Test Case Ideas

- **MCP Tool Access** — Verify all 167 MCP tools are accessible
- **Model Switching** — Test LLM model routing and auto-switching
- **Memory Query Performance** — Benchmark memory search speed
- **Webhook Processing** — Test GitHub webhook handling
- **Scheduler Accuracy** — Verify scheduled tasks execute on time
- **Voice Channel** — Test Admiral's voice capabilities (STT/TTS)

## Related Documentation

- [Bot Fleet Overview](../.cursor/memories/discord-bot-fleet.md)
- [Bot Audit Report](../docs/BOT_AUDIT_2026-08-18.md)
- [FLEET Protocol](../scripts/fleet_protocol.py)
- [Multi-Agent Coordination](../scripts/multi_agent.py)

## Change History

**2026-08-18:** Initial test framework implementation
- Created `proctor_test_framework.py` with 5 test cases
- Integrated into Proctor bot command system
- Added `!test` command with subcommands
- Documented usage and architecture

---

**Author:** Jeff Geronimo (via AI assistance)  
**Last Updated:** 2026-08-18
