# Fleet Command API

FastAPI service for the Fleet Command SPA at `https://command.schubert.life`.

- Bind: `127.0.0.1:8097` (`fleet-api.service`)
- Public: `https://api-command.schubert.life`
- Config: `FLEET_CONFIG_PATH` (default `/opt/Project-Tango/config/fleet-config.json`)

`GET /api/fleet/config` and bot tool endpoints merge the Nexus catalog so the
pre-Nexus UI stays connected. See ADR-019.

Blank `llm.model` / `llm.coding_model` fields are presented as
`writer/palmyra-x6`. See ADR-020.
