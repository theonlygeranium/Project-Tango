# ADR-003: Use Deepgram Nova-3 Monolingual `tl` for Tagalog Personas

**Date:** 2026-06-28
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Tita Baby and Mama Lulu are Tagalog/Taglish-speaking personas. Initial STT attempts using `nova-3-multi` produced phonetic fallback transcriptions for Tagalog — spelling words as they sound in English rather than using correct Tagalog orthography. Flux (`flux-general-multi`) was also attempted but does not include Tagalog in its supported language set.

## Decision

Use **Deepgram Nova-3** with `language="tl"` and `smart_format=True` for Tita Baby and Mama Lulu. Do not use Flux for any Tagalog persona.

## Rationale

- Flux Multilingual does **not** include Tagalog as of 2026
- `nova-3-multi` falls back to phonetic transcription for Tagalog — unreadable to the LLM
- `nova-3` with `language="tl"` (monolingual) produces correct Tagalog orthography
- `smart_format=True` enables language-aware formatting for Tagalog text
- User testing confirmed Tita Baby correctly understood Tagalog input after the switch

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| `flux-general-multi` | Does not support Tagalog; silent transcription failures |
| `nova-3-multi` | Phonetic fallback — LLM cannot understand output |
| `nova-2-general` | Older model; Nova-3 `tl` offers better accuracy |
| English-only STT | Users speak Taglish; English STT cannot capture Tagalog |

## Consequences

- `backend/main.py` must conditionally select STT model per persona
- Do not change Tagalog personas to Flux without explicit re-evaluation
- Tagalog personas use Nova-3's `endpointing_ms=300` instead of Flux native EOT

## References

- https://developers.deepgram.com/docs/models-languages-overview
