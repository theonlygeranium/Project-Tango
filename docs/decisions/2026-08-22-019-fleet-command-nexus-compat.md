# ADR: Fleet Command UI compatibility after Nexus rebuild

**Date:** 2026-08-22
**Status:** Accepted
**Decided by:** Cursor Cloud Agent

## Context

The Fleet Command web app at `https://command.schubert.life` was built before
the Nexus Fleet rebuild. It is a Cloudflare Pages React SPA whose source repo
(`theonlygeranium/fleet-command`) is not in this workspace. The SPA:

- Calls `https://api-command.schubert.life` (`fleet-api.service` on `127.0.0.1:8097`)
- Reads `GET /api/fleet/config` and renders `bots.<id>.tools`
- Uses pre-Nexus bot IDs (`dr_voss`, not `voss`)
- Falls back to baked-in mock data if the API is unreachable
- Has **zero** Nexus strings in the shipped bundle

Nexus (`src/bots/*/tools.py`, `fleet-manifest.yaml`) added tools such as
`fleet_delegate`, `health_check`, `wiki_publish`, `scan_ai_trends`,
`view_logs`, and a `sentinel` bot that is not in `fleet-config.json`.
`GET /api/bots/{id}/tools` previously returned only the frozen config list
and a note that live MCP discovery was unavailable.

## Decision

Keep the existing SPA contract for the legacy Pages app, and ship a Nexus
roster UI (`command-ui/`) served by `fleet-api`. Teach `fleet-api` to:

1. Merge the Nexus tool catalog into every bot `tools` array on read
   (`GET /api/fleet/config`, `GET /api/bots/{id}`, `GET /api/bots/{id}/tools`).
2. Present `voss` (and keep on-disk `dr_voss`) plus a Sentinel stub so the
   new UI can show eight cards.
3. Expose `GET /api/nexus/status` for roster / alias / sentinel visibility.
4. Leave live systemd unit names as recorded in `fleet-config.json`
   (for example `cortex-bot.service` remains the running unit;
   `schubert-cortex.service` is the Nexus name and is not active).

Do not write the merge into `fleet-config.json` on GET. Persist only when an
operator saves from the UI.

## Rationale

A Pages redeploy would require the missing `fleet-command` source. The UI
already renders whatever `tools` the API returns, so a backend merge reconnects
Nexus capabilities without changing the SPA.

## Alternatives Considered

1. **Rebuild the SPA** — blocked; `theonlygeranium/fleet-command` is not
   resolvable from this agent and is not on Schubert disk.
2. **Rewrite fleet-config.json in place** — risk of clobbering operator edits;
   GET-time merge is reversible.
3. **Switch UI IDs to Nexus (`voss`, `sentinel`)** — would break the shipped
   SPA, which hardcodes the original seven IDs.

## Consequences

- `command.schubert.life` shows Nexus tools after `fleet-api` restart.
- `sentinel` remains catalog-only until it is added to `fleet-config.json`
  and a systemd unit exists.
- A later SPA rebuild can drop the merge once it reads Nexus natively.
- LLM presentation defaults moved to ADR-020 (`writer/palmyra-x6`).

## References

- Outline: Fleet Command Testing Plan, Fleet Command Contextual Help Spec
- `fleet-api/nexus_catalog.py`
- `fleet-manifest.yaml` (Schubert)
- Port map: `command.schubert.life` (Pages), `api-command.schubert.life` → `:8097`
