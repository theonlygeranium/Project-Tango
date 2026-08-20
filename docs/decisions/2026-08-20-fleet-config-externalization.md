# ADR: Externalize Discord Bot Constants to fleet-config.json

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Cloud Agent

## Context

Discord fleet bot scripts (Admiral Schubert, Dr. Cortex, and related crew bots)
hardcoded LLM, prompt, guardrail, memory, voice, MCP, and multi-agent tuning
constants. Fleet Command manages a central JSON file at
`/opt/Project-Tango/config/fleet-config.json` for runtime configuration, but
bot scripts did not read it.

## Decision

Introduce `scripts/fleet_config_loader.py` that loads `fleet-config.json` (path
overridable via `FLEET_CONFIG_PATH`) and expose `get_config()`,
`get_bot_config(bot_id)`, and `get_fleet_config()`. Each bot script initializes
constants with `_cfg.get(... , <existing_hardcoded_default>)` so missing or
corrupt config never changes behavior or crashes a bot.

## Rationale

- Allows Fleet Command to tune bots without editing Python sources
- Non-breaking: defaults preserve current production behavior
- Single loader centralizes error handling and logging

## Alternatives Considered

1. **Environment variables only** — too many parameters; prompts are large
2. **Require config file** — would break bots if Fleet Command is down
3. **Hot reload on every message** — unnecessary complexity for this change

## Consequences

- Operators can change tunables via `fleet-config.json` then restart the bot
- Config file remains owned by Fleet Command API (not this repo)
- Fleet scripts present only on Schubert (not in this GitHub tree) still need
  the same wiring when synced

## References

- `scripts/fleet_config_loader.py`
- `/opt/Project-Tango/config/fleet-config.json` (deployed separately)
