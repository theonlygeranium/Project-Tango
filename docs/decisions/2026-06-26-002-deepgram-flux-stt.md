# ADR-002: Migrate English STT to Deepgram Flux

**Date:** 2026-06-26
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Project Tango initially used Deepgram Nova-3 for all personas. Nova-3 relied on polling-based end-of-turn detection, adding 200–600ms of perceived latency. Deepgram introduced Flux (STTv2) with native end-of-turn detection built into the transcription stream.

## Decision

Migrate all English-language personas (Damian, Chris, Jeremiah, Jacob, Nathaniel) from Deepgram Nova-3 to **Deepgram Flux** (`flux-general-en` via STTv2).

## Rationale

- Native end-of-turn detection eliminates 200–600ms polling latency
- Latency reduction is perceptible — conversations feel significantly more natural
- Flux is Deepgram's recommended model for new production deployments as of 2026
- First-class LiveKit Agents plugin support via `model="flux-general-en"`

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Keep Nova-3 for all personas | Retained polling-based turn detection; 200–600ms overhead |
| Nova-3 with reduced `endpointing_ms` | Reduces margin but increases false triggers mid-sentence |
| Flux for all personas including Tagalog | Flux Multilingual does not support Tagalog — see ADR-003 |

## Consequences

- Tagalog personas cannot use Flux — they require Nova-3 `language="tl"` (see ADR-003)
- Conditional STT model selection logic required in `backend/main.py`
- English users experience noticeably faster agent response time

## References

- https://developers.deepgram.com/docs/sttv2
