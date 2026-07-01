#!/usr/bin/env bash
set -euo pipefail

APP_ROOT=${APP_ROOT:-/opt/Project-Tango}
VENV_DIR=${F5_TTS_VENV_DIR:-/opt/tts-lab/f5-venv}
PYTHON_BIN=${PYTHON_BIN:-}

if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN=$(command -v "$candidate")
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "No python3 interpreter found" >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ffmpeg portaudio19-dev
fi

mkdir -p "$(dirname "$VENV_DIR")"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install \
  torch==2.8.0+cu128 \
  torchaudio==2.8.0+cu128 \
  --extra-index-url https://download.pytorch.org/whl/cu128
"$VENV_DIR/bin/pip" install -r "$APP_ROOT/tts_server/requirements.txt"

"$VENV_DIR/bin/python" - <<'PY'
import torch

print(torch.cuda.is_available(), torch.version.cuda, torch.cuda.get_device_name(0))
if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available to PyTorch")
PY

echo "F5-TTS environment ready at $VENV_DIR"
