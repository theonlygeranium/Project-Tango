---
name: fleet-bot-testing
description: >-
  Run automated conversation tests against the Schubert Discord bot fleet.
  Sends natural language questions to each bot (Cortex, Voss, Architect,
  Quartermaster, Cartographer, Admiral) as the Proctor, collects responses,
  and analyzes persona consistency, response quality, tool usage, and
  multi-agent coordination. Use when the user asks to test bots, run bot
  conversations, check bot health, validate bot responses, or tune the fleet.
---

# Fleet Bot Testing

Run conversation tests against the Schubert Discord bot fleet from Cursor,
Schubert CLI, or on a schedule via systemd.

## What Exists

| Component | Path | Purpose |
|-----------|------|---------|
| Fleet Health Monitor | `scripts/fleet_health_monitor.py` | Cadence-based testing (systemd timer, every 2h) |
| Cortex Conversation Test | `scripts/cortex_conversation_test.py` | 12-question deep conversation test |
| Fleet Test Suite | `scripts/fleet_test_suite.py` | 26 static-analysis tests (syntax, config, guardrails) |
| Proctor Test Framework | `scripts/proctor_test_framework.py` | Programmatic bot validation |
| Scheduled Test Runner | `scripts/run_scheduled_test.py` | Headless test runner for systemd |
| Health Monitor Timer | `deploy/fleet-health-monitor.timer` | systemd timer (every 2h) |
| Health Monitor Service | `deploy/fleet-health-monitor.service` | systemd oneshot service |

## Quick Start — Run a Conversation Test from Cursor

Run a 12-question conversation with Dr. Cortex:

```bash
set -a && source /opt/Project-Tango/.env && set +a
cd /opt/Project-Tango/scripts
/opt/Project-Tango/backend/venv/bin/python3 cortex_conversation_test.py --verbose --timeout 90
```

Run a quick 3-question smoke test against any bot:

```bash
set -a && source /opt/Project-Tango/.env && set +a
cd /opt/Project-Tango/scripts
/opt/Project-Tango/backend/venv/bin/python3 -c "
import asyncio, os, discord

BOT_TOKEN = os.environ['PROCTOR_BOT_TOKEN']
TARGET_BOT_ID = 1539172849569243217  # Cortex
CHANNEL_ID = int(os.environ['CORTEX_CHANNEL_ID'])

QUESTIONS = [
    'Dr. Cortex, what is your current research status?',
    'Dr. Cortex, can you explain the concept of emergence in AI systems?',
    'Dr. Cortex, what are your thoughts on multi-agent coordination?',
]

async def test():
    client = discord.Client(intents=discord.Intents.default())
    @client.event
    async def on_ready():
        ch = client.get_channel(CHANNEL_ID)
        for i, q in enumerate(QUESTIONS, 1):
            msg = await ch.send(q)
            print(f'Q{i}: {q}')
            await asyncio.sleep(60)
            async for resp in ch.history(limit=15, after=msg):
                if resp.author.bot and resp.author.id == TARGET_BOT_ID:
                    content = resp.content.strip()
                    if not content and resp.embeds:
                        content = resp.embeds[0].description or ''
                    if content and not content.startswith('Research') and not content.startswith('Researching'):
                        print(f'  A: {content[:200]}...')
                        break
        await client.close()
    await client.start(BOT_TOKEN)

asyncio.run(test())
"
```

## Bot Channel and ID Reference

| Bot | Channel Env Var | Bot ID |
|-----|-----------------|--------|
| Admiral Schubert | `FLEET_COMMAND_CHANNEL_ID` | 1538476585445892179 |
| The Architect | `ARCHITECT_CHANNEL_ID` | 1538766501035642890 |
| Dr. Cortex | `CORTEX_CHANNEL_ID` | 1539172849569243217 |
| Dr. Voss | `DR_VOSS_CHANNEL_ID` | 1539047086597873684 |
| Quartermaster | `QUARTERMASTER_CHANNEL_ID` | 1538817623045832746 |
| Cartographer | `CARTOGRAPHER_CHANNEL_ID` | 1538818587119067206 |
| Senior Staff | `SENIOR_STAFF_CHANNEL_ID` | — |
| Proctor (test sender) | `PROCTOR_BOT_TOKEN` | 1539047471899086988 |

## Running the Static Test Suite

```bash
cd /opt/Project-Tango/scripts
/opt/Project-Tango/backend/venv/bin/python3 fleet_test_suite.py
```

This runs 26 static-analysis tests covering: service health, script syntax,
LiteLLM proxy, MCP servers, FLEET protocol, multi-agent config, guardrails,
tool definitions, voice agent loop, bot personas, logger names, memory store,
channel onboarding, Discord UX utils, streaming, and known bug regressions.

## Checking the Automated Monitor

The fleet health monitor runs automatically every 2 hours via systemd:

```bash
# Check timer status
systemctl status fleet-health-monitor.timer

# Check latest run
sudo journalctl -u fleet-health-monitor.service --since "4 hours ago" --no-pager -o cat | tail -30

# Query stored results from PostgreSQL
sudo -u postgres psql -d tango -c "
  SELECT cycle_id, timestamp, channel, passed, persona_score, relevance_score
  FROM tango.fleet_health_results
  ORDER BY timestamp DESC LIMIT 20;
"

# Get trend summary
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

## Running a Manual Health Monitor Cycle

```bash
set -a && source /opt/Project-Tango/.env && set +a
cd /opt/Project-Tango
/opt/Project-Tango/backend/venv/bin/python scripts/fleet_health_monitor.py --once --verbose
```

## Analyzing Bot Logs After a Test

```bash
# Cortex (journald)
sudo journalctl -u cortex-bot.service --since "10 minutes ago" --no-pager -o cat | tail -50

# Dr. Voss (log file)
tail -50 /var/log/schubert-dr-voss.log

# Check for rate limiting
sudo journalctl -u cortex-bot.service --since "10 minutes ago" --no-pager -o cat | grep -c "rate limited"

# Check iteration counts
sudo journalctl -u cortex-bot.service --since "10 minutes ago" --no-pager -o cat | grep "iteration"

# Check tool calls
sudo journalctl -u cortex-bot.service --since "10 minutes ago" --no-pager -o cat | grep "Tool call"

# Check entity extraction noise
sudo journalctl -u cortex-bot.service --since "10 minutes ago" --no-pager -o cat | grep "Created entity"
```

## What to Look For in Test Results

| Metric | Good | Concern |
|--------|------|---------|
| Response received | 100% | < 100% = bot not responding |
| Response time | 3-15s | > 30s = LLM or tool latency |
| Response chars | 500-8000 | < 100 = truncated or error |
| Persona keywords | > 0.3 | < 0.15 = persona drift |
| Relevance score | > 0.3 | < 0.15 = off-topic |
| Tool calls made | 0-5 per question | 0 always = loop bug |
| Rate limit warnings | < 5 | > 20 = edit interval too fast |
| Auto-threads created | 0 for short Q&A | 1 per question = threshold too low |
| Entity noise | clean concepts | stop words/fragments = filter broken |
| "Maximum iterations" | never | appears = loop returning early |

## Restarting Bots After Code Changes

```bash
# All specialist bots
sudo systemctl restart cortex-bot.service schubert-architect.service \
  schubert-dr-voss.service schubert-proctor.service \
  schubert-quartermaster.service schubert-cartographer.service

# Admiral Schubert
sudo systemctl restart schubert-bot.service

# Verify all active
sleep 10 && systemctl is-active cortex-bot schubert-architect \
  schubert-dr-voss schubert-proctor schubert-quartermaster \
  schubert-cartographer schubert-bot
```

## Creating a Custom Conversation Test

To test a different bot, copy the pattern from `cortex_conversation_test.py`:

1. Change `CORTEX_CHANNEL_ID` to the target bot's channel ID
2. Change `CORTEX_BOT_ID` to the target bot's ID
3. Update `QUESTIONS` with bot-specific questions
4. Update `PERSONA_KEYWORDS` with the target bot's persona words
5. Run with `--verbose --timeout 90`

### Persona Keywords by Bot

| Bot | Keywords |
|-----|----------|
| Admiral Schubert | captain, fleet, ship, admiral, steady, schubert |
| The Architect | architect, infrastructure, docker, container, blueprint, build |
| Dr. Cortex | crystalline, amber, research, lattice, facet, captain, cortex |
| Dr. Voss | voss, analysis, data, research, doctor, medical |
| Quartermaster | quartermaster, supply, resource, captain, stores, provisions |
| Cartographer | cartographer, map, documentation, knowledge, territory, chart |

## Using /loop for Recurring Tests in Cursor

To run a quick bot health check on a recurring interval in Cursor:

```
/loop 30m Run a 3-question smoke test against Dr. Cortex and report any issues
```

The loop skill will arm a background timer that wakes the agent every 30 minutes
to run the test and report results.
