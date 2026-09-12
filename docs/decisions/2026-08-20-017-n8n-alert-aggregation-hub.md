# ADR: n8n Alert Aggregation Hub

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

Project Tango's alert and notification system was scattered across multiple Python scripts with different implementations:

- `tango-healthcheck.py` — Discord webhook notifications with JSON cooldown files
- `scheduler.py` — In-memory cooldown dict with Discord bot API
- `slack_notifier.py` — MCP-based Slack notifications (currently disabled)
- `fleet_health_monitor.py` — Discord bot API for summary posting
- `architect-bot.py` / `dr-voss-bot.py` — Inline escalation notifications

Each system had its own severity levels, deduplication logic, and delivery mechanisms. Adding a new notification destination (e.g., email, PagerDuty) required code changes to every source.

## Decision

Implement an **n8n Alert Aggregation Hub** workflow that centralizes all alert routing through a single webhook endpoint. The workflow:

1. Receives alerts via POST to `http://100.86.47.6:5678/webhook/tango-alert`
2. Validates and enriches the payload with defaults
3. Deduplicates using n8n's persistent static data (30-minute cooldown)
4. Routes by severity (CRITICAL/WARN/INFO/DEBUG) to appropriate destinations
5. Currently sends to Discord webhook; Slack integration ready to enable when channels are created

A Python `alert_dispatcher.py` module provides a unified API for all bot scripts to send alerts to the hub.

## Rationale

- **Centralization**: One place to change routing rules, add destinations, or adjust formatting
- **Visual workflow**: n8n's visual editor makes the alert flow transparent and editable without code changes
- **Built-in dedup**: n8n's static data persists between executions, replacing scattered cooldown logic
- **Extensibility**: Adding Slack, email, or PagerDuty destinations is a drag-and-drop operation
- **No code changes for new destinations**: Bot scripts only need to POST to the webhook; n8n handles the rest

## Alternatives Considered

1. **Custom Python alert router service** — Would require a new systemd service, more code to maintain, and no visual editing
2. **Expand slack_notifier.py** — Still code-based, still scattered, doesn't solve the centralization problem
3. **Use Discord bot API only** — No multi-destination routing, no visual workflow editing

## Consequences

- n8n becomes a dependency for alert delivery (if n8n is down, alerts are lost)
- The `alert_dispatcher.py` module has a 10-second timeout and silently swallows errors, so bot scripts won't crash if n8n is unavailable
- The Discord webhook URL is embedded in the workflow JSON (not ideal, but n8n doesn't support env vars in expressions by default)
- Future enhancement: Enable `N8N_ALLOW_ENV_VARS_IN_EXPRESSION=true` in n8n config to use env vars instead of hardcoded URLs

## References

- n8n instance: `100.86.47.6:5678` (Tailscale-only)
- n8n MCP endpoint: `n8n-mcp.schubert.life`
- Workflow ID: `e4bjWJfSx6h5rfKd`
- Workflow JSON: `/opt/Project-Tango/scripts/n8n-alert-hub-workflow.json`
- Dispatcher module: `/opt/Project-Tango/scripts/alert_dispatcher.py`
- n8n API documentation: https://docs.n8n.io/connect/n8n-api/workflow/
