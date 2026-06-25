#!/usr/bin/env bash
set -euo pipefail

echo "Project Tango Schubert preflight"
echo
status=0

echo "Target ports and related occupied ports:"
sudo ss -ltnp | grep -E ':(3006|8030|8010|3010|3100|8002|3000|3005|4000)\b' || true
if sudo ss -ltnp | grep -E '127\.0\.0\.1:8030\b'; then
  echo "blocked: 127.0.0.1:8030 must be available for tango-backend"
  status=2
else
  echo "ok: 127.0.0.1:8030 is available for tango-backend"
fi
if sudo ss -ltnp | grep -E '127\.0\.0\.1:8010\b' >/dev/null; then
  echo "ok: 127.0.0.1:8010 is occupied by existing asr-gateway and must not be reused"
fi
if sudo ss -ltnp | grep -E ':(3010|3100|8002|3000|3005|4000)\b' >/dev/null; then
  echo "ok: known non-Tango occupied ports are visible and must not be reused"
fi
echo

echo "Protected or related services:"
systemctl list-units --type=service --all | grep -Ei 'tango|foxtrot|meetscribe|polyglot-litellm|ollama|postgresql|caddy|cloudflared' || true
echo

if [[ -f /opt/project-tango/backend/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /opt/project-tango/backend/.env
  set +a
elif [[ -f /opt/Project-Tango/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /opt/Project-Tango/.env
  set +a
fi

echo "LiveKit credentials:"
python3 <<'PY' || status=2
import os
import sys

required = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
missing = [name for name in required if not os.environ.get(name)]
placeholder = [
    name
    for name in required
    if "your_" in os.environ.get(name, "").lower()
    or os.environ.get(name, "").strip().lower() in {"", "todo", "changeme"}
]

if missing or placeholder:
    if missing:
        print("missing: " + ", ".join(missing))
    if placeholder:
        print("placeholder: " + ", ".join(placeholder))
    sys.exit(2)

url = os.environ["LIVEKIT_URL"]
if not (url.startswith("wss://") or url.startswith("ws://")):
    print("invalid URL scheme: LIVEKIT_URL must start with ws:// or wss://")
    sys.exit(2)

print("ok: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")
PY
echo

echo "LiteLLM master key:"
if [[ -n "${LITELLM_MASTER_KEY:-}" ]]; then
  echo "ok: LITELLM_MASTER_KEY is set"
else
  echo "missing: LITELLM_MASTER_KEY"
  status=2
fi
echo

litellm_base="${LITELLM_BASE_URL:-http://127.0.0.1:4000/v1}"
litellm_base="${litellm_base%/}"
if [[ "$litellm_base" == */v1 ]]; then
  models_url="$litellm_base/models"
else
  models_url="$litellm_base/v1/models"
fi

echo "Required LiteLLM aliases:"
python3 - "$models_url" <<'PY' || status=2
import json
import os
import sys
import urllib.error
import urllib.request

models_url = sys.argv[1]
key = os.environ.get("LITELLM_MASTER_KEY") or ""
required = {"writer/palmyra-x5-voice", "local/qwen3-fast"}
request = urllib.request.Request(models_url, headers={"Authorization": f"Bearer {key}"})

try:
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode())
except urllib.error.HTTPError as exc:
    print(f"Unable to read models: HTTP {exc.code}")
    sys.exit(1)

available = {item.get("id") for item in payload.get("data", []) if item.get("id")}
missing = sorted(required - available)
if missing:
    print("missing: " + ", ".join(missing))
    sys.exit(2)

print("ok: " + ", ".join(sorted(required)))
PY

exit "$status"
