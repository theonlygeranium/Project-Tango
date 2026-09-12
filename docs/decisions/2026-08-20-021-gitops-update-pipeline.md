# ADR: GitOps Update Propagation Pipeline

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

Bot configuration changes previously required manual service restarts with
no rollback safety:

- An operator would edit `fleet-config.json`, manually restart the affected
  bot services, and visually verify they came back online.
- If a config change broke a bot, the only recovery was to manually revert
  the config and restart again — with no guarantee the revert was clean.
- There was no staging or canary step; all bots were restarted simultaneously,
  so a bad config took down the entire fleet at once.
- There was no automated health verification after restart; a bot could
  appear "active" in systemd but be non-functional (e.g., LLM route broken,
  Discord token invalid).

## Decision

Implement a **GitOps update propagation pipeline** that manages bot
configuration changes through `fleet-manifest.yaml` with:

1. **Manifest diffing** — Compare the current manifest against the previous
   version to identify exactly which bots and config fields changed.
2. **Change severity classification** — Classify each change as low,
   medium, or high severity based on the affected fields (e.g., system
   prompt change = medium, LLM provider change = high).
3. **Canary-first deployment** — Deploy changes to the lowest-tier bot first
   (canary), then progressively to higher tiers, with Admiral deployed last.
4. **5 health gates** — After each bot restart, verify:
   - `systemd_active`: service is active in systemd
   - `liveness_endpoint`: bot responds to health check
   - `llm_test_request`: bot can make a test LLM call through LiteLLM
   - `no_new_errors`: no new error patterns in journalctl since restart
   - `sentinel_tests_passed`: Sentinel test suite passes for this bot
5. **Automatic rollback** — If any health gate fails, the pipeline
   automatically reverts the config change and restarts the bot with the
   previous configuration.
6. **Phased rollout** — Deployment order: canary → ascending tier → Admiral
   last. Each phase waits for all health gates to pass before proceeding.

## Rationale

- **Safe, automated, reversible**: Every deployment is automatically
  verified and rolled back if any health gate fails, eliminating the risk
  of a bad config taking down the fleet.
- **Canary-first catches issues early**: Deploying to the lowest-tier bot
  first means a broken config affects the least critical bot, not Admiral.
- **Health gates go beyond systemd**: The LLM test request and Sentinel test
  gates catch functional failures that systemd "active" status cannot detect.
- **GitOps single source of truth**: All config changes flow through
  `fleet-manifest.yaml` in git, providing audit trail and version history.

## Alternatives Considered

1. **Manual deployment** — The pre-existing approach. Error-prone, slow,
   no rollback safety, no health verification.
2. **Blue-green deployment** — Would require running two complete fleet
   instances simultaneously. Doubles resource usage on Schubert, which
   has limited GPU memory.
3. **Rolling deployment without canary** — Restarts bots one at a time but
   without the canary-first safety net. A bad config still takes down bots
   one by one before anyone notices.

## Consequences

- Deployments take longer due to health gate checks. Each bot restart
  includes a 30-second stabilization period plus health gate verification,
  so a full fleet deployment takes several minutes.
- Rollback storage is required: previous manifest versions must be retained
  for automatic revert. This is handled via git history.
- The pipeline depends on Sentinel being operational for the
  `sentinel_tests_passed` health gate. If Sentinel is down, this gate is
  skipped with a warning.

## References

- NX-SPEC-07: Update Propagation Pipeline (GitOps)
- Implementation: `src/nexus/deployment/`
