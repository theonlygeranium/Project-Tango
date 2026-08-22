# Runbook: Fleet Command UI + API

**UI (Nexus roster):** `https://api-command.schubert.life/` (served by `fleet-api`)
**UI (legacy Pages):** `https://command.schubert.life` (hardcoded 7 bots)
**API:** `https://api-command.schubert.life` → `127.0.0.1:8097` (`fleet-api.service`)
**Config:** `/opt/Project-Tango/config/fleet-config.json`

## What it does

The Nexus console is the `command-ui/` app served by `fleet-api`. It lists
eight cards (`voss` + `sentinel`) from `GET /api/fleet/config` and does not
fall back to mock data. The older Cloudflare Pages app still hardcodes
seven IDs and should be treated as legacy until it is republished from
`command-ui/dist`.

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

## LLM defaults

Every bot's primary and coding model default is `writer/palmyra-x6` (LiteLLM
on `:4000`). `GET /api/fleet/config` fills a blank `coding_model` so the
console does not show the old Claude Sonnet fallback.

Use `https://api-command.schubert.life/` — the legacy Pages app at
`command.schubert.life` still has a baked mock that lists Claude Sonnet when
the API is unreachable.

Do not restart Discord bots from a model-default change unless an operator
asked. Config is read at process start.

## Do not

- Commit `FLEET_API_TOKEN` or the Discord webhook from the n8n editor.
- Point the UI at Nexus systemd names that are inactive (`schubert-cortex`).
- `PUT /api/fleet/config` with a partial document — it replaces the whole file.
