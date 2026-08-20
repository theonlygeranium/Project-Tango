#!/usr/bin/env python3
"""
Verify ElevenLabs Flash v2.5 time-to-first-byte on the US endpoint.
Usage: python scripts/verify_elevenlabs_ttfb.py
Requires: ELEVENLABS_API_KEY in environment.
"""
import os
import sys
import time

try:
    import requests
except ImportError:
    print("This script requires the 'requests' package. Install with: pip install requests")
    sys.exit(1)

API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
BASE_URL = os.environ.get("ELEVENLABS_BASE_URL", "https://api.us.elevenlabs.io/v1")
VOICE_ID = "QF9HJC7XWnue5c9W3LkY"

if not API_KEY:
    print("ERROR: ELEVENLABS_API_KEY is not set in the environment.")
    sys.exit(1)

headers = {
    "xi-api-key": API_KEY,
    "Content-Type": "application/json",
    "Accept": "audio/mpeg",
}
payload = {
    "text": "Hello, this is a latency test.",
    "model_id": "eleven_flash_v2_5",
    "voice_settings": {
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "use_speaker_boost": False,
    },
}

print(f"Endpoint: {BASE_URL}")
print(f"Model: eleven_flash_v2_5")
print(f"Streaming TTFB test (5 iterations)...\n")

ttfb_samples = []
for i in range(5):
    start = time.perf_counter()
    response = requests.post(
        f"{BASE_URL}/text-to-speech/{VOICE_ID}",
        headers=headers,
        json=payload,
        stream=True,
        timeout=30,
    )
    response.raise_for_status()
    first_chunk = True
    for chunk in response.iter_content(chunk_size=4096):
        if first_chunk and chunk:
            ttfb = (time.perf_counter() - start) * 1000
            ttfb_samples.append(ttfb)
            print(f"  Iteration {i+1}: TTFB = {ttfb:.1f}ms")
            first_chunk = False
            break

if ttfb_samples:
    avg = sum(ttfb_samples) / len(ttfb_samples)
    print(
        f"\nAverage TTFB: {avg:.1f}ms "
        f"(min {min(ttfb_samples):.1f}, max {max(ttfb_samples):.1f})"
    )
    if avg < 150:
        print("PASS: TTFB is within the optimized Flash v2.5 range (<150ms).")
    elif avg < 300:
        print("WARN: TTFB is acceptable but higher than the 50ms model TTFB target.")
    else:
        print("FAIL: TTFB is high — verify US endpoint routing and network path.")
