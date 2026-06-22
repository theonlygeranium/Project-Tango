#!/bin/bash
set -e

DEPLOY_LOG=/opt/Project-Tango/logs/deploy.log
mkdir -p /opt/Project-Tango/logs
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting deployment..." >> "$DEPLOY_LOG"

# Install/update Python backend dependencies using the project venv
VENV_PIP=/opt/Project-Tango/backend/venv/bin/pip
if [ -x "$VENV_PIP" ]; then
  "$VENV_PIP" install -q -r /opt/Project-Tango/backend/requirements.txt >> "$DEPLOY_LOG" 2>&1
else
  echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] WARNING: venv not found at $VENV_PIP, skipping pip install" >> "$DEPLOY_LOG"
fi

# Build Next.js frontend
cd /opt/Project-Tango/frontend
npm ci --silent >> "$DEPLOY_LOG" 2>&1
npm run build >> "$DEPLOY_LOG" 2>&1

# Restart systemd services
systemctl restart tango-backend
systemctl restart tango-web

# Verify services came back up
sleep 3
systemctl is-active --quiet tango-backend || { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: tango-backend failed to start" >> "$DEPLOY_LOG"; exit 1; }
systemctl is-active --quiet tango-web     || { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: tango-web failed to start"     >> "$DEPLOY_LOG"; exit 1; }

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Deployment completed successfully." >> "$DEPLOY_LOG"
