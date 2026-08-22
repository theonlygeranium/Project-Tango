# Fleet Command UI (Nexus roster)

LCARS operator console for the Discord fleet. Replaces the pre-Nexus
Cloudflare Pages app that hardcoded seven bot IDs (`dr_voss`, no Sentinel).

- Eighth card: **Sentinel**
- Dr. Voss id: **`voss`**
- No mock-data fallback — API errors stay visible
- Served by `fleet-api` at `https://api-command.schubert.life/`

```bash
npm install
npm run build
```

Same-origin requests to `/api` do not need a baked-in token. A Pages deploy
to `command.schubert.life` should set `VITE_API_BASE=https://api-command.schubert.life`
and `VITE_API_TOKEN`.
