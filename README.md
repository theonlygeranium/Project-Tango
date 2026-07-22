# Project Tango

Project Tango is EdStratum Labs' private, persona-driven AI voice companion. It
combines a Next.js WebRTC interface with a FastAPI/LiveKit agent backend and is
self-hosted on Schubert at `https://project-tango.schubert.life`.

## Stack

- Next.js 15 App Router frontend and same-origin backend-for-frontend routes
- FastAPI account, authorization, LiveKit token, dispatch, history, and memory APIs
- LiveKit Agents SDK voice worker
- PostgreSQL schema `tango` for users, sessions, persona policy, and memories
- Deepgram Flux for English and Nova-3 `tl` for Tagalog speech recognition
- ElevenLabs Flash v2.5 and the optional Jeremiah F5-TTS sidecar
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

## Development

See [docs/setup.md](docs/setup.md) for environment, migration, build, and
deployment steps. The production architecture and security boundary are in
[docs/architecture.md](docs/architecture.md). Repository agents must follow
[AGENTS.md](AGENTS.md) before making any change.
