# RB-02 — Service Recovery

**Runbook ID:** RB-02
**Last Updated:** 2026-06-28
**Applies To:** All agents and operators

---

## When to Use This Runbook

Use when `tango-backend` or `tango-web` have crashed or failed to start, but the codebase is intact (no rollback needed).

---

## Diagnosis

```bash
systemctl status tango-backend --no-pager
systemctl status tango-web --no-pager
sudo journalctl -u tango-backend -n 100 --no-pager
sudo journalctl -u tango-web -n 100 --no-pager
```

### Common Failure Signatures

| Log Pattern | Likely Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` | Missing Python dependency | Step A |
| `ENOENT .next/standalone/server.js` | Frontend not built | Step B |
| `Address already in use :8030` | Port conflict | Step C |
| `Address already in use :3006` | Port conflict | Step C |
| `Connection refused localhost:4000` | LiteLLM down | Step D |
| `LIVEKIT_API_KEY not set` | `.env` missing | Step E |

---

## Step A — Reinstall Python Dependencies

```bash
cd /opt/Project-Tango/backend
sudo -u z121532 venv/bin/pip install -r requirements.txt
sudo systemctl restart tango-backend
```

## Step B — Rebuild Frontend

```bash
cd /opt/Project-Tango/frontend
sudo -u z121532 npm run build
sudo -u z121532 cp -r .next/static .next/standalone/.next/static
sudo -u z121532 cp -r public .next/standalone/public
sudo systemctl restart tango-web
```

## Step C — Kill Port Conflict

```bash
sudo ss -tlnp | grep 8030
sudo ss -tlnp | grep 3006
sudo kill -9 <PID>
sudo systemctl restart tango-backend tango-web
```

> Ports 8010 and 3010 are permanently reserved by other services. Never use them for Tango.

## Step D — Restart LiteLLM

> LiteLLM is shared by all Schubert projects. Confirm with human owner before restarting.

```bash
sudo systemctl restart polyglot-litellm
systemctl is-active polyglot-litellm
curl -s http://localhost:4000/health
```

## Step E — Check Environment File

```bash
cat /opt/Project-Tango/backend/.env | grep -E "^(LIVEKIT_URL|LIVEKIT_API_KEY|DEEPGRAM_API_KEY|ELEVENLABS_API_KEY|LITELLM_MASTER_KEY)" | sed 's/=.*/=<SET>/'
```

---

## Final Verification

```bash
systemctl is-active tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
curl -sI https://project-tango.schubert.life | head -3
```
