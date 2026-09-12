# ADR: Sentinel Autonomous Testing Agent

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

The Proctor bot was the fleet's testing agent, but it was limited to static
test execution with no adaptive testing or auto-repair:

- **Static test cases**: Proctor ran a fixed set of hardcoded test
  conversations. New bot behaviors were not covered until someone manually
  wrote a new test case.
- **No evaluation framework**: Proctor checked for response presence but
  not quality. It could not assess whether a bot's response was accurate,
  on-persona, or helpful.
- **No auto-repair**: When Proctor detected a failure, it delegated to the
  Architect with a raw error message. The Architect had to diagnose the
  root cause from scratch every time.
- **No adaptive difficulty**: Every test ran at the same difficulty level
  regardless of past results, so consistently passing bots were
  over-tested and consistently failing bots were under-diagnosed.
- **Crash-loop vulnerability**: Proctor itself was prone to crash-loops
  (see ADR-019), which took down the entire testing capability.

## Decision

Replace Proctor with **Sentinel** — an autonomous testing agent with:

1. **Test recipe registry** — 7 YAML files, each with 20+ test cases,
   covering persona consistency, tool usage, task delegation, error
   handling, multi-agent coordination, recovery behavior, and edge cases.
2. **6 structured rubrics with anchored scoring** — Each rubric defines
   quality criteria with 1-5 anchored scores (e.g., "1 = completely
   off-persona, 3 = partially on-persona, 5 = perfectly on-persona").
3. **Conversation runner via Nexus Bus** — Sentinel sends test messages
   through the Nexus Bus rather than Discord, avoiding rate limits and
   keeping test traffic out of user channels.
4. **Agent-as-a-Judge LLM evaluation** — An LLM evaluates bot responses
   against the rubrics, providing structured quality scores and
   qualitative feedback.
5. **Auto-generated test cases from git diffs** — When a bot's code
   changes, Sentinel automatically generates new test cases targeting
   the changed behavior.
6. **Repair engine with strategy ladder** — When a test fails, Sentinel
   attempts repair in order: prompt_fix → config_fix → code_fix →
   escalate. Each strategy is tried in sequence, with the results
   verified by re-running the failing test.
7. **Posterior tracking for adaptive difficulty** — Sentinel tracks
   pass/fail rates per bot per test category and adjusts test frequency
   and difficulty accordingly.
8. **Universal testing policy enforcement** — A pre-commit hook and CI
   gate ensure no code is merged without passing Sentinel tests.
9. **SentinelBot implementation** — Sentinel runs as a FleetBot subclass
   with its own systemd service, inheriting all self-healing capabilities.

## Rationale

- **Continuous quality assurance**: Sentinel runs tests continuously,
  not just on demand, catching regressions before they reach production.
- **Adaptive test generation**: Auto-generating test cases from git diffs
  ensures new behaviors are tested immediately without manual test
  authoring.
- **Automated repair reduces human burden**: The repair engine's strategy
  ladder handles common failures (prompt tweaks, config adjustments)
  without human intervention, escalating only when automated repair fails.
- **Agent-as-a-Judge provides quality assessment**: LLM-based evaluation
  goes beyond presence/absence checks to assess response quality, persona
  consistency, and helpfulness.
- **Posterior tracking optimizes testing resources**: Bots with high pass
  rates are tested less frequently, freeing resources for bots that need
  more attention.

## Alternatives Considered

1. **Keep Proctor with enhancements** — Incremental improvements to Proctor
   would not address the fundamental limitations: static test cases, no
   evaluation framework, no auto-repair.
2. **Use external CI only** — GitHub Actions CI handles unit tests but
   cannot test live bot conversations, persona consistency, or
   multi-agent coordination.
3. **Manual testing** — Does not scale for a fleet of 8 bots running 24/7.

## Consequences

- Additional LLM cost for the Agent-as-a-Judge evaluation and auto-generated
  test case generation. Costs are bounded by the posterior tracking system,
  which reduces test frequency for consistently passing bots.
- Test recipe YAML files require maintenance as bot behaviors evolve. The
  auto-generation from git diffs mitigates this but does not eliminate it.
- Sentinel is itself a bot and subject to the same failure modes as other
  fleet members. It inherits FleetBot self-healing capabilities, but if
  Sentinel is down, the `sentinel_tests_passed` health gate in the GitOps
  pipeline is skipped with a warning.

## References

- NX-SPEC-10: Autonomous Testing & Validation Agent (Sentinel)
- Implementation: `src/nexus/sentinel/`
