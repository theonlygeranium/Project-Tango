# RB-03 — Deploy a New Version

**Runbook ID:** RB-03
**Last Updated:** 2026-07-22
**Applies To:** All agents and operators

---

## Pre-Deploy Checklist

- [ ] `python3.12 -m py_compile backend/main.py backend/history.py backend/memory.py backend/auth.py backend/accounts.py backend/account_routes.py`
- [ ] Backend auth/account tests pass
- [ ] `python3 -m py_compile tts_server/main.py scripts/extract_jeremiah_reference.py`
- [ ] `cd frontend && npx tsc --noEmit`
- [ ] `cd frontend && npm run build`
- [ ] `bash deploy/schubert-preflight.sh`
- [ ] If SPEC-004/F5-TTS changed: `bash -n scripts/setup-f5-tts.sh` and verify `tango-tts.service`
- [ ] `CHANGELOG.md` updated
- [ ] `git diff --check` — no secrets committed
- [ ] If architecture changed: `docs/architecture.md` updated
- [ ] If new env vars: `backend/.env.example` updated

---

## Method 1 — GitHub Actions (Recommended)

```
1. Confirm `/opt/Project-Tango` is clean; preserve and reconcile live-only work first.
2. Push changes to `main` on GitHub.
3. Monitor the `Deploy to Schubert` workflow.
4. The workflow uses the `[self-hosted, schubert]` runner and queues behind an
   in-progress Tango deploy rather than interrupting migration or restart.
5. Confirm the migration ledger, both Tango services, and live browser flow.
```

---

## Method 2 — Manual Deploy on Schubert

```bash
cd /opt/Project-Tango
sudo -u z121532 git status --short  # must be empty
sudo -u z121532 git pull --ff-only origin main

# Backend (if requirements.txt changed)
cd backend && sudo -u z121532 venv/bin/pip install -r requirements.txt && cd ..

# Apply tracked migrations before restarting services
set -a; . ./.env; set +a
sudo -u postgres env DATABASE_URL=postgresql://postgres@localhost/tango \
  backend/venv/bin/python backend/migrate.py

# F5-TTS sidecar (if first install or TTS files changed)
sudo bash scripts/setup-f5-tts.sh
sudo -u z121532 python3 scripts/extract_jeremiah_reference.py
sudo cp deploy/tango-tts.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tango-tts
sudo systemctl restart tango-tts

# Frontend (if frontend/ changed)
cd frontend
sudo -u z121532 npm run build
sudo -u z121532 cp -r .next/static .next/standalone/.next/static
sudo -u z121532 cp -r public .next/standalone/public
cd ..

sudo systemctl restart tango-backend tango-web
systemctl is-active tango-tts tango-backend tango-web
curl -s http://127.0.0.1:8020/healthz
curl -s https://tango-api.schubert.life/healthz
```

Migrations run as PostgreSQL's local migration owner because the legacy Tango
tables have mixed ownership. The application services continue running as
`z121532`; PostgreSQL itself is not restarted.

For the initial account rollout or administrator recovery, follow
[RB-04 — Account administration and credential recovery](RB-04-account-administration.md).

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
