#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from urllib import error, request

APP_ROOT = Path(os.getenv("TANGO_APP_ROOT", "/opt/Project-Tango"))
OUTPUT_DIR = APP_ROOT / "tts-voices"
OUTPUT_PATH = OUTPUT_DIR / "jeremiah_reference.wav"
REFERENCE_TEXT_PATH = OUTPUT_DIR / "jeremiah_reference.txt"
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


def write_pcm_wav(pcm_data: bytes, reference_text: str) -> float:
    with wave.open(str(OUTPUT_PATH), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_data)
    REFERENCE_TEXT_PATH.write_text(reference_text)
    return len(pcm_data) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)


def convert_audio_to_reference(source_path: Path) -> float:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-t",
            "45",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            str(OUTPUT_PATH),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    REFERENCE_TEXT_PATH.write_text("")
    with wave.open(str(OUTPUT_PATH), "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def request_json(url: str, api_key: str) -> dict:
    req = request.Request(url, headers={"xi-api-key": api_key})
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def download_binary(url: str, api_key: str | None = None) -> bytes:
    headers = {"xi-api-key": api_key} if api_key else {}
    req = request.Request(url, headers=headers)
    with request.urlopen(req, timeout=90) as response:
        return response.read()


def fallback_to_existing_voice_sample(api_key: str) -> float:
    voice = request_json(f"{elevenlabs_base_url()}/voices/{JEREMIAH_VOICE_ID}", api_key)
    samples = voice.get("samples") or []
    source_bytes: bytes
    suffix = ".mp3"

    if samples:
        sample = max(samples, key=lambda item: int(item.get("size_bytes") or 0))
        sample_id = sample["sample_id"]
        print(f"Falling back to existing ElevenLabs sample {sample_id} ({sample.get('file_name')})...")
        try:
            source_bytes = download_binary(
                f"{elevenlabs_base_url()}/voices/{JEREMIAH_VOICE_ID}/samples/{sample_id}/audio",
                api_key,
            )
        except error.HTTPError as exc:
            if not voice.get("preview_url"):
                raise
            detail = exc.read().decode(errors="replace")
            print(f"Sample download failed: HTTP {exc.code} {detail}")
            print("Falling back to ElevenLabs preview_url...")
            source_bytes = download_binary(voice["preview_url"])
        suffix = Path(sample.get("file_name") or "sample.mp3").suffix or ".mp3"
    elif voice.get("preview_url"):
        print("Falling back to ElevenLabs preview_url...")
        source_bytes = download_binary(voice["preview_url"])
    else:
        raise SystemExit("No ElevenLabs voice sample or preview_url available for fallback")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as source_file:
        source_file.write(source_bytes)
        source_path = Path(source_file.name)
    try:
        return convert_audio_to_reference(source_path)
    finally:
        source_path.unlink(missing_ok=True)


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
        print(f"ElevenLabs TTS request failed: HTTP {exc.code} {detail}")
        duration_s = fallback_to_existing_voice_sample(api_key)
    else:
        duration_s = write_pcm_wav(pcm_data, REFERENCE_TEXT)

    print(f"Saved: {OUTPUT_PATH}")
    print(f"Transcript: {REFERENCE_TEXT_PATH}")
    print(f"Duration: {duration_s:.1f}s")
    if duration_s < 30:
        raise SystemExit("Reference audio is shorter than 30 seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
