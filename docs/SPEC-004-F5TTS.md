# SPEC-004: F5-TTS Self-Hosted Voice Engine (Jeremiah Pilot)

**Project:** Project Tango  
**Author:** Geronimo AI  
**Date:** June 30, 2026  
**Status:** Ready for Codex  
**Target Persona:** Jeremiah (`EqHdTYoEuDQCxN1CVbi0`)  
**Server:** Schubert — NVIDIA RTX PRO 4500 Blackwell, 32GB VRAM, CUDA 12.0, Python 3.14, Ubuntu  

---

## Overview

This spec installs F5-TTS on Schubert as a self-hosted text-to-speech engine, wires it into Project Tango's backend as an optional per-persona TTS backend, and validates it against Jeremiah using a reference audio sample extracted from his current ElevenLabs voice. All other personas remain on ElevenLabs. This is a non-destructive pilot — ElevenLabs is the unchanged fallback.

The goal is to validate that F5-TTS produces acceptable real-time speech quality for a live LiveKit voice agent session running on Schubert hardware, paving the way for full persona voice ownership.

---

## Architecture

```
Current:  LLM response text → ElevenLabs API (cloud) → PCM audio → LiveKit room
New:      LLM response text → F5-TTS API (localhost:8020) → PCM audio → LiveKit room
                            ↑
                     Jeremiah only (pilot)
```

The F5-TTS service runs as a FastAPI server on Schubert at `http://localhost:8020`. It is NOT exposed publicly — accessed only by `tango-backend` over localhost. A new `tts_backend` field on the `Persona` dataclass switches routing. Jeremiah is set to `f5-tts`; all others remain `elevenlabs`.

---

## Phase 1 — Reference Audio Extraction

### 1.1 Generate Jeremiah Reference Audio via ElevenLabs API

Use Jeremiah's ElevenLabs Voice ID `EqHdTYoEuDQCxN1CVbi0` to generate a clean 45-second reference audio sample. This sample is used by F5-TTS as the voice fingerprint for zero-shot cloning.

Write a Python script at `/opt/Project-Tango/scripts/extract_jeremiah_reference.py`:

```python
#!/usr/bin/env python3
"""
Extract a reference audio sample for Jeremiah from ElevenLabs for F5-TTS cloning.
Usage: python extract_jeremiah_reference.py
Output: /opt/Project-Tango/tts-voices/jeremiah_reference.wav
"""
import os
import requests

ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
JEREMIAH_VOICE_ID = "EqHdTYoEuDQCxN1CVbi0"
OUTPUT_PATH = "/opt/Project-Tango/tts-voices/jeremiah_reference.wav"
OUTPUT_DIR = "/opt/Project-Tango/tts-voices"

# 45-second natural monologue — varied pacing, natural sentences
REFERENCE_TEXT = (
    "Hi, I'm Jeremiah. I'm an agent whose voice is based on my creator, Jeff Geronimo. "
    "I'm here to help — ask me anything and I'll give you a straight answer. "
    "I don't hedge, I don't over-explain, and I respect your time. "
    "Whether it's a quick question or something you really want to dig into, I'm ready. "
    "What's on your mind?"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)

url = f"https://api.elevenlabs.io/v1/text-to-speech/{JEREMIAH_VOICE_ID}"
headers = {
    "xi-api-key": ELEVENLABS_API_KEY,
    "Content-Type": "application/json",
    "Accept": "audio/wav",
}
payload = {
    "text": REFERENCE_TEXT,
    "model_id": "eleven_flash_v2_5",
    "voice_settings": {
        "stability": 0.60,
        "similarity_boost": 0.80,
        "style": 0.15,
        "use_speaker_boost": False,
    },
    "output_format": "pcm_24000",
}

print(f"Generating Jeremiah reference audio ({len(REFERENCE_TEXT)} chars)...")
resp = requests.post(url, json=payload, headers=headers, timeout=30)
resp.raise_for_status()

# ElevenLabs returns raw PCM — wrap in WAV
import wave, struct
pcm_data = resp.content
sample_rate = 24000
channels = 1
sample_width = 2  # 16-bit

with wave.open(OUTPUT_PATH, "wb") as wf:
    wf.setnchannels(channels)
    wf.setsampwidth(sample_width)
    wf.setframerate(sample_rate)
    wf.writeframes(pcm_data)

print(f"Saved: {OUTPUT_PATH}")
duration_s = len(pcm_data) / (sample_rate * channels * sample_width)
print(f"Duration: {duration_s:.1f}s")
```

Run it:
```bash
cd /opt/Project-Tango
source .env  # loads ELEVENLABS_API_KEY
python scripts/extract_jeremiah_reference.py
```

Verify output exists and is >30s:
```bash
ls -lh /opt/Project-Tango/tts-voices/jeremiah_reference.wav
python3 -c "import wave; w=wave.open('/opt/Project-Tango/tts-voices/jeremiah_reference.wav'); print(f'{w.getnframes()/w.getframerate():.1f}s')"
```

**Expected:** File exists, duration ≥ 30 seconds.

---

## Phase 2 — F5-TTS Installation

### ⚠️ Critical: Blackwell GPU Requires cu128 PyTorch

Schubert has an NVIDIA RTX PRO 4500 Blackwell (compute capability 12.0 = `sm_120`). Standard PyTorch builds only support up to `sm_90`. You MUST use the `cu128` build or CUDA inference will silently fail.

### 2.1 Create Isolated venv

```bash
python3 -m venv /opt/tts-lab/f5-venv
source /opt/tts-lab/f5-venv/bin/activate
pip install --upgrade pip
```

### 2.2 Install PyTorch with CUDA 12.8 (Blackwell-compatible)

```bash
pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 \
  --extra-index-url https://download.pytorch.org/whl/cu128
```

Verify CUDA is visible:
```bash
python3 -c "import torch; print(torch.cuda.is_available(), torch.version.cuda, torch.cuda.get_device_name(0))"
```

**Expected output:** `True 12.8 NVIDIA RTX PRO 4500 Blackwell`

### 2.3 Install System Dependencies

```bash
sudo apt update -y
sudo apt install ffmpeg portaudio19-dev -y
```

### 2.4 Install F5-TTS

```bash
source /opt/tts-lab/f5-venv/bin/activate
pip install f5-tts
```

F5-TTS will auto-download model weights (~2GB) from HuggingFace on first inference run. To pre-download now:
```bash
python3 -c "from f5_tts import F5TTS; tts = F5TTS(device='cuda'); print('Model loaded OK')"
```

### 2.5 Smoke Test

Run a quick inference to confirm everything works end-to-end:
```bash
source /opt/tts-lab/f5-venv/bin/activate
python3 - <<'PY'
from f5_tts import F5TTS

tts = F5TTS(device="cuda")
audio = tts.generate(
    text="Hello, I'm Jeremiah. How can I help you today?",
    ref_audio="/opt/Project-Tango/tts-voices/jeremiah_reference.wav",
    ref_text=(
        "Hi, I'm Jeremiah. I'm an agent whose voice is based on my creator, Jeff Geronimo. "
        "I'm here to help — ask me anything and I'll give you a straight answer."
    ),
    output_path="/tmp/jeremiah_smoke_test.wav"
)
print("Smoke test passed — output: /tmp/jeremiah_smoke_test.wav")
PY
```

Listen to `/tmp/jeremiah_smoke_test.wav` to confirm voice quality before proceeding.

---

## Phase 3 — F5-TTS FastAPI Server

### 3.1 Create TTS API Server

Write `/opt/Project-Tango/tts_server/main.py`:

```python
"""
Project Tango — F5-TTS Local TTS Server
Runs on port 8020 (localhost only).
Accepts POST /synthesize → returns WAV audio bytes.
"""
from __future__ import annotations

import io
import logging
import os
import wave
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

log = logging.getLogger("tts_server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Project Tango TTS Server", version="1.0.0")

# Voice registry: persona_id → reference audio path + text
VOICE_REGISTRY: dict[str, dict] = {
    "jeremiah": {
        "ref_audio": "/opt/Project-Tango/tts-voices/jeremiah_reference.wav",
        "ref_text": (
            "Hi, I'm Jeremiah. I'm an agent whose voice is based on my creator, Jeff Geronimo. "
            "I'm here to help — ask me anything and I'll give you a straight answer. "
            "I don't hedge, I don't over-explain, and I respect your time."
        ),
    },
}

# Load F5-TTS model once at startup (warm)
_tts = None

def get_tts():
    global _tts
    if _tts is None:
        from f5_tts import F5TTS
        log.info("Loading F5-TTS model on CUDA...")
        _tts = F5TTS(device="cuda")
        log.info("F5-TTS model ready.")
    return _tts


class SynthesizeRequest(BaseModel):
    persona_id: str
    text: str
    ref_audio_override: Optional[str] = None
    ref_text_override: Optional[str] = None


@app.on_event("startup")
async def startup():
    """Pre-warm the model."""
    get_tts()
    log.info("TTS Server ready on port 8020.")


@app.get("/healthz")
async def health():
    return {"status": "ok", "model": "f5-tts"}


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    voice = VOICE_REGISTRY.get(req.persona_id)
    if not voice and not req.ref_audio_override:
        raise HTTPException(
            status_code=404,
            detail=f"No voice registered for persona_id='{req.persona_id}'. "
                   f"Provide ref_audio_override to use a custom reference.",
        )

    ref_audio = req.ref_audio_override or voice["ref_audio"]
    ref_text = req.ref_text_override or voice["ref_text"]

    if not os.path.exists(ref_audio):
        raise HTTPException(status_code=500, detail=f"Reference audio not found: {ref_audio}")

    try:
        tts = get_tts()
        output_path = f"/tmp/tts_{req.persona_id}_{abs(hash(req.text))}.wav"
        tts.generate(
            text=req.text,
            ref_audio=ref_audio,
            ref_text=ref_text,
            output_path=output_path,
        )
        with open(output_path, "rb") as f:
            audio_bytes = f.read()
        os.unlink(output_path)

        log.info(f"Synthesized {len(req.text)} chars for persona={req.persona_id}")
        return Response(content=audio_bytes, media_type="audio/wav")

    except Exception as e:
        log.error(f"Synthesis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

Install FastAPI in the venv:
```bash
source /opt/tts-lab/f5-venv/bin/activate
pip install fastapi uvicorn
```

Create the directory:
```bash
mkdir -p /opt/Project-Tango/tts_server
```

Test the server manually before creating the systemd unit:
```bash
source /opt/tts-lab/f5-venv/bin/activate
cd /opt/Project-Tango
uvicorn tts_server.main:app --host 127.0.0.1 --port 8020 --workers 1
```

In another terminal verify:
```bash
curl http://localhost:8020/healthz
```
Expected: `{"status":"ok","model":"f5-tts"}`

### 3.2 Create systemd Service

Write `/etc/systemd/system/tango-tts.service`:

```ini
[Unit]
Description=Project Tango F5-TTS Server
After=network.target
Wants=tango-backend.service

[Service]
Type=simple
User=z121532
WorkingDirectory=/opt/Project-Tango
Environment=PATH=/opt/tts-lab/f5-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/tts-lab/f5-venv/bin/uvicorn tts_server.main:app --host 127.0.0.1 --port 8020 --workers 1
Restart=on-failure
RestartSec=5
TimeoutStartSec=120
StandardOutput=journal
StandardError=journal
SyslogIdentifier=tango-tts

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tango-tts.service
sudo systemctl start tango-tts.service
sudo systemctl status tango-tts.service
```

Wait ~30 seconds for model to warm up, then verify health:
```bash
curl http://localhost:8020/healthz
```

---

## Phase 4 — Backend Integration

### 4.1 Update `backend/personas.py`

Add `tts_backend` field to the `Persona` dataclass (add after existing fields):

```python
# In the Persona dataclass definition, add:
tts_backend: str = "elevenlabs"  # "elevenlabs" | "f5-tts"
```

Set Jeremiah's `tts_backend` to `f5-tts`:

```python
"jeremiah": Persona(
    id="jeremiah",
    # ... all existing fields unchanged ...
    tts_backend="f5-tts",   # ← ADD THIS LINE
),
```

All other personas implicitly default to `tts_backend="elevenlabs"` — no other changes needed.

### 4.2 Update `backend/main.py` — TTS Routing

Find the section where ElevenLabs TTS is initialized for a session (look for `ElevenLabsTTS`, `elevenlabs.TTS`, or the `tts=` argument in `AgentSession`). Add a helper function and conditional routing:

```python
# Add near the top of main.py with other imports:
import httpx
from livekit.agents import tts as lk_tts

# Add this helper class before the agent entry point:
class F5TTSAdapter(lk_tts.TTS):
    """
    Thin adapter wrapping the local F5-TTS server (localhost:8020)
    as a LiveKit-compatible TTS backend.
    """
    def __init__(self, persona_id: str, base_url: str = "http://localhost:8020"):
        super().__init__(capabilities=lk_tts.TTSCapabilities(streaming=False))
        self._persona_id = persona_id
        self._base_url = base_url

    async def synthesize(self, text: str) -> lk_tts.ChunkedStream:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/synthesize",
                json={"persona_id": self._persona_id, "text": text},
            )
            resp.raise_for_status()
            audio_bytes = resp.content
        return lk_tts.ChunkedStream(self, audio_bytes, text)
```

Find where the `tts=` argument is passed to `AgentSession` (or equivalent in the worker entrypoint). Replace with a factory function:

```python
def build_tts(persona: Persona) -> lk_tts.TTS:
    """Return the correct TTS backend for the given persona."""
    if getattr(persona, "tts_backend", "elevenlabs") == "f5-tts":
        logger.info(f"Using F5-TTS for persona={persona.id}")
        return F5TTSAdapter(persona_id=persona.id)
    # Default: ElevenLabs (unchanged)
    from livekit.plugins import elevenlabs
    return elevenlabs.TTS(
        voice_id=persona.voice_id,
        model="eleven_flash_v2_5",
        **persona.voice_settings,
    )
```

Then replace the hardcoded `tts=elevenlabs.TTS(...)` with `tts=build_tts(persona)` in the session setup.

### 4.3 Update `frontend/lib/personas.ts`

Add a `ttsBackend` field to the Jeremiah persona type annotation so the UI badge can optionally show "F5-TTS" for clarity during testing. Mark it as optional so no other personas need changes:

```typescript
// In the Persona interface / type definition, add:
ttsBackend?: "elevenlabs" | "f5-tts";

// In jeremiah's persona object, add:
ttsBackend: "f5-tts",
```

This is cosmetic — used only to show a UI badge during testing. Not required for functionality.

---

## Phase 5 — Validation

### 5.1 Python Compile Check
```bash
cd /opt/Project-Tango
python3 -m py_compile backend/personas.py backend/main.py
echo "Python compile OK"
```

### 5.2 TypeScript Check
```bash
cd /opt/Project-Tango/frontend
npm run build
```

### 5.3 Service Health Checks
```bash
# All services should be active
sudo systemctl is-active tango-tts.service tango-backend.service tango-web.service caddy

# TTS server health
curl http://localhost:8020/healthz

# Backend health
curl https://tango-api.schubert.life/healthz
```

### 5.4 End-to-End Synthesis Test

Test that Jeremiah synthesis works through the full API stack:
```bash
curl -X POST http://localhost:8020/synthesize \
  -H "Content-Type: application/json" \
  -d '{"persona_id": "jeremiah", "text": "Hello. I am Jeremiah, now running on a self-hosted voice engine."}' \
  --output /tmp/jeremiah_e2e_test.wav

# Verify file is a valid WAV and has audio content
python3 -c "
import wave
w = wave.open('/tmp/jeremiah_e2e_test.wav')
duration = w.getnframes() / w.getframerate()
print(f'WAV OK: {duration:.2f}s, {w.getnchannels()}ch, {w.getframerate()}Hz')
assert duration > 1.0, 'Audio too short — synthesis may have failed'
print('E2E test PASSED')
"
```

### 5.5 Live Session Test

In the Project Tango web UI at `https://project-tango.schubert.life`:
1. Select **Jeremiah** persona
2. Click **Start Conversation**
3. Verify no initialization errors
4. Speak a question — verify response audio plays (Jeremiah's voice, not silence)
5. Check `tango-tts` logs for synthesis events:
   ```bash
   sudo journalctl -u tango-tts.service -f
   ```
   Expected log line: `Synthesized N chars for persona=jeremiah`
6. Check `tango-backend` logs for F5-TTS routing confirmation:
   ```bash
   sudo journalctl -u tango-backend.service -n 20 --no-pager | grep -i f5
   ```
   Expected: `Using F5-TTS for persona=jeremiah`

### 5.6 Latency Assessment

During the live session, note subjective response time. F5-TTS on a 32GB VRAM Blackwell GPU target:
- First-token-to-audio: < 800ms
- Subsequent turns: < 500ms

If latency is noticeably worse than ElevenLabs, add a note to the session log. Do not revert — this is an expected tradeoff at this stage.

---

## Phase 6 — Git Commit

Once all validation passes:

```bash
cd /opt/Project-Tango
git add backend/personas.py backend/main.py frontend/lib/personas.ts \
        tts_server/main.py scripts/extract_jeremiah_reference.py
git commit -m "feat(SPEC-004): add F5-TTS self-hosted TTS engine — Jeremiah pilot

- Install F5-TTS in /opt/tts-lab/f5-venv (cu128 PyTorch for Blackwell GPU)
- Add tango-tts.service FastAPI server on localhost:8020
- Add F5TTSAdapter in backend/main.py for LiveKit-compatible TTS routing
- Add tts_backend field to Persona dataclass; Jeremiah set to f5-tts
- All other personas remain on ElevenLabs (non-destructive pilot)
- Reference audio extracted from ElevenLabs voice EqHdTYoEuDQCxN1CVbi0

Ref: SPEC-004"
git push origin main
```

---

## Schubert File Layout After Completion

```
/opt/Project-Tango/
├── backend/
│   ├── main.py              ← F5TTSAdapter + build_tts() added
│   └── personas.py          ← tts_backend field + jeremiah tts_backend="f5-tts"
├── frontend/
│   └── lib/personas.ts      ← ttsBackend?: "f5-tts" on Jeremiah
├── tts_server/
│   └── main.py              ← NEW: FastAPI TTS server
├── scripts/
│   └── extract_jeremiah_reference.py  ← NEW: reference audio extractor
└── tts-voices/
    └── jeremiah_reference.wav  ← NEW: 45s ElevenLabs reference sample

/opt/tts-lab/
└── f5-venv/                 ← NEW: isolated Python venv w/ F5-TTS + cu128 PyTorch

/etc/systemd/system/
└── tango-tts.service        ← NEW: systemd unit for TTS sidecar
```

---

## Rollback Plan

If F5-TTS produces poor quality or causes session errors:

1. Remove `tts_backend="f5-tts"` from Jeremiah in `personas.py` (delete the one line)
2. Restart `tango-backend.service`
3. Jeremiah immediately reverts to ElevenLabs
4. `tango-tts.service` can be left running or stopped — it has no effect once no persona routes to it

The F5-TTS installation (`/opt/tts-lab/`) and service (`tango-tts.service`) do not interfere with any existing services and can be safely left in place for future testing.

---

## Notes for Codex

- **Do not install Coqui XTTS v2** — this is F5-TTS only
- **Do not expose port 8020 publicly** — TTS server is localhost only
- **Do not modify Jeremiah, Chris, or any other persona's TTS backend** — Jeremiah is the only pilot
- **Preserve all existing ElevenLabs voice settings** in `personas.py` — only add the new `tts_backend` field
- **The `F5TTSAdapter` must be LiveKit Agents 1.x compatible** — check `livekit-agents` version before writing the adapter; the internal TTS API may differ slightly from the skeleton above. Adjust accordingly.
- **Run `sudo systemctl daemon-reload` before `systemctl enable`** after writing the service file
- **Model download on first load** takes ~2–5 minutes and requires internet access on Schubert — ensure `tango-tts.service` `TimeoutStartSec` is sufficient (120s is set above)

---

*SPEC-004 — Geronimo AI / Project Tango — June 30, 2026*