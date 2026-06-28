# Project Tango — Deployment Guide

> This guide covers deploying Project Tango on Schubert from scratch.
> For rollback procedures, see [REVERT.md](../REVERT.md).
> For architecture details, see [architecture.md](architecture.md).

---

## Prerequisites

Verify these Schubert services are active before starting:

```bash
systemctl is-active polyglot-litellm ollama postgresql@18-main caddy cloudflared
# All should return: active
```

Verify port availability:

```bash
bash deploy/schubert-preflight.sh
```

Required ports:
- `3006` — Tango frontend (must be free)
- `8030` — Tango backend (must be free)
- `4000` — LiteLLM proxy (must be active)

---

## Step 1 — Clone the Repository

```bash
cd /opt
sudo -u z121532 git clone git@github.com:theonlygeranium/Project-Tango.git
cd Project-Tango
```

---

## Step 2 — Configure Environment

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set:

```bash
# LiveKit (cloud)
LIVEKIT_URL=wss://project-tango-0xs3szq3.livekit.cloud
LIVEKIT_API_KEY=<your key>
LIVEKIT_API_SECRET=<your secret>

# Deepgram
DEEPGRAM_API_KEY=<your key>

# ElevenLabs
ELEVENLABS_API_KEY=<your key>

# LiteLLM (already running on Schubert)
LITELLM_MASTER_KEY=<key from /opt/watson-ai/.credentials>
LITELLM_BASE_URL=http://localhost:4000

# Database
DATABASE_URL=postgresql://tango_user:<password>@localhost:5432/tango

# Do NOT add WRITER_API_KEY or PALMYRA_API_KEY here
```

---

## Step 3 — Backend Setup

```bash
cd /opt/Project-Tango/backend
sudo -u z121532 python3 -m venv venv
sudo -u z121532 venv/bin/pip install -r requirements.txt
```

Verify:

```bash
sudo -u z121532 python3 -m py_compile main.py history.py
echo "Python compile: OK"
```

---

## Step 4 — Database Initialization

```bash
sudo -u postgres psql
```

```sql
CREATE USER tango_user WITH PASSWORD '<password>';
CREATE SCHEMA tango AUTHORIZATION tango_user;
GRANT CONNECT ON DATABASE postgres TO tango_user;
\q
```

Tables are created automatically on first backend startup.

---

## Step 5 — Frontend Build

```bash
cd /opt/Project-Tango/frontend
sudo -u z121532 npm install
sudo -u z121532 npm run build
sudo -u z121532 cp -r .next/static .next/standalone/.next/static
sudo -u z121532 cp -r public .next/standalone/public
```

Verify:

```bash
ls .next/standalone/server.js && echo "Build: OK"
```

---

## Step 6 — Install systemd Services

```bash
sudo cp deploy/tango-backend.service /etc/systemd/system/
sudo cp deploy/tango-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tango-backend tango-web
sudo systemctl start tango-backend tango-web
```

---

## Step 7 — Verify Deployment

```bash
# Services active
systemctl is-active tango-backend tango-web

# Backend health
curl -s https://tango-api.schubert.life/healthz
# Expected: {"status":"ok"}

# Frontend loads
curl -sI https://project-tango.schubert.life | head -3
# Expected: HTTP/2 200

# Confirm LiteLLM routing
sudo journalctl -u tango-backend -n 30 --no-pager | grep "llm_base_url"
# Expected: llm_base_url=http://localhost:4000
```

---

## Updating an Existing Deployment

**Via CI/CD (recommended):** Trigger the `Deploy to Schubert` workflow in GitHub Actions.

**Manual update on Schubert:**

```bash
cd /opt/Project-Tango
sudo -u z121532 git pull origin main

# Backend (if requirements changed)
cd backend && sudo -u z121532 venv/bin/pip install -r requirements.txt && cd ..

# Frontend (if frontend changed)
cd frontend
sudo -u z121532 npm run build
sudo -u z121532 cp -r .next/static .next/standalone/.next/static
sudo -u z121532 cp -r public .next/standalone/public
cd ..

sudo systemctl restart tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
```

---

## Local Development Setup

**Backend:**

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in dev values
uvicorn main:app --host 127.0.0.1 --port 8030 --reload
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env.local  # Set NEXT_PUBLIC_BACKEND_URL=http://localhost:8030
npm run dev -- --port 3006
```

Open `http://localhost:3006`.

---

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Services not starting | `journalctl -u tango-backend -n 50` | See [RB-02](runbooks/RB-02-service-recovery.md) |
| Health check fails | `ss -tlnp \| grep 8030` | Port conflict — see [RB-02](runbooks/RB-02-service-recovery.md) |
| Blank frontend page | Check static assets in `.next/standalone` | Rebuild frontend (Step 5) |
| Agent not joining room | POST /api/dispatch returns error | Check backend logs |
| Tagalog phonetic transcription | Check `stt_model` in logs | Must be `nova-3` with `language=tl` |
| Need to rollback | — | See [RB-01](runbooks/RB-01-rollback.md) or [REVERT.md](../REVERT.md) |
