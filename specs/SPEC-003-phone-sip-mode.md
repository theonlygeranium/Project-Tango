# SPEC-003 — LiveKit Native Phone / SIP Mode
**Project:** Project Tango
**Priority:** 3 (Phase 3)
**Status:** Ready for implementation
**Spec Author:** WRITER Agent — June 27, 2026
**Codebase Ref:** `theonlygeranium/Project-Tango` @ `fdc9144` (v1.0-stable)
**Estimated Effort:** 2–3 days
**Dependency:** None — additive only, does not touch existing web session flow
**Risk Level:** Medium — requires LiveKit Cloud SIP configuration and phone number purchase; new infra path, but agent code is unchanged

---

## 1. Problem Statement

Project Tango is currently web-only. Users must open a browser, load the UI, and select a persona manually. For many real-world use cases — calling Tita Baby from iOS, reaching Damian during a commute, or having Jeremiah available at a moment's notice — a phone call is a far more natural entry point.

The original enhancement report described Phone/SIP as requiring a third-party bridge (Twilio/Telnyx). **This was incorrect.** As of LiveKit Agents 1.x and LiveKit Cloud GA (November 2025), LiveKit includes native telephony (SIP) as a built-in feature. No external SIP bridge is required.

Because Project Tango already runs on LiveKit Cloud (`wss://project-tango-0xs3szq3.livekit.cloud`) using `livekit-agents` 1.6.2, adding phone mode is primarily a **configuration and backend routing** task. The core agent pipeline — Deepgram STT, LiteLLM, ElevenLabs TTS — is completely unchanged.

---

## 2. Architecture Overview

```
Caller dials phone number
    │  PSTN
    ▼
LiveKit Cloud SIP Trunk (inbound)
    │  SIP INVITE → LiveKit room per call
    ▼
LiveKit Cloud Room
    │  room metadata: persona routed from phone number / room prefix
    ▼
TangoAgent (existing LiveKit Agent Worker on Schubert)
    │  same pipeline: Deepgram Flux STT → LiteLLM → ElevenLabs Flash TTS
    │  same persona system prompts, voice IDs, keyterms
    ▼
ElevenLabs Flash v2.5 TTS audio → LiveKit → SIP → caller hears
```

**Key insight:** The agent dispatch path (`POST /api/dispatch` → `CreateAgentDispatchRequest`) is the same for web and SIP calls. The room is populated by a phone caller instead of a WebRTC browser. The agent does not know or care about the transport.

---

## 3. LiveKit SIP Concepts

### 3.1 Inbound SIP Trunk

A SIP trunk in LiveKit Cloud receives inbound calls from the PSTN:
- Configured with a `trunk_id` (LiveKit-assigned)
- An inbound phone number (purchased or ported via LiveKit or a carrier)
- Routing rules that map calls to LiveKit rooms

### 3.2 SIP Dispatch Rules

A dispatch rule defines what room a call is routed to. For Project Tango:
- Each persona gets a `CreateSipDispatchRuleDirectCall` routing rule
- Rule maps phone number → room name prefix `tango-<persona_key>-<call_id>`

### 3.3 Phone Number Options

**Option A — Dedicated numbers per persona (recommended)**
- One phone number per persona
- Caller dials the persona's number → routed directly, zero friction
- Cost: ~$2/month per number
- Start with 2–3 personas: Damian, Tita Baby, Jeremiah

**Option B — Shared number with DTMF IVR**
- One number answers all calls
- IVR: "Press 1 for Damian, 2 for Chris, 3 for Tita Baby…"
- Cost: $2/month total
- Trade-off: added friction before reaching the persona

**Recommendation:** Start with Option A for Damian, Tita Baby, and Jeremiah. Expand after validating the flow.

---

## 4. LiveKit Dashboard Configuration (Human Action Required)

These steps are performed in the LiveKit Cloud dashboard at `https://cloud.livekit.io` for project `project-tango-0xs3szq3`. They require human action in the UI or via the LiveKit Management API.

### Step 1 — Enable SIP

1. Log in to https://cloud.livekit.io
2. Select project `project-tango-0xs3szq3`
3. Navigate to **SIP → Trunks**
4. Click **Create Inbound Trunk**
5. Name it: `tango-inbound`
6. Save — record the `trunk_id`

### Step 2 — Purchase Phone Numbers

1. In **SIP → Phone Numbers**, click **Purchase Number**
2. Select US numbers (or Philippine numbers for Tita Baby/Mama Lulu if available)
3. Purchase 2–3 numbers
4. Record each phone number and the persona it maps to

### Step 3 — Create Dispatch Rules (one per persona)

| Persona | Room Prefix | Rule Type |
|---|---|---|
| Damian (therapy) | `tango-therapy-` | DirectCall |
| Tita Baby (pinoy-pride) | `tango-pinoy-pride-` | DirectCall |
| Jeremiah (general-info) | `tango-general-info-jeremiah-` | DirectCall |

Assign each purchased phone number to its corresponding dispatch rule via the LiveKit dashboard or CLI.

---

## 5. Backend Changes

### 5.1 New file: `backend/sip.py`

Create `backend/sip.py`:

```python
"""
sip.py — SIP call persona resolution for Project Tango.

When a caller arrives via LiveKit SIP, the room name contains the persona prefix
(e.g. "tango-therapy-<call_uuid>"). This module extracts the persona key from
the room name so the existing entrypoint() loads the correct persona config.

Usage in main.py entrypoint():
    from sip import persona_key_from_room_name

    persona_key = (
        ctx.room.metadata.get("persona")              # web sessions
        or persona_key_from_room_name(ctx.room.name)  # SIP calls
    )
"""

import logging

logger = logging.getLogger(__name__)

# Maps room name prefix → persona key (must match personas.py PERSONAS dict keys)
_PREFIX_TO_PERSONA: dict[str, str] = {
    "tango-therapy-":                   "therapy",
    "tango-general-info-jeremiah-":     "general-info",
    "tango-general-info-":              "general-info",
    "tango-meditation-":                "meditation",
    "tango-pinoy-pride-":               "pinoy-pride",
}


def persona_key_from_room_name(room_name: str) -> str | None:
    """
    Extracts a persona key from a LiveKit SIP-generated room name.
    Returns None if the room name does not match any known SIP prefix.

    Examples:
        "tango-therapy-a1b2c3d4"              → "therapy"
        "tango-pinoy-pride-x9y8z7w6"          → "pinoy-pride"
        "tango-general-info-jeremiah-abcdef"  → "general-info"
        "some-other-room"                     → None
    """
    for prefix, persona_key in _PREFIX_TO_PERSONA.items():
        if room_name.startswith(prefix):
            logger.info("sip: resolved persona '%s' from room '%s'", persona_key, room_name)
            return persona_key

    logger.warning("sip: could not resolve persona from room name '%s'", room_name)
    return None


# SIP greeting addendum — injected when is_sip=True
# The agent introduces itself since the caller cannot see the UI.
SIP_GREETING_ADDENDUM = (
    "\n\nThis is a phone call (SIP session). Begin your greeting by introducing yourself "
    "by name and role before anything else. Keep the introduction warm and brief — "
    "one sentence maximum. Example: 'Hi, this is Damian — I'm your wellness companion. "
    "I'm really glad you called.'"
)
```

### 5.2 Modify `backend/main.py` — SIP persona fallback in `entrypoint()`

Add the SIP fallback immediately after the existing metadata lookup:

```python
from sip import persona_key_from_room_name, SIP_GREETING_ADDENDUM

# Existing: reads from room metadata (web sessions)
persona_key = ctx.room.metadata.get("persona") if ctx.room.metadata else None

# NEW: SIP fallback — infer persona from room name prefix
is_sip = False
if not persona_key:
    persona_key = persona_key_from_room_name(ctx.room.name)
    is_sip = persona_key is not None

if not persona_key:
    logger.error("entrypoint: no persona resolved for room %s — defaulting to general-info", ctx.room.name)
    persona_key = "general-info"

# ... load persona config ...

# Augment instructions for SIP calls
if is_sip:
    augmented_instructions += SIP_GREETING_ADDENDUM
```

---

## 6. No Frontend Changes Required

The existing web frontend is completely unaffected. Phone mode is a parallel entry point.

**Optional UX addition:** Display the phone number for each persona on the persona card:

```tsx
{persona.phoneNumber && (
  <p className="text-xs text-white/40 mt-1">📞 {persona.phoneNumber}</p>
)}
```

Add `phoneNumber?: string` to the `Persona` type in `frontend/lib/types.ts`. Populate from `personas.json` or frontend persona config after numbers are confirmed.

---

## 7. Codex Execution Order

### Phase A — Infrastructure (human action required)

1. **Human action:** Complete Steps 1–3 in Section 4 (LiveKit Dashboard).
2. **Record:** Trunk ID, purchased phone numbers, dispatch rule IDs.
3. **Verify trunk is active:** LiveKit dashboard → SIP → Trunks → confirm `tango-inbound` status is Active.

### Phase B — Code changes

4. **Create `backend/sip.py`** with content from Section 5.1.

5. **Compile check:**
   ```bash
   python3 -m py_compile backend/sip.py && echo "OK"
   ```

6. **Modify `backend/main.py`** — add SIP persona fallback per Section 5.2.

7. **Compile check:**
   ```bash
   python3 -m py_compile backend/main.py && echo "OK"
   ```

8. **Deploy to Schubert:**
   ```bash
   sudo systemctl restart tango-backend
   systemctl is-active tango-backend
   curl -s https://tango-api.schubert.life/healthz
   ```

9. **Test the SIP flow:**
   - Dial the phone number assigned to Damian (`tango-therapy-`)
   - Verify: call connects, agent greets by persona
   - Check backend logs: `sip: resolved persona 'therapy' from room 'tango-therapy-...'`
   - Have a short conversation and hang up
   - Verify: session appears in `tango.sessions` with `persona = 'therapy'`
   - Verify: memory generation runs (SPEC-001 integration)

10. **Commit:**
    ```
    git add backend/sip.py backend/main.py
    git commit -m "feat(sip): add LiveKit native phone/SIP mode with persona routing"
    git push origin main
    ```

---

## 8. Acceptance Criteria

| ID | Criterion | How to Verify |
|---|---|---|
| AC-001 | LiveKit inbound SIP trunk is active | LiveKit dashboard |
| AC-002 | Dispatch rule maps phone number to correct room prefix | Test call routes to `tango-therapy-*` room |
| AC-003 | Agent resolves correct persona from SIP room name | Backend log: `sip: resolved persona '...'` |
| AC-004 | Agent greets caller with SIP-aware introduction | Listen to first 10s of call |
| AC-005 | Deepgram Flux STT transcribes phone audio correctly | Check `tango.turns` after call |
| AC-006 | ElevenLabs TTS audio plays to caller | Audible during call |
| AC-007 | Session is written to `tango.sessions` with correct persona | psql query after call |
| AC-008 | End call (hang up) closes session cleanly; `ended_at` populated | psql query after hang up |
| AC-009 | Web sessions are completely unaffected by SIP changes | QA: web session before and after deploy |
| AC-010 | No persona confusion — all configured numbers resolve correctly | Test each configured number |

---

## 9. SIP Audio Quality Notes

Phone network audio (PCMU/PCMA codecs) is 8kHz narrowband, significantly lower quality than WebRTC's 48kHz wideband.

**Deepgram Flux for SIP:** Flux STTv2 handles 8kHz audio via `encoding=mulaw&sample_rate=8000` parameters on the WebSocket connection. The LiveKit Agents Deepgram plugin should pass these automatically for SIP rooms. Verify via backend logs that STT connects with `sample_rate=8000` for SIP sessions.

**ElevenLabs TTS:** ElevenLabs generates 44.1kHz/24kHz audio; LiveKit downsamples to 8kHz for the PSTN leg. No configuration change needed.

**Keyterm boosting:** Keyterms for Tita Baby and Mama Lulu (`Tita Baby`, `kumain ka na`, `Hay naku`) remain active on phone calls — they are configured on the Deepgram plugin, not on the audio format.

---

## 10. Estimated Costs

| Item | Cost |
|---|---|
| LiveKit SIP feature | Included in LiveKit Cloud plan |
| Phone numbers (3 US) | ~$6/month |
| Per-minute PSTN termination | ~$0.005–$0.01/min |
| Deepgram STT (phone calls) | Same rate as web — ~$0.008/min |
| ElevenLabs TTS | Same rate as web — character-based billing |

A 5-minute phone session costs approximately $0.10–$0.15 in PSTN + STT + TTS costs.

---

## 11. Future Extensions (Post-Phase 3)

| Feature | Description |
|---|---|
| Outbound calling | Agent proactively calls user for follow-up (requires SPEC-002 time-triggers) |
| DTMF IVR menu | Single number with keypad routing to any persona |
| Philippine numbers | Local PH number for Tita Baby / Mama Lulu |
| SMS follow-up | Post-call transcript delivered via SMS |
| Call recording disclosure | Automated legal disclosure prompt |

---

## 12. References

- LiveKit SIP first-party Phone Numbers (GA November 2025)
- LiveKit Agents 1.x SIP dispatch rules — `CreateSipDispatchRuleDirectCall`
- Deepgram Flux STTv2 audio encoding parameters (`encoding=mulaw&sample_rate=8000`)
- Deepgram Keyterm Prompting for Flux streams
- ElevenLabs Flash v2.5 — 32-language TTS at ~75ms latency
- Enhancement Review P3 analysis — `Project Tango_ENHANCEMENT_REVIEW_2026-06-28.md`
- LiveKit SIP docs: https://docs.livekit.io/sip/
