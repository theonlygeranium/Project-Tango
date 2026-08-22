# Runbook: Fleet Command UI + API

**UI:** `https://command.schubert.life` (Cloudflare Pages React SPA)
**API:** `https://api-command.schubert.life` → `127.0.0.1:8097` (`fleet-api.service`)
**Config:** `/opt/Project-Tango/config/fleet-config.json`

## What it does

The SPA is the pre-Nexus operator console. After the Nexus rebuild it still
talks to the same 19-ish endpoints. `fleet-api` merges Nexus tools into
`bots.*.tools` on every read so the Tools / Identity views stay current.

## Health

```bash
systemctl is-active fleet-api
curl -sS https://api-command.schubert.life/health
# authenticated:
curl -sS -H "Authorization: Bearer $FLEET_API_TOKEN" \
  https://api-command.schubert.life/api/fleet/status
curl -sS -H "Authorization: Bearer $FLEET_API_TOKEN" \
  https://api-command.schubert.life/api/nexus/status
```

`GET /api/nexus/status` lists Nexus vs config IDs (`voss` → `dr_voss`), live
systemd names, and whether `sentinel` is in config (it is not, yet).

## Tools tab looks stale

1. Confirm the yellow **MOCK DATA** badge is absent. If present, the SPA could
   not reach the API and is showing the baked-in fixture.
2. Confirm `GET /api/bots/admiral/tools` includes `fleet_delegate` and
   `health_check` with `"source": "nexus"`.
3. Restart only Fleet Command API if the merge is missing:

```bash
sudo systemctl restart fleet-api
```

Do not restart Discord bot units from this runbook unless an operator asked.

## Bot ID aliases

| UI / fleet-config | Nexus manifest |
|---|---|
| `dr_voss` | `voss` |
| `cortex` | `cortex` (unit still `cortex-bot.service`) |
| — | `sentinel` (not deployed) |

`GET /api/bots/voss` resolves to `dr_voss`.

## Do not

- Commit `FLEET_API_TOKEN` or the Discord webhook from the n8n editor.
- Point the UI at Nexus systemd names that are inactive (`schubert-cortex`).
- `PUT /api/fleet/config` with a partial document — it replaces the whole file.
