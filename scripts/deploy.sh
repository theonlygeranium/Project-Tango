#!/bin/bash
set -euo pipefail

DEPLOY_LOG=/opt/Project-Tango/logs/deploy.log
APP_ROOT=/opt/Project-Tango
APP_USER=z121532
APP_GROUP=z121532
APP_HOME=/home/z121532

run_as_app_user() {
  sudo -u "$APP_USER" env HOME="$APP_HOME" "$@"
}

# Never build or restart services from a worktree containing changes that have
# not been reconciled into Git. This protects live-only configuration edits.
cd "$APP_ROOT"
DIRTY_WORKTREE="$(run_as_app_user git status --porcelain --untracked-files=normal)"
if [ -n "$DIRTY_WORKTREE" ]; then
  echo "ERROR: Refusing deployment from a dirty worktree." >&2
  printf '%s\n' "$DIRTY_WORKTREE" >&2
  exit 1
fi

mkdir -p /opt/Project-Tango/logs
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting deployment..." >> "$DEPLOY_LOG"

if [ -f /opt/Project-Tango/deploy/tango-tts.service ]; then
  cp /opt/Project-Tango/deploy/tango-tts.service /etc/systemd/system/tango-tts.service
fi
if [ -f /opt/Project-Tango/deploy/tango-backend.service ]; then
  cp /opt/Project-Tango/deploy/tango-backend.service /etc/systemd/system/tango-backend.service
fi
if [ -f /opt/Project-Tango/deploy/tango-web.service ]; then
  cp /opt/Project-Tango/deploy/tango-web.service /etc/systemd/system/tango-web.service
fi
systemctl daemon-reload

# Install/update Python backend dependencies using the project venv
VENV_PIP=/opt/Project-Tango/backend/venv/bin/pip
if [ -x "$VENV_PIP" ]; then
  "$VENV_PIP" install -q -r /opt/Project-Tango/backend/requirements.txt >> "$DEPLOY_LOG" 2>&1
else
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] WARNING: venv not found at $VENV_PIP, skipping pip install" >> "$DEPLOY_LOG"
fi

# Build Next.js frontend
cd /opt/Project-Tango/frontend
chown -R "$APP_USER:$APP_GROUP" /opt/Project-Tango/frontend/.next /opt/Project-Tango/frontend/node_modules 2>/dev/null || true
run_as_app_user npm ci --silent >> "$DEPLOY_LOG" 2>&1
run_as_app_user npm run build >> "$DEPLOY_LOG" 2>&1

# Copy static assets into standalone output (required for Next.js standalone mode)
# Without this, _next/static/* returns 404 and the app has no CSS or JS chunks.
run_as_app_user rm -rf /opt/Project-Tango/frontend/.next/standalone/.next/static
run_as_app_user mkdir -p /opt/Project-Tango/frontend/.next/standalone/.next
run_as_app_user cp -R /opt/Project-Tango/frontend/.next/static \
      /opt/Project-Tango/frontend/.next/standalone/.next/static >> "$DEPLOY_LOG" 2>&1
if [ -d /opt/Project-Tango/frontend/public ]; then
  run_as_app_user rm -rf /opt/Project-Tango/frontend/.next/standalone/public
  run_as_app_user cp -R /opt/Project-Tango/frontend/public \
        /opt/Project-Tango/frontend/.next/standalone/public >> "$DEPLOY_LOG" 2>&1
fi
chown -R "$APP_USER:$APP_GROUP" /opt/Project-Tango/frontend/.next
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Static assets copied to standalone dir." >> "$DEPLOY_LOG"

# Apply ledgered, checksum-verified migrations after a successful application
# build but before restarting services. The runner serializes deployments with
# a PostgreSQL advisory lock and applies each new migration transactionally.
if [ -f "$APP_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$APP_ROOT/.env"
  set +a
fi
MIGRATION_PYTHON="$APP_ROOT/backend/venv/bin/python"
MIGRATION_RUNNER="$APP_ROOT/backend/migrate.py"
if [ ! -x "$MIGRATION_PYTHON" ] || [ ! -f "$MIGRATION_RUNNER" ]; then
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: Backend migration runner is unavailable." >> "$DEPLOY_LOG"
  exit 1
fi
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Applying database migrations..." >> "$DEPLOY_LOG"
sudo -u postgres env \
  HOME=/var/lib/postgresql \
  DATABASE_URL="${TANGO_MIGRATION_DATABASE_URL:-postgresql://postgres@localhost/tango}" \
  PGDATABASE="${PGDATABASE:-tango}" \
  PGUSER=postgres \
  TANGO_DB_SOCKET_DIR="${TANGO_DB_SOCKET_DIR:-/var/run/postgresql}" \
  "$MIGRATION_PYTHON" "$MIGRATION_RUNNER" >> "$DEPLOY_LOG" 2>&1
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Database migrations completed successfully." >> "$DEPLOY_LOG"

# Restart systemd services
TTS_READY=0
if [ -x /opt/tts-lab/f5-venv/bin/uvicorn ] && [ -f /opt/Project-Tango/tts-voices/jeremiah_reference.wav ]; then
  systemctl enable tango-tts >> "$DEPLOY_LOG" 2>&1 || true
  systemctl restart tango-tts
  TTS_READY=1
else
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] WARNING: F5-TTS venv or Jeremiah reference missing; tango-tts not restarted" >> "$DEPLOY_LOG"
fi
systemctl restart tango-backend
systemctl restart tango-web

# Verify services came back up
sleep 3
if [ "$TTS_READY" -eq 1 ]; then
  systemctl is-active --quiet tango-tts || { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: tango-tts failed to start" >> "$DEPLOY_LOG"; exit 1; }
fi
systemctl is-active --quiet tango-backend || { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: tango-backend failed to start" >> "$DEPLOY_LOG"; exit 1; }
systemctl is-active --quiet tango-web     || { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: tango-web failed to start"     >> "$DEPLOY_LOG"; exit 1; }

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Deployment completed successfully." >> "$DEPLOY_LOG"
