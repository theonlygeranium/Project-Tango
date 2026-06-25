# Project Tango Deploy Notes

These files are append/install templates for the Project Tango v1.2 bootstrap goal.
Install them on Schubert under `/opt/Project-Tango`; the production environment
file lives at `/opt/Project-Tango/.env` and must be preserved rather than
recreated from local templates.

Before installing them on Schubert, run a fresh preflight:

```bash
bash deploy/schubert-preflight.sh
nl -ba /etc/caddy/Caddyfile | sed -n '175,215p'
```

To syntax-check the API-only Caddy snippet by itself:

```bash
caddy validate --adapter caddyfile --config deploy/Caddyfile.tango-api
```

v1.2 target map:

- `project-tango.schubert.life` already exists in the live Caddyfile and proxies
  to frontend port `3006`. Do not create another frontend Caddy block.
- `tango-api.schubert.life` proxies to backend port `8030` using
  `deploy/Caddyfile.tango-api`.
- Schubert currently has `admin off` in the global Caddy options, so
  `systemctl reload caddy` cannot apply new Caddyfile content through the admin
  API. Apply Caddyfile changes with a full Caddy restart after validation.
- `tango-api.schubert.life` has a proxied Cloudflare CNAME to
  `project-tango.schubert.life`. Authoritative and Cloudflare resolver checks
  return `104.21.34.22` and `172.67.167.183`; public `/healthz` checks passed
  through both edge IPs on 2026-06-22.
- Tango authenticates to LiteLLM with `LITELLM_MASTER_KEY`; do not add
  `WRITER_API_KEY` or `PALMYRA_API_KEY` to Tango env files.
- LiteLLM aliases are `local/qwen3-fast` for Therapy/Meditation/Pinoy Pride and
  `writer/palmyra-x5-voice` for General Info.

Live inspection on 2026-06-22 showed `127.0.0.1:8010` is permanently held by
Docker container `asr-gateway`; do not reuse it. Backend port `8030` is the
Project Tango target and should remain available before install.
