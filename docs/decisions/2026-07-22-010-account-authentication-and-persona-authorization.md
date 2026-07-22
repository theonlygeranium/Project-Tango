# ADR: Password accounts, server sessions, and persona authorization

**Date:** 2026-07-22
**Status:** Accepted
**Decided by:** EdStratum Labs and Codex

## Context

Project Tango previously exposed its interface and voice-token, dispatch,
history, and memory APIs without an account boundary. The requested experience
uses a single password field rather than an email/password pair, while an admin
must be able to provision regular users, assign personas, choose each persona's
default or an allowlisted model override, and reset generated passwords.

A visual frontend gate would not protect the API, and the existing persona-only
history and memory queries would mix data between users.

## Decision

- FastAPI is the authority for credentials, sessions, roles, persona access,
  effective model policy, voice-room grants, history, and memory ownership.
- Next.js is the browser-facing backend-for-frontend. Protected browser calls
  use same-origin route handlers; client code does not call the public FastAPI
  host or mint LiveKit tokens directly.
- Generated passwords contain 12 characters selected from lowercase letters
  and digits with ambiguous characters removed.
- Store an Argon2id password hash plus a unique HMAC-SHA-256 lookup digest made
  with a separate server secret. The lookup permits constant-time account
  selection for a one-field login; Argon2id remains the password verifier.
- Use opaque random session tokens. Store only token digests in PostgreSQL and
  send the token in a host-only, `HttpOnly`, `Secure`, `SameSite=Strict` cookie.
- Require a valid request origin and CSRF token for authenticated mutations.
- Rate-limit failed login attempts persistently by network and credential
  digest, with atomic counters, bounded Argon2id verification concurrency, and
  a dummy verification for unknown credentials.
- Dashboard-created accounts are always `regular`. Admin access is created only
  through the bootstrap operation.
- A persona-access row enables that persona. A null model override means the
  source-controlled persona default; a non-null override must match Tango's
  LiteLLM allowlist.
- Connection details and room names are generated server-side. Dispatch accepts
  only an authenticated, unexpired room grant issued to the same account.
- Store and query `user_id` on voice sessions and memories. Legacy rows are
  adopted by the initial admin during bootstrap and never exposed to regular
  users without ownership.
- Creating or resetting a password returns the plaintext once. It is never
  stored, logged, or recoverable. Reset/deactivation revokes sessions and room
  grants, removes connected participants, and workers periodically revalidate
  account activity as a backstop.

## Rationale

This design satisfies the intentionally minimal login UI without weakening
password storage or performing an Argon2 scan across all accounts. Server-side
policy prevents request tampering, and ownership scoping prevents cross-account
history or memory disclosure.

## Alternatives Considered

- UI-only password gate: rejected because protected backend routes remain
  callable directly.
- Email plus password login: rejected because the required experience is one
  password field.
- Reversible password encryption: rejected because passwords must not be
  retrievable.
- Client-visible JWT or local storage: rejected because browser script access
  increases the effect of cross-site scripting.
- Arbitrary model configuration: rejected because it could bypass LiteLLM or
  disclose provider credentials.

## Consequences

- `TANGO_AUTH_LOOKUP_KEY` becomes a required secret and must not enter Git,
  examples, logs, or client bundles.
- Database migration `004` must be applied before the authenticated services
  start, followed by a one-time admin bootstrap.
- Password reset is disruptive by design: existing web and voice sessions are
  revoked and connected participants are removed.
- Both services require a restart after deployment; PostgreSQL does not.
- The standalone frontend needs a server-only internal FastAPI base URL.

## References

- `backend/migrations/004_accounts_auth.sql`
- `backend/auth.py`
- `backend/accounts.py`
- `frontend/app/api/`
- `docs/runbooks/RB-04-account-administration.md`
