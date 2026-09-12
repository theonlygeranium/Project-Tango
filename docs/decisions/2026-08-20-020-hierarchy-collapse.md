# ADR: Hierarchy Collapse — Admiral as Sole Tier 0

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

The Discord bot fleet previously operated with two Tier 0 bots: Admiral
Schubert and the Architect. Both could issue commands to other bots,
delegate tasks, and initiate escalations. This dual-authority structure
caused:

- **Conflicting commands**: Admiral and Architect sometimes issued
  contradictory instructions to the same bot, causing it to oscillate
  between tasks or halt entirely.
- **Routing ambiguity**: The orchestrator could not determine which Tier 0
  bot should handle a given request, leading to both bots responding or
  neither responding.
- **Unclear escalation path**: When a task failed, it was unclear whether
  to escalate to Admiral or Architect, causing delays and dropped tasks.

## Decision

Collapse the bot hierarchy so **Admiral is the sole Tier 0 leader**. The
Architect is demoted to Tier 1, alongside the other bots. The new hierarchy:

- **Tier 0**: Admiral (sole fleet commander)
- **Tier 1**: Architect, Cartographer, Cortex, Quartermaster, Dr. Voss,
  Sentinel
- **Tier 2**: (reserved for future bots)

The orchestrator router uses a **deterministic routing table** instead of
keyword-based scoring. Each task type maps to a specific bot, eliminating
ambiguity. The routing table is defined in `fleet-manifest.yaml`.

## Rationale

- **Single point of authority**: Eliminates conflicting commands and
  routing ambiguity. Only Admiral can issue fleet-wide directives.
- **Deterministic routing**: The routing table maps task types to bots
  directly, removing the non-deterministic keyword-scoring approach that
  occasionally routed tasks to the wrong bot.
- **Clear escalation path**: The monotonic escalation ladder
  (retry → reroute → Voss → human) has a single starting point and no
  branching between Tier 0 bots.
- **Architect's role preserved**: The Architect remains a Tier 1 bot with
  full implementation capabilities. It receives delegated tasks from
  Admiral but can no longer issue commands to other Tier 1 bots.

## Alternatives Considered

1. **Keep dual Tier 0 with voting** — Both bots would vote on commands.
   Adds latency, complexity, and tie-breaking logic for a fleet of 8 bots
   where voting overhead exceeds the benefit.
2. **Rotate Tier 0 role** — Admiral and Architect would alternate as
   Tier 0 leader on a schedule. Introduces state synchronization problems
   and confusion about which bot is currently in charge.

## Consequences

- Admiral becomes a single point of failure. If Admiral crashes, no bot
  can issue fleet-wide commands until it recovers. This is mitigated by
  the crash-loop detector and runtime supervisor from the self-healing
  foundation (NX-SPEC-03), which automatically restarts Admiral and
  alerts if recovery fails.
- The Architect's system prompt and tool palette were updated to reflect
  Tier 1 status. It no longer has fleet-management tools.
- The deterministic routing table must be maintained in
  `fleet-manifest.yaml` as new task types are introduced.

## References

- NX-SPEC-06: Hierarchy Collapse & Orchestrator Router
- Implementation: `src/nexus/orchestrator/`
