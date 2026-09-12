# Project Tango — Device and Environment Specifics

## Schubert Nexus Server Details

### Hardware Information
- **Hostname:** Schubert Nexus (schubert.life)
- **OS:** Ubuntu Linux
- **Architecture:** x86_64
- **GPU:** Present (used by Ollama for local model inference)

### File System Paths
- **Project root:** `/opt/Project-Tango/` (capital T - exact casing required)
- **Backend:** `/opt/Project-Tango/backend/`
- **Frontend:** `/opt/Project-Tango/frontend/`
- **Python venv:** `/opt/Project-Tango/backend/venv/`
- **Deploy scripts:** `/opt/Project-Tango/scripts/`
- **Systemd units:** `/etc/systemd/system/tango-*.service`

### User Accounts
- **Primary user:** `z121532` (owns `/opt/Project-Tango/`)
- **Service user:** Services run as `z121532`
- **Root access:** Available via `sudo` for system operations

### Git Configuration
- **Always run git as z121532:** `sudo -u z121532 git ...`
- **Never use:** `sudo git pull` as root (causes ownership issues)
- **Repository:** Local only (no remote currently configured)
- **Branch:** `main`

## Service Architecture

### Systemd Services

| Service Name | Port | User | Purpose | Auto-restart |
|--------------|------|------|---------|--------------|
| `tango-backend.service` | 8030 | z121532 | FastAPI + LiveKit worker | Yes |
| `tango-web.service` | 3006 | z121532 | Next.js frontend | Yes |
| `polyglot-litellm.service` | 4000 | z121532 | LLM proxy (shared) | Yes |
| `ollama.service` | 11434 | ollama | Local model server (shared) | Yes |
| `postgresql@18-main.service` | 5432 | postgres | PostgreSQL 18 | Yes |
| `caddy.service` | 80/443 | caddy | Reverse proxy | Yes |
| `cloudflared.service` | N/A | cloudflared | Cloudflare tunnel | Yes |

### Service Dependencies
```
tango-backend.service requires:
  - polyglot-litellm.service (LLM proxy)
  - postgresql@18-main.service (conversation history)
  - Network (for Deepgram, ElevenLabs API calls)

tango-web.service requires:
  - Network only (static build served)
  - Backend API for token/dispatch endpoints
```

### Service Control Commands
```bash
# Check status
systemctl status tango-backend tango-web

# Start/stop/restart
sudo systemctl start tango-backend
sudo systemctl stop tango-web
sudo systemctl restart tango-backend

# View logs
sudo journalctl -u tango-backend -n 100 --no-pager
sudo journalctl -u tango-web -f  # Follow mode

# Reload after .service file changes
sudo systemctl daemon-reload
sudo systemctl restart tango-backend
```

## Network Configuration

### Internal Services (Localhost)
- `http://localhost:4000` - LiteLLM proxy
- `http://localhost:11434` - Ollama (DO NOT call directly)
- `http://localhost:5432` - PostgreSQL
- `http://localhost:8030` - Tango backend (before Caddy)
- `http://localhost:3006` - Tango frontend (before Caddy)

### External URLs (via Caddy + Cloudflare)
- `https://tango.schubert.life` - Frontend (Caddy → :3006)
- `https://tango-api.schubert.life` - Backend API (Caddy → :8030)
- `https://watson.schubert.life` - OpenHands (separate project)
- `https://pumpkin.schubert.life` - Open WebUI (separate project)
- `https://foxtrot.schubert.life` - Project Foxtrot (separate project)

### Caddy Configuration
- **Config file:** `/etc/caddy/Caddyfile`
- **Reloads automatically** on config changes (no restart needed)
- **Handles:** TLS certificates, reverse proxying, HTTPS redirects

### Firewall
- **External access:** Via Cloudflare Tunnel (no direct port exposure)
- **Internal access:** Via Tailscale VPN
- **Local services:** Bound to localhost only (except Caddy)

## Database Configuration

### PostgreSQL 18
- **Schema:** `tango`
- **Connection:**
  - Host: `localhost`
  - Port: `5432`
  - Database: `tango`
  - User: `tango_user` (read/write access to `tango` schema)
  
### Tables
```sql
-- tango.sessions
session_id UUID PRIMARY KEY DEFAULT gen_random_uuid()
persona_name TEXT NOT NULL
created_at TIMESTAMP DEFAULT NOW()

-- tango.turns
turn_id BIGSERIAL PRIMARY KEY
session_id UUID REFERENCES tango.sessions(session_id)
user_transcript TEXT
agent_response TEXT
agent_transcript TEXT
created_at TIMESTAMP DEFAULT NOW()
```

### Connection Pattern
```python
# Always use environment variables
conn = psycopg2.connect(
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
    dbname=os.getenv("DB_NAME", "tango"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)
```

## Python Environment

### Virtual Environment
- **Location:** `/opt/Project-Tango/backend/venv/`
- **Python version:** 3.10+ (Ubuntu default)
- **Activation:** `source /opt/Project-Tango/backend/venv/bin/activate`

### Package Installation
```bash
# Always use venv pip (NOT system pip)
/opt/Project-Tango/backend/venv/bin/pip install -r requirements.txt

# Or with venv activated
source /opt/Project-Tango/backend/venv/bin/activate
pip install -r requirements.txt
```

### Service Environment
- Systemd services load environment from `/opt/Project-Tango/backend/.env`
- Set via `EnvironmentFile=` directive in `.service` files
- No need to activate venv in service (full path to Python binary used)

## Node.js Environment

### Version
- **Node.js:** v20+ (LTS)
- **npm:** v10+
- **Installed via:** nvm or system package manager

### Frontend Build
```bash
cd /opt/Project-Tango/frontend
npm install
npm run build  # Outputs to .next/
```

### Service Execution
- Next.js runs in production mode via `npm start`
- Serves static build from `.next/` directory
- No dev server in production (no hot reload)

## Shared Services (Multi-Project)

### LiteLLM Proxy (Port 4000)
- **Shared by:** Project Tango, Watson AI, Pumpkin AI, Project Foxtrot, MeetScribe
- **Restart impact:** Affects all projects
- **Config:** `/opt/polyglot-litellm/config.yaml`
- **Before restarting:** Check if other projects are actively using it

### Ollama (Port 11434)
- **Shared by:** All projects needing local models
- **Models loaded:** `qwen3.6:latest`, others...
- **GPU access:** Exclusive per request (concurrent requests queue)
- **Before restarting:** Check `ollama ps` for active models

### PostgreSQL 18
- **Schemas:**
  - `tango` - Project Tango
  - `watson` - Watson AI
  - `meetscribe` - MeetScribe
  - Others...
- **Never restart** during active conversations
- **Backup before schema changes**

## Reserved Ports (DO NOT USE)

| Port | Owner | Reason |
|------|-------|--------|
| 8010 | MeetScribe (asr-gateway Docker) | Permanently allocated |
| 3010 | Project Foxtrot | Permanently allocated |
| 80/443 | Caddy | System-level reverse proxy |
| 5432 | PostgreSQL | System-level database |
| 11434 | Ollama | Shared model server |

## Deployment Workflow

### Standard Deploy Process
```bash
# 1. Pull latest (as z121532)
cd /opt/Project-Tango
sudo -u z121532 git pull

# 2. Update backend dependencies (if needed)
/opt/Project-Tango/backend/venv/bin/pip install -r backend/requirements.txt

# 3. Rebuild frontend
cd frontend
npm install
npm run build

# 4. Restart services
sudo systemctl restart tango-backend tango-web

# 5. Verify
systemctl status tango-backend tango-web
curl -s https://tango-api.schubert.life/healthz
```

### Rollback Process
```bash
# 1. Check current tag
cd /opt/Project-Tango
git describe --tags

# 2. Revert to stable tag (e.g., v1.0-stable)
sudo -u z121532 git checkout v1.0-stable

# 3. Reinstall backend deps
/opt/Project-Tango/backend/venv/bin/pip install -r backend/requirements.txt

# 4. Rebuild frontend
cd frontend
npm install
npm run build

# 5. Restart services
sudo systemctl restart tango-backend tango-web
```

See `REVERT.md` for detailed rollback instructions.

## Environment Variables

### Backend .env File
Location: `/opt/Project-Tango/backend/.env`

**Required variables:**
```bash
# LiveKit
LIVEKIT_URL=wss://...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...

# LiteLLM
LITELLM_MASTER_KEY=...

# Deepgram
DEEPGRAM_API_KEY=...

# ElevenLabs
ELEVENLABS_API_KEY=...

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=tango
DB_USER=tango_user
DB_PASSWORD=...

# Logging
LOG_LEVEL=INFO
```

**DO NOT commit:** `.env` file with real secrets
**DO commit:** `.env.example` with placeholders

## Monitoring and Logs

### Log Locations
```bash
# Systemd service logs
sudo journalctl -u tango-backend -n 100
sudo journalctl -u tango-web -n 100

# Nginx/Caddy access logs (if needed)
sudo journalctl -u caddy -n 100

# Application logs (if file logging enabled)
/var/log/tango/backend.log  # If configured
```

### Health Check Endpoints
```bash
# Backend API health
curl https://tango-api.schubert.life/healthz
# Should return: {"status": "ok"}

# Frontend health (HTTP 200)
curl -I https://tango.schubert.life
```

### Service Status Check
```bash
# All Tango services
systemctl status tango-backend tango-web

# Dependency services
systemctl status polyglot-litellm ollama postgresql@18-main

# External connectivity
ping -c 1 api.deepgram.com
ping -c 1 api.elevenlabs.io
```

## CLI Command Length Limit

**Schubert Nexus connector has a 500-character command limit.**

### Workarounds:
1. **Use scripts:** Place complex commands in `/opt/Project-Tango/scripts/`
2. **Chain commands:** Use `&&` or `;` to combine (but keep under 500 chars)
3. **Multiple calls:** Split into several short commands

**Example:**
```bash
# Too long (>500 chars) - will fail
sudo journalctl -u tango-backend --since "1 hour ago" | grep ERROR | grep -v "transient" | awk '{print $1, $2, $3, $NF}' | sort | uniq -c | sort -rn

# Split into steps - works
# Step 1
sudo journalctl -u tango-backend --since "1 hour ago" > /tmp/logs.txt

# Step 2
grep ERROR /tmp/logs.txt | grep -v "transient" > /tmp/errors.txt

# Step 3
awk '{print $1, $2, $3, $NF}' /tmp/errors.txt | sort | uniq -c | sort -rn
```

## Backup and Recovery

### Git-based Recovery
- Current stable: `v1.0-stable` (commit `fdc9144`)
- All configs tracked in git
- Quick rollback: `git checkout <tag>`

### Database Backup
```bash
# Manual backup
sudo -u postgres pg_dump -n tango tango > /tmp/tango-backup-$(date +%Y%m%d).sql

# Restore
sudo -u postgres psql tango < /tmp/tango-backup-20260817.sql
```

### Configuration Backup
```bash
# All configs in /opt/Project-Tango/ are git-tracked
cd /opt/Project-Tango
sudo -u z121532 git status  # Check for uncommitted changes
sudo -u z121532 git log --oneline -10  # Recent commits
```

## Remote Access

### Cloudflare Tunnel
- Provides HTTPS access to `*.schubert.life`
- No incoming firewall rules needed
- Managed by `cloudflared.service`

### Tailscale VPN
- Private network access to Schubert
- IP: `100.x.x.x` (check with `tailscale ip`)
- Used for: Direct SSH, internal service access

### SSH Access
```bash
# Via Tailscale
ssh z121532@schubert.tail<xyz>.ts.net

# Public SSH (if configured)
ssh z121532@schubert.life
```

## Performance Considerations

### GPU Usage
- Ollama uses GPU for model inference
- Only one model loaded at a time (others swap to RAM)
- `nvidia-smi` to check GPU utilization

### Concurrent Conversations
- Each LiveKit room = one agent process
- Each agent uses ~1-2GB RAM
- Test scaling before allowing many concurrent users

### Database Connections
- PostgreSQL connection pool managed by psycopg2
- Close connections properly (`conn.close()` in finally blocks)
- Monitor with: `SELECT count(*) FROM pg_stat_activity WHERE datname='tango';`

## Known Device Quirks

### GPU Memory
- Ollama models can be large (4GB+ for `qwen3.6`)
- If GPU OOM: restart Ollama to clear memory

### SystemD Service Restarts
- Services have `Restart=always` in unit files
- Failed starts retry automatically every 10s
- Check logs if service keeps restarting

### File Permissions
- `/opt/Project-Tango/` owned by `z121532:z121532`
- Systemd services run as `z121532`
- Never `chown` to root (breaks service execution)

### Network Latency
- Deepgram STT: ~100-300ms latency (US East)
- ElevenLabs TTS: ~200-500ms latency (US routing)
- LiteLLM → Ollama: <50ms (local)
- Total round-trip: ~500-1000ms typical
