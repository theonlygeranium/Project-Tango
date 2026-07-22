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
- `8020` — Tango F5-TTS sidecar (localhost-only; free before first install or owned by `tango-tts`)
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
cp backend/.env.example .env
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

# F5-TTS Jeremiah pilot
TANGO_F5_TTS_ENABLED=true
TANGO_F5_TTS_BASE_URL=http://127.0.0.1:8020
TANGO_F5_TTS_SAMPLE_RATE=24000
TANGO_F5_TTS_TIMEOUT_SECONDS=60
# Optional deterministic synthesis seed. Values are bounded to Python's
# PYTHONHASHSEED range before F5-TTS is called.
# F5_TTS_SEED=12345

# Database
DATABASE_URL=postgresql://tango_user:<password>@localhost:5432/tango

# Account authentication (generate a unique value; never commit it)
TANGO_AUTH_LOOKUP_KEY=<at-least-32-random-bytes>
TANGO_PUBLIC_ORIGIN=https://project-tango.schubert.life
TANGO_AUTH_COOKIE_SECURE=true
TANGO_AUTH_SESSION_TTL_HOURS=168
TANGO_AUTH_IDLE_TTL_HOURS=12

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
sudo -u z121532 venv/bin/python -m py_compile main.py history.py memory.py auth.py accounts.py account_routes.py
echo "Python compile: OK"
```

---

## Step 4 — F5-TTS Sidecar Setup

This is required for the SPEC-004 Jeremiah pilot. It uses a separate venv so
cu128 PyTorch and F5-TTS do not alter the main backend venv.
The setup helper defaults to `F5_TORCH_VERSION=2.9.1` for Schubert's Python
3.14 runtime and installs the matching `+cu128` PyTorch wheels.

```bash
cd /opt/Project-Tango
sudo bash scripts/setup-f5-tts.sh
sudo -u z121532 python3 scripts/extract_jeremiah_reference.py
```

Verify the reference audio:

```bash
python3 -c "import wave; w=wave.open('/opt/Project-Tango/tts-voices/jeremiah_reference.wav'); print(f'{w.getnframes()/w.getframerate():.1f}s')"
# Expected: roughly 12.0s and at least 5.0s
```

If Jeremiah's ElevenLabs voice is not fine-tuned for text generation, the
extractor uses the existing ElevenLabs voice sample audio instead of the
blocked text-to-speech endpoint. It transcribes the exact saved clip with
Deepgram `nova-3` and writes `tts-voices/jeremiah_reference.txt` so F5-TTS does
not need to run its internal Whisper transcription path. The deployed F5-TTS
package clips reference audio over 12 seconds during preprocessing, so do not
force a 28-second runtime WAV unless the inference stack is changed to keep the
audio and custom transcript aligned. Longer raw recordings can still be used as
the source; the runtime reference should stay short and transcript-matched.

The sidecar loads the local reference WAV through `soundfile` because
`torchaudio` 2.9 routes file loading through `torchcodec`, which requires a CUDA
runtime library not present in Schubert's isolated F5-TTS venv.

---

## Step 5 — Database Initialization

```bash
sudo -u postgres psql
```

```sql
CREATE USER tango_user WITH PASSWORD '<password>';
CREATE SCHEMA tango AUTHORIZATION tango_user;
GRANT CONNECT ON DATABASE postgres TO tango_user;
\q
```

Apply the tracked migrations before starting the services:

```bash
cd /opt/Project-Tango
set -a
. ./.env
set +a
sudo -u postgres env DATABASE_URL=postgresql://postgres@localhost/tango \
  backend/venv/bin/python backend/migrate.py
```

The migration runner uses a PostgreSQL advisory lock and records each filename
and checksum in `tango.schema_migrations`. It refuses changed migrations that
were already applied. Run it as the PostgreSQL migration owner because Tango's
legacy tables do not all share the application service account as owner; the
migration grants the application role its required table and sequence access.

Create the initial administrator once. The generated password is printed once;
copy it directly into the owner's password manager and do not place it in a
shell script, environment file, or deployment log.

```bash
sudo -u z121532 env DATABASE_URL="$DATABASE_URL" \
  TANGO_AUTH_LOOKUP_KEY="$TANGO_AUTH_LOOKUP_KEY" \
  TANGO_PUBLIC_ORIGIN="$TANGO_PUBLIC_ORIGIN" \
  backend/venv/bin/python backend/bootstrap_admin.py \
  --first-name Tango --last-name Admin \
  --email founder@edstratumlabs.ai --adopt-legacy-data
```

---

## Step 6 — Frontend Build

```bash
cd /opt/Project-Tango/frontend
printf 'NEXT_PUBLIC_LIVEKIT_URL=wss://project-tango-0xs3szq3.livekit.cloud\nNEXT_PUBLIC_SITE_URL=https://project-tango.schubert.life\nTANGO_INTERNAL_API_BASE_URL=http://127.0.0.1:8030\n' > .env.local
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

## Step 7 — Install systemd Services

```bash
sudo cp deploy/tango-backend.service /etc/systemd/system/
sudo cp deploy/tango-tts.service /etc/systemd/system/
sudo cp deploy/tango-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tango-tts tango-backend tango-web
sudo systemctl start tango-tts tango-backend tango-web
```

---

## Step 8 — Verify Deployment

```bash
# Services active
systemctl is-active tango-tts tango-backend tango-web

# F5-TTS health
curl -s http://127.0.0.1:8020/healthz
# Expected: {"status":"ok", ...}

# Public backend health
curl -s https://tango-api.schubert.life/healthz
# Expected: ok

# Anonymous frontend access redirects to login
curl -sI https://project-tango.schubert.life | head -3
# Expected: redirect to /login

# Confirm LiteLLM routing
sudo journalctl -u tango-backend -n 30 --no-pager | grep "llm_base_url"
# Expected: llm_base_url=http://localhost:4000

# Confirm Jeremiah F5 routing after a Jeremiah session
sudo journalctl -u tango-backend -n 80 --no-pager | grep -i "Using F5-TTS"
sudo journalctl -u tango-tts -n 80 --no-pager | grep "Synthesized"
```

---

## Updating an Existing Deployment

**Via CI/CD (recommended):** Trigger the `Deploy to Schubert` workflow in GitHub Actions.

**Manual update on Schubert:**

```bash
cd /opt/Project-Tango
sudo -u z121532 git status --short  # must be empty
sudo -u z121532 git pull --ff-only origin main

# F5-TTS sidecar (if SPEC-004 files changed or first setup is incomplete)
sudo bash scripts/setup-f5-tts.sh
sudo -u z121532 python3 scripts/extract_jeremiah_reference.py

# Backend dependencies and migrations
cd backend && sudo -u z121532 venv/bin/pip install -r requirements.txt && cd ..
set -a; . ./.env; set +a
sudo -u postgres env DATABASE_URL=postgresql://postgres@localhost/tango \
  backend/venv/bin/python backend/migrate.py

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
cp .env.example ../.env  # Fill in dev values; set secure cookies false for HTTP
uvicorn main:app --host 127.0.0.1 --port 8030 --reload
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.example .env.local  # Set TANGO_INTERNAL_API_BASE_URL=http://127.0.0.1:8030
npm run dev -- --port 3006
```

Open `http://localhost:3006`.

---

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| Services not starting | `journalctl -u tango-backend -n 50` | See [RB-02](runbooks/RB-02-service-recovery.md) |
| Health check fails | `ss -tlnp \| grep 8030` | Port conflict — see [RB-02](runbooks/RB-02-service-recovery.md) |
| Blank frontend page | Check static assets in `.next/standalone` | Rebuild frontend (Step 6) |
| Agent not joining room | POST /api/dispatch returns error | Check backend logs |
| Jeremiah has no audio | `systemctl status tango-tts`; `curl http://127.0.0.1:8020/healthz` | Start `tango-tts` or set `TANGO_F5_TTS_ENABLED=false` and restart backend |
| Tagalog phonetic transcription | Check `stt_model` in logs | Must be `nova-3` with `language=tl` |
| Need to rollback | — | See [RB-01](runbooks/RB-01-rollback.md) or [REVERT.md](../REVERT.md) |
