#!/usr/bin/env python3
"""
Audit ElevenLabs voice IDs to classify them as premade / IVC / PVC.
Usage: python scripts/audit_elevenlabs_voices.py
Requires: ELEVENLABS_API_KEY in environment.
"""
import os
import sys

try:
    import requests
except ImportError:
    print("This script requires the 'requests' package. Install with: pip install requests")
    sys.exit(1)

API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
BASE_URL = os.environ.get("ELEVENLABS_BASE_URL", "https://api.us.elevenlabs.io/v1")

VOICE_IDS = {
    "therapy": "QF9HJC7XWnue5c9W3LkY",
    "general-info": "HfRP3cIhYLmeNHeTvkWK",
    "jeremiah": "EqHdTYoEuDQCxN1CVbi0",
    "jeremiah-v2": "lktV9XgoGxRX7e8LLRxv",
    "jacob": "qYwy2TckibCF9cBuhI46",
    "meditation": "pFQStpMdprGFILRDrWR2",
    "mama-lulu": "LF1xMOq6fDVEBEkLP0HO",
    "pinoy-pride": "smYFzUb4yrSqprnml7n5",
}

if not API_KEY:
    print("ERROR: ELEVENLABS_API_KEY is not set in the environment.")
    sys.exit(1)

headers = {"xi-api-key": API_KEY}
resp = requests.get(f"{BASE_URL}/voices", headers=headers, timeout=15)
resp.raise_for_status()
all_voices = {v["voice_id"]: v for v in resp.json().get("voices", [])}

print(f"{'Persona':<16} {'Voice ID':<24} {'Category':<14} {'Name':<30}")
print("-" * 90)
pvc_found = False
for persona_id, voice_id in VOICE_IDS.items():
    voice = all_voices.get(voice_id)
    if voice is None:
        print(f"{persona_id:<16} {voice_id:<24} {'NOT FOUND':<14}")
        continue
    category = voice.get("category", "unknown")
    name = voice.get("name", "unknown")
    print(f"{persona_id:<16} {voice_id:<24} {category:<14} {name:<30}")
    if category == "professional":
        pvc_found = True

print()
if pvc_found:
    print("WARNING: Professional Voice Clones (PVC) detected.")
    print("Consider adding use_pvc_as_ivc=True to mitigate PVC latency overhead.")
else:
    print("No Professional Voice Clones found. No IVC optimization needed.")
