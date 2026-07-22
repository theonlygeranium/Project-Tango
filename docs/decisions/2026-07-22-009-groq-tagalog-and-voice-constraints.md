# ADR: Route Tagalog personas through Groq Scout and prepend voice constraints

**Date:** 2026-07-22
**Status:** Accepted
**Decided by:** EdStratum Labs and Codex

## Context

The live Schubert deployment contained three valuable source changes that were
not yet represented in Git: a LiteLLM alias for Groq Llama 4 Scout, Groq Scout
defaults for the two Tagalog personas, and a universal voice-interface prompt
layer. Leaving those changes only on the server made normal deployments unsafe
and allowed persona prompts to drift away from the production behavior.

## Decision

- Add `groq/llama4-scout` to Tango's source-controlled LiteLLM allowlist.
- Use that alias by default for Mama Lulu and Tita Baby.
- Keep both Tagalog personas on Deepgram Nova-3 with `language="tl"`.
- Prepend the same voice-interface constraint layer whenever a persona is
  resolved. Persona definitions remain the second, identity-specific layer.
- Continue routing all model calls through LiteLLM; Tango does not call Groq or
  Ollama directly.

## Rationale

This preserves the production behavior already validated on Schubert while
making it reproducible. Central prompt composition also guarantees concise,
spoken responses and infrastructure non-disclosure without duplicating the
same rules across every persona.

## Alternatives Considered

- Keep the changes only on Schubert: rejected because an automated deployment
  would overwrite them.
- Copy the universal block into every persona prompt: rejected because the
  duplicated text would drift.
- Switch Tagalog STT to Flux: rejected because Flux does not support Tagalog.

## Consequences

- LiteLLM must expose the `groq/llama4-scout` alias before these personas start.
- Account-level model overrides may choose this alias, but only through the
  source-controlled allowlist.
- Prompt inspection tests must account for the universal Layer 1 prefix.

## References

- `backend/personas.py`
- `frontend/lib/llm-models.ts`
- `frontend/lib/personas.ts`
- `docs/decisions/2026-06-22-007-litellm-proxy-all-llm.md`
- `docs/decisions/2026-06-28-003-nova3-tagalog-stt.md`
