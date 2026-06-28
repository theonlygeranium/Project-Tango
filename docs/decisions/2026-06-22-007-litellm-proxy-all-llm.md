# ADR-007: Route All LLM Requests Through LiteLLM Proxy

**Date:** 2026-06-22
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Project Tango uses two LLM backends: Ollama (local GPU inference of Qwen3.6) and WRITER Palmyra X5 (cloud API). Schubert already runs a shared LiteLLM proxy (`polyglot-litellm.service` on port 4000) used by other projects (watson-ai, MeetScribe, Project Foxtrot).

## Decision

All LLM requests from Project Tango route through the **LiteLLM proxy at `http://localhost:4000`**. Tango never calls Ollama (`localhost:11434`) or WRITER cloud APIs directly.

- Ollama models are referenced as `local/qwen3-fast`
- WRITER Palmyra is referenced as `writer/palmyra-x5-voice`

## Rationale

- Credential centralization: WRITER API keys live only in LiteLLM config — never in Tango's `.env`
- Model aliasing: switching models requires updating one LiteLLM config, not all downstream projects
- Consistent logging, rate limiting, and fallback behavior across all Schubert projects
- Avoids duplicating `WRITER_API_KEY` or `PALMYRA_API_KEY` in Tango's environment

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Direct Ollama HTTP calls | Bypasses credential management; Ollama has no auth |
| Direct WRITER API calls | Requires storing WRITER_API_KEY in Tango .env — violates security policy |
| Separate LiteLLM instance for Tango | Unnecessary; shared instance already handles all Schubert projects |

## Consequences

- `PALMYRA_API_KEY` and `WRITER_API_KEY` must never appear in `backend/.env`
- `LITELLM_MASTER_KEY` and `LITELLM_BASE_URL=http://localhost:4000` are the only LLM-related env vars in Tango
- If LiteLLM goes down, all Tango personas are offline — this is acceptable given the single-machine architecture
- Any new LLM model must be registered in LiteLLM config before being referenced in Tango's persona definitions
