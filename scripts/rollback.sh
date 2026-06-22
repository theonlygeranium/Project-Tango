#!/bin/bash
set -e

echo "Rolling back to previous state..."
docker compose up -d --force-recreate
echo "Rollback complete."
