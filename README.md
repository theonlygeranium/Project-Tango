# Project Tango

Project Tango is EdStratum Labs' private, persona-driven AI voice companion. It
combines a Next.js WebRTC interface with a FastAPI/LiveKit agent backend. The web app,
API and voice worker run on Schubert at `https://project-tango.schubert.life`; media is
relayed through LiveKit Cloud, and speech and voice services are Deepgram and ElevenLabs.

## Stack

- Next.js 15 App Router frontend and same-origin backend-for-frontend routes
- FastAPI account, authorization, LiveKit token, dispatch, history, and memory APIs
- LiveKit Agents SDK voice worker (`livekit-agents` pinned to 1.8.4)
- PostgreSQL schema `tango` for users, sessions, persona policy, and memories
- Deepgram Flux for English (Flux ends the user's turn) and Nova-3 `tl` for Tagalog
- ElevenLabs Flash v2.5 with a Deepgram Aura fallback; an optional F5-TTS sidecar
  exists but no persona uses it by default
- LiteLLM-only model routing to local and approved hosted models

## Account model

The interface is gated by a one-field generated-password login. FastAPI stores
Argon2id password hashes, HMAC lookup digests, and opaque server-session token
digests; plaintext passwords are shown only once when an admin creates or resets
an account. Regular users see only their assigned personas, and each assignment
may use the persona default model or an admin-selected allowlisted override.
Administrators also see each persona's source default model on the main Tango
screen and may choose any allowlisted model for their own next voice session.
These session choices do not change the persona defaults or regular-user policy.

The admin dashboard lives at `/admin`. It includes the current source-controlled
persona/model and voice-pipeline map alongside account provisioning. Accounts
created in the dashboard are always regular users; the first admin is created
with the backend bootstrap command documented in
[RB-04](docs/runbooks/RB-04-account-administration.md).

## Voice pipeline

The per-session pipeline, persona table and design decisions are in
[docs/architecture.md](docs/architecture.md). The 2026-10-05 review of audio and
conversation behaviour, with what was fixed and what is still open, is in
[docs/reviews/2026-10-05-voice-pipeline-review.md](docs/reviews/2026-10-05-voice-pipeline-review.md).
Architectural decisions are indexed in [docs/decisions/README.md](docs/decisions/README.md).

## Development

See [docs/setup.md](docs/setup.md) for environment, migration, build, and
deployment steps. The production architecture and security boundary are in
[docs/architecture.md](docs/architecture.md). Repository agents must follow
[AGENTS.md](AGENTS.md) before making any change.
