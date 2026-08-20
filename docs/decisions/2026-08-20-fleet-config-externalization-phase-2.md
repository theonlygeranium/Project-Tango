# ADR: Fleet Config Externalization Phase 2 (Remaining Scripts)

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Cloud Agent

## Context

Phase 1 (PR #4) introduced `scripts/fleet_config_loader.py` and wired
`schubert-bot.py`, `cortex-bot.py`, and `multi_agent_config.py`. The remaining
fleet bot scripts and shared modules were later added to the GitHub tree and
still hard-coded LLM, prompt, self-healing, guardrail, memory, voice, MCP, and
fleet-protocol tunables.

## Decision

Apply the same non-breaking `_cfg.get(..., <existing_default>)` pattern to:

| File | bot_id / section |
|------|------------------|
| `scripts/architect-bot.py` | `architect` |
| `scripts/dr-voss-bot.py` | `dr_voss` |
| `scripts/cartographer-bot.py` | `cartographer` |
| `scripts/quartermaster-bot.py` | `quartermaster` |
| `scripts/proctor-bot.py` | `proctor` |
| `scripts/schubert-bot-v2.py` | `admiral` |
| `scripts/dr-cortex-bot.py` | `cortex` |
| `scripts/fleet_protocol.py` | `fleet_protocol` |
| `scripts/context_builder.py` | `context_builder` |
| `scripts/scheduler.py` | `scheduler` |
| `scripts/conversation_coordinator.py` | `conversation` |

Do not modify `fleet_config_loader.py` or `/opt/Project-Tango/config/fleet-config.json`.

## Rationale

- Completes Fleet Command coverage for all bot scripts now in the repository
- Preserves production behavior when the config file is absent
- Avoids re-touching files already migrated in phase 1

## Alternatives Considered

1. **Wait for phase-1 merge only** — leaves newly synced scripts unconfigurable
2. **Require config file** — would crash bots if Fleet Command is down

## Consequences

- Operators can tune remaining bots via `fleet-config.json` then restart that bot
- Phase-1 files (`schubert-bot.py`, `cortex-bot.py`, `multi_agent_config.py`) remain owned by PR #4

## References

- `scripts/fleet_config_loader.py`
- ADR `docs/decisions/2026-08-20-fleet-config-externalization.md` (phase 1)
- `/opt/Project-Tango/config/fleet-config.json` (deployed separately)
