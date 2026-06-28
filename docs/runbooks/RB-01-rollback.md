# RB-01 — Rollback to Stable Baseline

**Runbook ID:** RB-01
**Last Updated:** 2026-06-28
**Applies To:** All agents and operators

---

## When to Use This Runbook

Use this runbook when:
- A deployment has caused a regression (broken UI, backend crash, audio pipeline failure)
- A new feature introduced an unrecoverable error
- You need to restore a known-good state quickly

The current stable baseline is **`v1.0-stable`** (commit `fdc9144`).

---

## Step 1 — Assess the Failure

```bash
systemctl is-active tango-backend tango-web
sudo journalctl -u tango-backend -n 50 --no-pager
sudo journalctl -u tango-web -n 50 --no-pager
curl -s https://tango-api.schubert.life/healthz
curl -sI https://project-tango.schubert.life | head -3
```

---

## Step 2 — Rollback on Schubert

```bash
cd /opt/Project-Tango
sudo -u z121532 git fetch --tags
sudo -u z121532 git checkout v1.0-stable

# Rebuild frontend
cd frontend
sudo -u z121532 npm run build
sudo -u z121532 cp -r .next/static .next/standalone/.next/static
sudo -u z121532 cp -r public .next/standalone/public
cd ..

# Reinstall backend dependencies
cd backend && sudo -u z121532 venv/bin/pip install -r requirements.txt && cd ..

# Restart
sudo systemctl restart tango-backend tango-web
```

---

## Step 3 — Verify Rollback Success

```bash
systemctl is-active tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
curl -sI https://project-tango.schubert.life | head -3
sudo -u z121532 git log --oneline -3
# Expected: fdc9144 at the top
```

---

## Step 4 — Document the Rollback

Add a CHANGELOG.md entry and commit:

```bash
# After updating CHANGELOG.md:
sudo -u z121532 git add CHANGELOG.md
sudo -u z121532 git commit -m "chore: rollback to v1.0-stable — <reason>"
sudo -u z121532 git push origin main
```

---

## Notes

- `backend/.env` is NOT tracked in git — credentials are unaffected by rollback.
- Force-push to reset `main` on GitHub requires explicit human authorization.
- See [`REVERT.md`](../../REVERT.md) for the full baseline reference.
