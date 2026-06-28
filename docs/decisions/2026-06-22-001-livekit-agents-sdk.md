# ADR-001: Use LiveKit Agents SDK (Not Pipecat)

**Date:** 2026-06-22
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Project Tango requires a real-time voice agent framework that integrates with LiveKit's WebRTC infrastructure. Two primary options were evaluated: Pipecat (the framework used by the upstream AURA fork) and the LiveKit Agents SDK (`livekit-agents`).

## Decision

Use the **LiveKit Agents SDK** (`livekit-agents` PyPI package) as the exclusive voice agent framework. Pipecat is explicitly prohibited.

## Rationale

- LiveKit Agents is natively designed for LiveKit's infrastructure — no adapter layer
- `AgentSession` pipeline model maps cleanly to Tango's persona-driven architecture
- Deepgram and ElevenLabs both have first-class LiveKit Agents plugins
- Active development with strong community support
- Eliminates a full dependency layer, reducing failure surface

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Pipecat | Used in upstream AURA fork but adds unnecessary abstraction; incompatible with LiveKit Agents in same pipeline |
| Vapi / Bland AI | Managed voice services — rejected by owner |
| Raw LiveKit SDK | Too low-level; would require reimplementing STT/TTS orchestration |

## Consequences

- All agents must use `AgentSession`, `livekit.agents.Agent`, and LiveKit Agents plugin classes exclusively
- `pipecat-ai` is permanently prohibited — never install or import
- Plugin APIs are defined by LiveKit Agents and must be followed as documented in `AGENTS.md`

## References

- https://github.com/livekit/agents
- https://docs.livekit.io/agents/
