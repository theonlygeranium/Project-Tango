# ADR: Nexus Bus to n8n Alert Bridge

**Date:** 2026-08-22
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

The n8n Alert Aggregation Hub (ADR-017) was deployed against the pre-Nexus Discord
bot fleet. Those bots were expected to POST a fixed JSON schema to
`http://100.86.47.6:5678/webhook/tango-alert` via `scripts/alert_dispatcher.py`.

The Nexus Fleet Model rebuild (NX-SPEC-00 through NX-SPEC-10) changed the
architecture:

- Live bots still run as `scripts/*-bot.py` systemd units, but health and
  escalation now also publish `health.alert` events on the Nexus Bus
  (Redis Streams).
- FleetBot `src/nexus/bot/base.py` only logs those events.
- `tango-healthcheck.py` still POSTs directly to `DISCORD_WEBHOOK_URL`.
- `alert_dispatcher.py` existed on Schubert but had no callers.

n8n itself is healthy (workflow `e4bjWJfSx6h5rfKd` active). The break is that
the new architecture stopped feeding it.

## Decision

Keep n8n as the outbound alert hub. Add a thin mapping layer so both caller
generations speak the same webhook schema:

1. `AlertDispatcher.send_nexus_health_alert()` maps Nexus
   `{bot_id, alert_type, severity, message, details}` onto the n8n payload,
   including severity aliases (`warning` → `WARN`, `error` → `CRITICAL`).
2. `scripts/nexus_n8n_bridge.py` is the import surface for FleetBot
   `_handle_health_alert`.
3. `tango-healthcheck.py` prefers n8n and falls back to the Discord webhook
   only if n8n dispatch cannot start.
4. `scheduler.py` mirrors channel embeds to n8n without removing the Discord
   channel message (different destination).
5. The checked-in n8n workflow accepts those severity aliases at validate time.

## Rationale

- n8n already owns Discord formatting, dedup, and future Slack routing.
- Rebuilding that in Nexus would re-scatter notification logic.
- A mapper is smaller and safer than rewriting the fleet onto n8n webhooks.

## Alternatives Considered

1. **Replace n8n with Nexus-only Discord posts** — Rejected; loses the visual
   hub and the Priority 2–7 workflows designed around it.
2. **Have n8n consume Redis Streams directly** — Deferred; n8n on Schubert
   does not currently subscribe to the Nexus stream, and the HTTP webhook is
   already active.
3. **Do nothing until src/bots fully replace scripts/** — Rejected; live
   alerts are already bypassing the hub.

## Consequences

- `N8N_ALERT_ENABLED=false` disables hub POSTs without a code change.
- Health Guardian alerts go through n8n first to avoid duplicate Discord
  webhook posts.
- Operators must call `forward_health_alert(event.payload)` from Nexus
  FleetBot `_handle_health_alert` on Schubert until that tree is in git.
- Workflow JSON in git must not contain the live Discord webhook URL.

## References

- ADR-017: n8n Alert Aggregation Hub
- Outline: n8n Alert Aggregation Hub, n8n Integration Opportunities
- NX-SPEC-02 (Nexus Bus), NX-SPEC-06 (Orchestrator / health.alert escalations)
