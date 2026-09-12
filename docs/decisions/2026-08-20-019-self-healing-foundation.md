# ADR: Self-Healing Foundation (9 Modules)

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

The Discord bot fleet suffered repeated outages from unhandled failure
modes:

- **Proctor crash-loop**: The Proctor bot entered a crash-loop that
  cascaded into fleet-wide instability. systemd restarted the bot, which
  immediately crashed again, consuming CPU and filling logs.
- **Discord API failures**: Rate limits (429), gateway disconnects, and
  permission errors caused bots to hang or crash with no recovery
  mechanism.
- **LLM failures**: LiteLLM proxy timeouts, Ollama model loading failures,
  and malformed responses caused agent loops to hang indefinitely.
- **No automated recovery**: Every failure required manual intervention —
  reading logs, restarting services, and diagnosing root causes by hand.

## Decision

Implement a **Self-Healing Foundation** consisting of 9 modules under
`src/nexus/healing/`:

1. **Crash-loop detector** — Monitors systemd service restart frequency;
   masks services that exceed the crash threshold to prevent cascading
   failures.
2. **Circuit breakers** — CLOSED/OPEN/HALF_OPEN state machine for LLM,
   tools, and Discord API calls. Trips after configurable failure counts;
   half-open allows probe requests.
3. **Health monitor** — Periodic health checks for each bot and dependency
   (Redis, LiteLLM, Discord gateway).
4. **Recovery engine** — Retry/fallback/escalate ladder for failed
   operations. Retries with exponential backoff, falls back to alternative
   providers, and escalates to human notification if all recovery attempts
   fail.
5. **Checkpoint manager** — Redis-backed state checkpointing so bots can
   resume from their last known good state after a crash.
6. **Semantic breaker** — Detects repeated identical tool calls (e.g., a
   bot stuck calling the same MCP tool in a loop) and breaks the cycle.
7. **Health registry** — Fleet-wide aggregation of all bot health states;
   consumed by the orchestrator for routing decisions.
8. **Remediation actions** — Concrete recovery actions: restart service,
   clear session, reload config, switch LLM provider.
9. **Runtime supervisor** — Orchestrates the above modules, coordinating
   detection, recovery, and escalation across the fleet.

## Rationale

- **Defense-in-depth**: Each module addresses a specific failure mode
  observed in production. No single module covers all cases, but together
  they provide comprehensive coverage.
- **Automated recovery**: The recovery engine and remediation actions
  handle common failures without human intervention, reducing mean time
  to recovery from minutes/hours to seconds.
- **Crash-loop prevention**: The crash-loop detector and service masking
  prevent the cascading failures that previously took down the entire fleet.
- **State preservation**: The checkpoint manager ensures bots resume
  cleanly after crashes rather than losing in-flight task state.

## Alternatives Considered

1. **External monitoring (Nagios, Prometheus)** — Would detect failures
   but not automatically recover. Still requires manual intervention for
   remediation.
2. **Manual intervention only** — The pre-existing approach. Unsustainable
   for a fleet of 8 bots running 24/7; failures at 3 AM went unaddressed
   for hours.

## Consequences

- Increased code complexity: 9 modules with interdependencies require
  careful integration testing.
- Redis is required for checkpoint storage; if Redis is down, checkpoints
  are unavailable (bots fall back to clean-start behavior).
- The circuit breaker state machine introduces a small latency overhead
  on every LLM/tool/Discord call for state checks.
- The crash-loop detector may mask a service that is genuinely trying to
  recover; masked services require manual unmasking after the root cause
  is fixed.

## References

- NX-SPEC-03: Self-Healing Foundation
- Implementation: `src/nexus/healing/`
