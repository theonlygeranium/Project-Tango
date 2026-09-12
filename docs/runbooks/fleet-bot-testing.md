# Runbook: Fleet Bot Testing

**Last updated:** 2026-08-19

## Overview

This runbook covers running automated conversation tests against the Schubert Discord bot fleet. Tests can be run from Cursor (via the `fleet-bot-testing` skill), from the Schubert CLI, or automatically via the systemd timer.

## Test Components

### 1. Fleet Health Monitor (Automated, every 2h)

**Service:** `fleet-health-monitor.service`
**Timer:** `fleet-health-monitor.timer`
**Script:** `/opt/Project-Tango/scripts/fleet_health_monitor.py`
**Database:** `tango.fleet_health_results` (PostgreSQL)

Runs every 2 hours. Sends a test message to the senior-staff-meeting channel as the Proctor, passively analyzes recent admin-to-bot interactions in dedicated channels, scores responses, stores results in PostgreSQL, and posts a summary embed to the Proctor analysis channel.

### 2. Cortex Conversation Test (Manual, deep dive)

**Script:** `/opt/Project-Tango/scripts/cortex_conversation_test.py`

Sends 12 natural language questions to Dr. Cortex, collects full responses (including embeds), measures response time, char count, word count, and saves results to JSON. Use for deep persona and response quality analysis.

### 3. Fleet Test Suite (Manual, static analysis)

**Script:** `/opt/Project-Tango/scripts/fleet_test_suite.py`

26 static-analysis tests covering service health, script syntax, LiteLLM proxy, MCP servers, FLEET protocol, multi-agent config, guardrails, tool definitions, voice agent loop, bot personas, logger names, memory store, channel onboarding, Discord UX utils, streaming, and known bug regressions.

### 4. Proctor Test Framework (Programmatic)

**Script:** `/opt/Project-Tango/scripts/proctor_test_framework.py`
**Scheduled runner:** `/opt/Project-Tango/scripts/run_scheduled_test.py`

Programmatic test framework that validates bot behavior without Discord interaction. Used by the scheduled test runner for headless validation.

## Running Tests

### From Cursor

Use the `fleet-bot-testing` skill — it provides ready-to-run commands for all test types.

### From Schubert CLI

```bash
# Quick Cortex conversation test
set -a && source /opt/Project-Tango/.env && set +a
cd /opt/Project-Tango
/opt/Project-Tango/backend/venv/bin/python scripts/cortex_conversation_test.py --verbose --timeout 90

# Static test suite
cd /opt/Project-Tango/scripts
/opt/Project-Tango/backend/venv/bin/python fleet_test_suite.py

# Manual health monitor run
set -a && source /opt/Project-Tango/.env && set +a
cd /opt/Project-Tango
/opt/Project-Tango/backend/venv/bin/python scripts/fleet_health_monitor.py --once --verbose
```

### Check Automated Monitor Results

```bash
# Latest run logs
sudo journalctl -u fleet-health-monitor.service --since "4 hours ago" --no-pager -o cat | tail -30

# Query stored results
sudo -u postgres psql -d tango -c "
  SELECT cycle_id, timestamp, channel, passed, persona_score, relevance_score
  FROM tango.fleet_health_results
  ORDER BY timestamp DESC LIMIT 20;
"

# Trend summary
sudo -u postgres psql -d tango -c "
  SELECT cycle_id,
    COUNT(*) as tests,
    COUNT(*) FILTER (WHERE passed) as passed,
    AVG(response_time) as avg_time,
    AVG(persona_score) as avg_persona,
    AVG(relevance_score) as avg_relevance
  FROM tango.fleet_health_results
  GROUP BY cycle_id
  ORDER BY MAX(timestamp) DESC LIMIT 10;
"
```

## After Code Changes

1. Verify syntax: `cd /opt/Project-Tango/scripts && /opt/Project-Tango/backend/venv/bin/python3 -c "import ast; ast.parse(open('BOTFILE').read()); print('OK')"`
2. Restart affected bots: `sudo systemctl restart BOTSERVICE`
3. Run a quick conversation test to verify
4. Check logs for errors: `sudo journalctl -u BOTSERVICE --since "2 minutes ago" --no-pager -o cat | tail -20`
5. Run the static test suite: `cd /opt/Project-Tango/scripts && /opt/Project-Tango/backend/venv/bin/python3 fleet_test_suite.py`

## Troubleshooting

### Bot not responding to Proctor

- Check `PROCTOR_BOT_ID` is set in the bot's environment
- Check the bot's `on_message` handler allows `PROCTOR_BOT_ID` (not just `ADMIN_USER_ID`)
- Check the FLEET delegation filter allows Proctor (not just Schubert)
- Check `_fleet_chain_id` variables are initialized for Proctor messages

### "Maximum iterations reached" on every response

- Check the agent loop body is inside the `for iteration in range(MAX_ITERATIONS)` loop (indentation)
- Check the `return "Maximum iterations reached"` is OUTSIDE the for loop (8-space indent, not 12)
- Check that tool calls are being processed and the loop continues to the next iteration

### Responses truncated at 2000 chars

- Check `StreamingMessage.MAX_LENGTH` in `fleet_protocol.py`
- Check that `finalize()` uses embeds for responses > 2000 chars
- Check that `append()` shows "streaming..." preview instead of finalizing early

### Rate limit warnings (HTTP 429)

- Check `StreamingMessage.EDIT_INTERVAL` is 2.0s or higher
- Reduce frequency of message edits during streaming

### Auto-thread created for every response

- Check `THREAD_RESPONSE_THRESHOLD` is 8000 (not 500)
- Check `THREAD_TOOL_CALL_THRESHOLD` is 8 (not 3)

### Noisy entity extraction

- Check `_is_valid_entity()` in `memory_store.py` is filtering stop words, newlines, short/generic entities
- Check both LLM-based and heuristic extraction paths use the filter
