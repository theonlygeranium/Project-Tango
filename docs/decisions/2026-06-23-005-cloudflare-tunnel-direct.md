# ADR-005: Route Cloudflare Tunnel Directly to localhost (Bypass Caddy)

**Date:** 2026-06-23
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Initial deployment routed Cloudflare Tunnel traffic through Caddy before reaching the Tango services. This produced two failure modes:

1. **Error 522** (Connection Timed Out) — Cloudflare could not reach the origin via Caddy
2. **Empty responses** — Caddy's CORS headers conflicted with Tango's own CORS headers, producing duplicate header responses that browsers rejected

## Decision

Update the `schubert-foxtrot` Cloudflare Tunnel ingress to route Tango hostnames **directly to localhost ports**, bypassing Caddy:

- `project-tango.schubert.life` → `http://localhost:3006`
- `tango-api.schubert.life` → `http://localhost:8030`

## Rationale

- Eliminates the Error 522 failure mode entirely
- Removes duplicate CORS header conflicts
- Reduces latency by one hop
- Caddy is still used by other projects and shared services — Tango simply doesn't route through it

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Keep Caddy in path with CORS fix | Fragile; requires keeping Caddy and Tango CORS configs in sync |
| Disable Caddy CORS entirely | Breaks other services on Schubert sharing Caddy |
| Different Cloudflare tunnel per project | More infrastructure to manage; unnecessary |

## Consequences

- Tango services manage their own CORS (in FastAPI middleware for API, Next.js headers for frontend)
- Caddy config requires no Tango-specific blocks — `project-tango.schubert.life` and `tango-api.schubert.life` are not listed in Caddy
- DNS records for both hostnames are CNAME → `cd4474e7-d944-424f-ae41-1ccc4fee1a7e.cfargotunnel.com`
