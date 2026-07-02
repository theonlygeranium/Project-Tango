#!/usr/bin/env python3
"""Build Jeremiah's F5-TTS reference clip from an uploaded source recording.

Jeremiah's ElevenLabs PVC may not be fine-tuned for text-to-speech synthesis,
so this script does not call the ElevenLabs TTS endpoint. It downloads the
largest existing voice sample, trims it to a short runtime reference that stays
inside the deployed F5-TTS preprocessing limit, and writes a Deepgram transcript
matched to that exact WAV.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from urllib import error, parse, request

APP_ROOT = Path(os.getenv("TANGO_APP_ROOT", "/opt/Project-Tango"))
OUTPUT_DIR = APP_ROOT / "tts-voices"
OUTPUT_PATH = OUTPUT_DIR / "jeremiah_reference.wav"
REFERENCE_TEXT_PATH = OUTPUT_DIR / "jeremiah_reference.txt"
JEREMIAH_VOICE_ID = "EqHdTYoEuDQCxN1CVbi0"

SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2

# The installed F5-TTS preprocessing clips references longer than 12 seconds.
# Keep the custom transcript aligned with the exact audio the model receives.
F5_RUNTIME_REFERENCE_LIMIT_SECONDS = 12.0
DEFAULT_REFERENCE_START_SECONDS = 10.0
DEFAULT_REFERENCE_DURATION_SECONDS = 12.0
DEFAULT_MIN_REFERENCE_DURATION_SECONDS = 5.0
MIN_TRANSCRIPT_CHARS = 25

DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        print(f"Invalid {name}={raw_value!r}; using {default:g}.")
        return default


def reference_duration_seconds() -> float:
    requested = env_float("JEREMIAH_REFERENCE_SECONDS", DEFAULT_REFERENCE_DURATION_SECONDS)
    if requested > F5_RUNTIME_REFERENCE_LIMIT_SECONDS:
        print(
            "Requested Jeremiah reference duration "
            f"{requested:g}s exceeds installed F5-TTS preprocessing limit; "
            f"using {F5_RUNTIME_REFERENCE_LIMIT_SECONDS:g}s instead."
        )
        return F5_RUNTIME_REFERENCE_LIMIT_SECONDS
    return requested


def elevenlabs_base_url() -> str:
    base_url = os.getenv("ELEVENLABS_BASE_URL", "https://api.us.elevenlabs.io/v1").rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def request_json(url: str, api_key: str) -> dict:
    req = request.Request(url, headers={"xi-api-key": api_key})
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def download_binary(url: str, api_key: str | None = None) -> bytes:
    headers = {"xi-api-key": api_key} if api_key else {}
    req = request.Request(url, headers=headers)
    with request.urlopen(req, timeout=120) as response:
        return response.read()


def sample_size(sample: dict) -> int:
    try:
        return int(sample.get("size_bytes") or 0)
    except (TypeError, ValueError):
        return 0


def select_voice_sample(samples: list[dict]) -> dict:
    sample_id_override = os.getenv("JEREMIAH_REFERENCE_SAMPLE_ID")
    if sample_id_override:
        for sample in samples:
            if sample.get("sample_id") == sample_id_override:
                return sample
        raise SystemExit(
            "JEREMIAH_REFERENCE_SAMPLE_ID was set, but that sample was not "
            "found on Jeremiah's ElevenLabs voice."
        )

    if not samples:
        raise SystemExit("Jeremiah's ElevenLabs voice has no source samples.")
    return max(samples, key=sample_size)


def download_existing_voice_sample(api_key: str) -> tuple[Path, str]:
    voice = request_json(f"{elevenlabs_base_url()}/voices/{JEREMIAH_VOICE_ID}", api_key)
    samples = voice.get("samples") or []

    if samples:
        sample = select_voice_sample(samples)
        sample_id = sample["sample_id"]
        file_name = sample.get("file_name") or "jeremiah-source.mp3"
        size_bytes = sample_size(sample)
        print(f"Downloading ElevenLabs source sample {sample_id} ({file_name}, {size_bytes} bytes)...")
        source_bytes = download_binary(
            f"{elevenlabs_base_url()}/voices/{JEREMIAH_VOICE_ID}/samples/{sample_id}/audio",
            api_key,
        )
        suffix = Path(file_name).suffix or ".mp3"
        label = file_name
    elif voice.get("preview_url"):
        print("No source samples returned; falling back to ElevenLabs preview_url.")
        source_bytes = download_binary(voice["preview_url"])
        suffix = ".mp3"
        label = "preview_url"
    else:
        raise SystemExit("No ElevenLabs source sample or preview_url is available for Jeremiah.")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as source_file:
        source_file.write(source_bytes)
        return Path(source_file.name), label


def measure_wav(path: Path) -> tuple[float, int, int, int]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        duration = wav_file.getnframes() / sample_rate
    return duration, channels, sample_width, sample_rate


def run_ffmpeg(source_path: Path, output_path: Path, start_seconds: float, duration_seconds: float) -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required; install it before extracting the Jeremiah reference.")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_seconds:g}",
            "-i",
            str(source_path),
            "-t",
            f"{duration_seconds:g}",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        check=True,
    )


def convert_audio_to_reference(source_path: Path) -> float:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    requested_start = env_float("JEREMIAH_REFERENCE_START_SECONDS", DEFAULT_REFERENCE_START_SECONDS)
    duration_target = reference_duration_seconds()
    minimum_duration = env_float("JEREMIAH_REFERENCE_MIN_SECONDS", DEFAULT_MIN_REFERENCE_DURATION_SECONDS)
    if minimum_duration > duration_target:
        minimum_duration = min(DEFAULT_MIN_REFERENCE_DURATION_SECONDS, duration_target)

    attempts = [requested_start]
    if requested_start != 0:
        attempts.append(0.0)

    last_duration = 0.0
    for start_seconds in attempts:
        with tempfile.NamedTemporaryFile(dir=OUTPUT_DIR, suffix=".wav", delete=False) as output_file:
            temp_output = Path(output_file.name)
        try:
            print(f"Trimming source at {start_seconds:g}s for {duration_target:g}s...")
            run_ffmpeg(source_path, temp_output, start_seconds, duration_target)
            duration, channels, sample_width, sample_rate = measure_wav(temp_output)
            last_duration = duration
            if (
                duration >= minimum_duration
                and channels == CHANNELS
                and sample_width == SAMPLE_WIDTH
                and sample_rate == SAMPLE_RATE
            ):
                temp_output.replace(OUTPUT_PATH)
                return duration
            print(
                "Trim output did not meet reference requirements "
                f"(duration={duration:.1f}s, channels={channels}, "
                f"sample_width={sample_width}, sample_rate={sample_rate})."
            )
        except subprocess.CalledProcessError as exc:
            print(f"ffmpeg trim failed at start={start_seconds:g}s: {exc}")
        finally:
            if temp_output.exists():
                temp_output.unlink(missing_ok=True)

    raise SystemExit(
        "Could not create a usable Jeremiah reference WAV "
        f"(last duration {last_duration:.1f}s; minimum {minimum_duration:.1f}s)."
    )


def transcribe_reference_with_deepgram(audio_path: Path) -> str:
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise SystemExit("DEEPGRAM_API_KEY is required to write an aligned F5-TTS reference transcript.")

    query = parse.urlencode(
        {
            "model": os.getenv("JEREMIAH_REFERENCE_STT_MODEL", "nova-3"),
            "smart_format": "true",
            "punctuate": "true",
        }
    )
    req = request.Request(
        f"{DEEPGRAM_LISTEN_URL}?{query}",
        data=audio_path.read_bytes(),
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "audio/wav",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as response:
            payload = json.loads(response.read().decode())
    except error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"Deepgram reference transcription failed: HTTP {exc.code} {detail}") from exc

    try:
        transcript = payload["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit("Deepgram reference transcription response did not include a transcript.") from exc

    if len(transcript) < MIN_TRANSCRIPT_CHARS:
        raise SystemExit(
            "Deepgram reference transcription was too short to use safely "
            f"({len(transcript)} chars)."
        )
    return transcript


def main() -> int:
    load_env_file(APP_ROOT / ".env")
    load_env_file(APP_ROOT / "backend" / ".env")

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise SystemExit("ELEVENLABS_API_KEY is required")

    source_path, source_label = download_existing_voice_sample(api_key)
    try:
        duration_s = convert_audio_to_reference(source_path)
    finally:
        source_path.unlink(missing_ok=True)

    transcript = transcribe_reference_with_deepgram(OUTPUT_PATH)
    REFERENCE_TEXT_PATH.write_text(f"{transcript}\n")

    print(f"Source:     {source_label}")
    print(f"Saved:      {OUTPUT_PATH}")
    print(f"Transcript: {REFERENCE_TEXT_PATH}")
    print(f"Duration:   {duration_s:.1f}s")
    print(f"Transcript chars: {len(transcript)}")
    print(f"Size:       {OUTPUT_PATH.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
