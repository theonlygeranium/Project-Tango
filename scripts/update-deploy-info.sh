#!/usr/bin/env bash
# update-deploy-info.sh — Update the deployment timestamp and note.
#
# Usage:
#   ./scripts/update-deploy-info.sh "Brief note about what was deployed."
#
# This script writes backend/deploy_info.json, which is served by the
# /api/deploy-info endpoint and displayed in the Tango UI as a deploy badge.
# Run this AFTER deploying code changes and restarting services.

set -euo pipefail

NOTE="${1:-Deployment updated.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INFO_FILE="$PROJECT_ROOT/backend/deploy_info.json"

# Get version from git tag if available, otherwise use 'dev'
VERSION="dev"
if command -v git &>/dev/null && [ -d "$PROJECT_ROOT/.git" ]; then
  VERSION=$(cd "$PROJECT_ROOT" && git describe --tags --always 2>/dev/null || echo "dev")
fi

# Write deploy info with current UTC timestamp
cat > "$INFO_FILE" << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "note": "$NOTE",
  "version": "$VERSION"
}
EOF

echo "Deploy info updated:"
cat "$INFO_FILE"
