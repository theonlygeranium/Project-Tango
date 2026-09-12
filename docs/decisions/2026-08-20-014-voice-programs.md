# ADR: Voice-Created Programs (Subroutines)

**Date:** 2026-08-20
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

Project Tango personas have fixed system prompts defined in
`backend/personas.py`. While Control Mode (ADR-013) allows adjusting a
persona's behavior mid-conversation, there is no mechanism for the user to
create entirely new conversation modes — specialized profiles that change what
the persona talks about and how, while keeping the same voice, TTS engine, STT
model, and MCP tools.

The user requested the ability to ask the voice agent to create a new named
"program" (e.g., "create a therapy program where you discuss emotional
wellness") and then activate it later by saying "activate therapy program."
These programs should persist across sessions and be activatable both by voice
and via a frontend UI.

## Decision

Implement voice-created derived personas (programs) with the following design:

1. **Programs as derived personas**: A program inherits the base persona's
   voice, TTS, STT, MCP tools, and EOT settings. Only the system prompt
   changes. This avoids needing to reconfigure TTS/STT mid-session and keeps
   the implementation simple.

2. **Creation via Control Mode**: The `create_program` function tool is only
   available in Control Mode, ensuring the user is in an administrative state
   when defining new programs. The user describes the desired behavior in
   natural language and the LLM generates the full system prompt.

3. **PostgreSQL persistence**: A new `tango.programs` table (migration 007)
   stores programs with `id`, `base_persona_id`, `name`, `description`,
   `system_prompt`, `active`, `created_at`, and `updated_at`. Programs survive
   restarts and apply to all future sessions with that base persona.

4. **Activation by voice**: During normal conversation, the user says
   "activate [name] program". The `on_user_turn_completed` hook detects the
   activation phrase, loads the program from the database, and calls
   `agent.update_instructions()` to swap in the program's prompt (merged with
   the base persona's non-persona-specific preamble).

5. **Activation by UI**: The frontend Program Library displays all active
   programs as tappable cards grouped by base persona. Tapping a card starts a
   conversation with the program pre-activated via the `program_name` parameter
   in the connection-details request.

6. **Deactivation by voice**: The user says "deactivate program" or "return to
   default" to restore the base persona's original instructions.

7. **One program active at a time**: Activating a program deactivates the
   previous one. Only one program can be active per session.

8. **Program names unique per persona**: Two programs under the same base
   persona cannot share a name. Names are case-insensitive.

9. **Master switch**: `TANGO_PROGRAMS` env var (default true) for fail-safe
   rollback.

## Rationale

- **Inheriting base persona config keeps the implementation simple**: Only the
  system prompt changes — no need to reconfigure TTS, STT, voice, or MCP tools
  mid-session. The `agent.update_instructions()` call is the only runtime
  change needed.
- **LLM-generated system prompts lower the barrier to creation**: The user
  describes what they want in natural language and the LLM translates that into
  a structured system prompt. No prompt engineering knowledge required.
- **Control Mode as the creation gate ensures administrative intent**: Programs
  are persistent and affect all future sessions, so creation should require
  deliberate administrative action.
- **Dual activation (voice + UI) covers both interaction modes**: Voice
  activation is natural during a conversation; UI activation is convenient
  before starting a call. Both paths use the same underlying mechanism.
- **PostgreSQL persistence ensures programs survive restarts**: The user's
  programs are not lost on deploy or service restart.
- **Read-only frontend keeps the UI simple**: Creation and editing are
  voice-only via Control Mode. The frontend displays and activates programs but
  cannot create or edit them, avoiding a complex prompt editor.

## Alternatives Considered

1. **Full agent swap via `session.update_agent()`**: Rejected as unnecessarily
   complex. `update_instructions()` achieves the same goal with less overhead
   and no need to reconstruct the agent or reconfigure TTS/STT.

2. **In-memory only (no DB persistence)**: Rejected because the user's programs
   should apply to all future sessions, not just the current conversation.
   Programs represent a persistent customization of the persona.

3. **Frontend creation UI**: Rejected because it would require a complex prompt
   editor and break the voice-first design philosophy. Creation via Control
   Mode lets the LLM translate natural language into a structured prompt.

4. **Multiple programs active simultaneously**: Rejected for simplicity. One
   program active at a time keeps the conversation focused and avoids prompt
   conflicts.

5. **Separate TTS/STT per program**: Rejected because it would require
  reconfiguring the audio pipeline mid-session, which is complex and risky.
  Inheriting the base persona's audio config is simpler and sufficient.

6. **Programs as separate personas in the persona catalog**: Rejected because
   programs are derived from and tied to a base persona. They should not appear
   as top-level persona options — they are activated on top of a base persona.

## Consequences

- A new database table (`tango.programs`) and migration (007) must be
  maintained.
- The `Jarvis` agent class now carries program state (`_active_program`,
  `_base_instructions` for restoration).
- `backend/programs.py` provides phrase detection, DB functions, and function
  tools for program management.
- `backend/main.py` exposes `GET /api/programs` for the frontend Program
  Library.
- `frontend/components/ProgramLibrary.tsx` adds a new UI section to the welcome
  screen.
- `frontend/hooks/useConnectionDetails.ts` accepts an optional `program_name`
  parameter for pre-activation.
- Program names must be unique per base persona (case-insensitive).
- Programs are cumulative — there is no undo. The user must explicitly
  deactivate or the program must be deactivated in the database.

## References

- LiveKit Agents SDK `Agent.update_instructions()` —
  `backend/venv/.../livekit/agents/voice/agent.py`
- LiveKit Agents SDK `Agent.on_user_turn_completed()` —
  `backend/venv/.../livekit/agents/voice/agent.py`
- `backend/programs.py` — Programs implementation
- `backend/jarvis_agent.py` — Jarvis agent with program integration
- `backend/migrations/007_programs.sql` — Database migration
- `frontend/components/ProgramLibrary.tsx` — Frontend program library
- ADR-013 — Control Mode (precedent for voice-driven persona modification)
- ADR-012 — Voice Agent MCP Knowledge Access (precedent for persona-scoped
  features)
