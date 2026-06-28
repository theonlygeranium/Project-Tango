# RB-03 — Deploy a New Version

**Runbook ID:** RB-03
**Last Updated:** 2026-06-28
**Applies To:** All agents and operators

---

## Pre-Deploy Checklist

- [ ] `python3 -m py_compile backend/main.py backend/history.py`
- [ ] `cd frontend && npx tsc --noEmit`
- [ ] `cd frontend && npm run build`
- [ ] `bash deploy/schubert-preflight.sh`
- [ ] `CHANGELOG.md` updated
- [ ] `git diff --check` — no secrets committed
- [ ] If architecture changed: `docs/architecture.md` updated
- [ ] If new env vars: `backend/.env.example` updated

---

## Method 1 — GitHub Actions (Recommended)

```
1. Push changes to main on GitHub
2. Go to: https://github.com/theonlygeranium/Project-Tango/actions
3. Select "Deploy to Schubert" workflow
4. Click "Run workflow" → Run
5. Monitor for errors
```

---

## Method 2 — Manual Deploy on Schubert

```bash
cd /opt/Project-Tango
sudo -u z121532 git pull origin main

# Backend (if requirements.txt changed)
cd backend && sudo -u z121532 venv/bin/pip install -r requirements.txt && cd ..

# Frontend (if frontend/ changed)
cd frontend
sudo -u z121532 npm run build
sudo -u z121532 cp -r .next/static .next/standalone/.next/static
sudo -u z121532 cp -r public .next/standalone/public
cd ..

sudo systemctl restart tango-backend tango-web
systemctl is-active tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
```

---

## Tagging a New Stable Release

After verifying a deployment is stable and human-tested:

```bash
cd /opt/Project-Tango
sudo -u z121532 git tag -a v1.1-stable -m "v1.1-stable: description of what's confirmed working"
sudo -u z121532 git push origin v1.1-stable
```

Then update `REVERT.md` to reference the new stable tag.

---

## Rollback on Failure

If the deployment breaks anything, immediately run [RB-01 — Rollback to Stable Baseline](RB-01-rollback.md).
