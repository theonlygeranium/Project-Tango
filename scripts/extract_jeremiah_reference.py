#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import wave
from pathlib import Path
from urllib import error, request

APP_ROOT = Path(os.getenv("TANGO_APP_ROOT", "/opt/Project-Tango"))
OUTPUT_DIR = APP_ROOT / "tts-voices"
OUTPUT_PATH = OUTPUT_DIR / "jeremiah_reference.wav"
JEREMIAH_VOICE_ID = "EqHdTYoEuDQCxN1CVbi0"
SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2
REFERENCE_TEXT = (
    "Hi, I'm Jeremiah. I'm an agent whose voice is based on my creator, Jeff Geronimo. "
    "I'm here to help - ask me anything and I'll give you a straight answer. "
    "I don't hedge, I don't over-explain, and I respect your time. "
    "Whether it's a quick question or something you really want to dig into, I'm ready. "
    "What's on your mind? "
    "For this voice sample, I'll keep a steady pace and a natural rhythm. "
    "I can sound direct without sounding cold, friendly without wasting words, and calm without dragging the sentence out. "
    "If you ask me to solve a problem, I'll start with the practical answer, then give you just enough context to make a good decision. "
    "If the situation needs nuance, I'll say that plainly too. "
    "The point is simple: useful help, spoken clearly, with a voice that feels familiar and grounded."
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def elevenlabs_base_url() -> str:
    base_url = os.getenv("ELEVENLABS_BASE_URL", "https://api.us.elevenlabs.io/v1").rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def main() -> int:
    load_env_file(APP_ROOT / ".env")
    load_env_file(APP_ROOT / "backend" / ".env")

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY is required")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
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
    ).encode()
    req = request.Request(
        f"{elevenlabs_base_url()}/text-to-speech/{JEREMIAH_VOICE_ID}",
        data=payload,
        headers={
            "xi-api-key": api_key,
            "content-type": "application/json",
            "accept": "audio/wav",
        },
        method="POST",
    )

    print(f"Generating Jeremiah reference audio ({len(REFERENCE_TEXT)} chars)...")
    try:
        with request.urlopen(req, timeout=60) as response:
            pcm_data = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"ElevenLabs request failed: HTTP {exc.code} {detail}") from exc

    with wave.open(str(OUTPUT_PATH), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_data)

    duration_s = len(pcm_data) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    print(f"Saved: {OUTPUT_PATH}")
    print(f"Duration: {duration_s:.1f}s")
    if duration_s < 30:
        raise SystemExit("Reference audio is shorter than 30 seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
