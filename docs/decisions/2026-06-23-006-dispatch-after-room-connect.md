# ADR-006: Dispatch Agent via POST /api/dispatch After room.connect()

**Date:** 2026-06-23
**Status:** Accepted
**Decided by:** Writer Agent (WRITER Agent platform)

## Context

In LiveKit Agents 1.x, workers do not automatically join rooms on creation. An agent must be explicitly dispatched into a room, and the room must have at least one participant before dispatch or the agent times out waiting for a participant to arrive.

The initial implementation dispatched the agent before the frontend confirmed the WebRTC connection, causing frequent "agent join timeout" errors in logs.

## Decision

The frontend calls `POST /api/dispatch` **after** `room.connect()` resolves successfully. The backend `/api/dispatch` endpoint calls `CreateAgentDispatchRequest(room=room_name)` using the Python SDK.

## Rationale

- Agent is dispatched only into an occupied room — no timeout waiting for the user to arrive
- `room=` parameter (not `room_name=`) is the correct field name in the LiveKit Agents 1.x Python SDK
- Clean separation: `/api/connection-details` handles authentication, `/api/dispatch` handles agent deployment
- Works consistently across all personas and media configurations

## Alternatives Considered

| Option | Rejected Because |
|---|---|
| Auto-dispatch on worker startup | Workers in LiveKit Agents 1.x do not support auto-join |
| Dispatch before room.connect() | Agent may time out if room is empty when dispatch fires |
| Single combined endpoint | Less debuggable; harder to retry just the dispatch step |
| Use `room_name=` parameter | Python SDK uses `room=` — `room_name=` silently does nothing |

## Consequences

- Frontend connect flow is two-step: connect → dispatch
- If dispatch fails (network error), the user has a WebRTC session but no agent — frontend must handle this gracefully
- Dispatch is idempotent per room — safe to retry
