# ADR: Palmyra x6 is the Fleet Command default for all bots

**Date:** 2026-08-22
**Status:** Accepted
**Decided by:** Cursor Cloud Agent (owner request)

## Context

Fleet Command's LLM tab still showed Claude Sonnet in some places after the
fleet switched to Palmyra x6:

- Live `fleet-config.json` already had `writer/palmyra-x6` for seven file
  bots, but Cartographer and Quartermaster had a blank `coding_model`.
- The Sentinel GET stub set `coding_model` to `writer/claude-sonnet-4-5`.
- Discord bot scripts still fell back to Claude Sonnet when
  `coding_model` / `model` was missing.
- The legacy Pages app at `command.schubert.life` bakes a mock that lists
  Claude when the API is unreachable.

`fleet-manifest.yaml` already defaults every Nexus bot to
`writer/palmyra-x6`.

## Decision

1. `writer/palmyra-x6` is the default primary **and** coding model for every
   Fleet Command / Nexus bot.
2. `GET /api/fleet/config` fills a blank `model` or `coding_model` with that
   default. An operator-set override is not rewritten on GET.
3. Bot script fallbacks (`LLM_MODEL`, `CODING_MODEL`) use Palmyra x6.
   Claude remains in the `!model` picker.
4. Tango voice personas are unchanged (Chris still uses
   `writer/palmyra-x5-voice`).

## Rationale

The console should display the same default the live fleet already uses.
Leaving Claude as a hidden fallback reintroduces it on any blank field.

## Alternatives Considered

1. **Rewrite Claude on every GET** — would hide an intentional override.
2. **Leave script fallbacks on Claude** — Cartographer / Quartermaster would
   still code on Sonnet when `coding_model` is null.
3. **Republish Cloudflare Pages** — still blocked; source repo is not
   available. Operators should use `https://api-command.schubert.life/`.

## Consequences

- Sentinel's card shows Palmyra x6 for both LLM fields.
- Discord bots pick up the new script fallback only after a restart.
- Claude is still callable through LiteLLM if an operator types it in.

## References

- ADR-019 Fleet Command Nexus compatibility
- `fleet-api/nexus_catalog.py` (`DEFAULT_FLEET_MODEL`)
- `/opt/Project-Tango/config/fleet-config.json` (live, not in git)
