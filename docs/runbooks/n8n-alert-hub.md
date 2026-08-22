# Runbook: n8n Alert Aggregation Hub

**Service:** n8n workflow `e4bjWJfSx6h5rfKd` (Tango Alert Aggregation Hub)
**Host:** Schubert Tailscale `100.86.47.6:5678`
**Webhook:** `POST http://100.86.47.6:5678/webhook/tango-alert`

## Purpose

Centralize WARN/CRITICAL/INFO alerts from Tango Health Guardian, Discord
scheduler sweeps, and Nexus Fleet `health.alert` events. n8n deduplicates
for 30 minutes and posts Discord embeds.

## Verify the hub

```bash
curl -sS -X POST http://100.86.47.6:5678/webhook/tango-alert \
  -H 'Content-Type: application/json' \
  -d '{
    "source": "runbook",
    "severity": "INFO",
    "alert_type": "health_check",
    "title": "Hub probe",
    "message": "n8n alert hub connectivity check"
  }'
```

Expect `{"status":"ok","message":"Alert processed"}` or
`{"status":"duplicate",...}` if the same title was sent within 30 minutes.

Python dispatcher:

```bash
cd /opt/Project-Tango/scripts
python3 alert_dispatcher.py
```

## Environment

Set in `/opt/Project-Tango/.env` (never commit real values):

| Variable | Default | Purpose |
|---|---|---|
| `N8N_ALERT_WEBHOOK_URL` | `http://100.86.47.6:5678/webhook/tango-alert` | Hub endpoint |
| `N8N_ALERT_ENABLED` | `true` | Set `false` to stop POSTs |
| `DISCORD_WEBHOOK_URL` | (Health Guardian fallback only) | Used if n8n import/dispatch cannot start |

## After a Nexus / bot restart

1. Confirm n8n containers are up: `docker ps | grep n8n`
2. Confirm Health Guardian still routes via `alert_dispatcher` (next timer run).
3. From a Nexus `health.alert`, FleetBot should call
   `nexus_n8n_bridge.forward_health_alert(event.payload)`.
4. If Discord goes quiet, check n8n executions for validate errors
   (unknown severity) and the placeholder Discord URL in the git workflow JSON
   versus the live workflow.

## Do not

- Commit the live Discord webhook URL from the n8n editor.
- Restart `caddy`, `cloudflared`, `postgresql`, `tailscaled`, or `ollama`
  while debugging this hub.
- POST secrets in the alert `message` or `metadata` fields.
