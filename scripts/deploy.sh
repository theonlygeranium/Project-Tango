#!/bin/bash
set -e

mkdir -p /opt/Project-Tango/logs
echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting deployment..." >> /opt/Project-Tango/logs/deploy.log

git pull origin main
docker compose pull
docker compose up -d --remove-orphans

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Deployment completed." >> /opt/Project-Tango/logs/deploy.log
