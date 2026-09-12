# ADR 016: MeetScribe → Discord Bot Context Integration

**Date:** 2026-08-19
**Status:** Accepted
**Decided by:** Writer Agent

## Context

MeetScribe is a meeting intelligence platform deployed on Schubert Nexus at `/opt/meetscribe` (port 8010). It provides a Meeting Corpus REST API with RAG (Retrieval-Augmented Generation) question answering, an MCP server for tool-based access, and automatic vector memory indexing of all processed sessions. When a meeting completes, MeetScribe generates AI summaries, action items, key decisions, and full transcripts — all indexed for semantic search.

However, two gaps prevent Discord bots in the Project Tango fleet from leveraging this meeting intelligence:

1. **No outbound event dispatch (push gap):** MeetScribe has no built-in webhook mechanism to notify external services when new notes become available. Discord bots have no way to know when new meeting data arrives without polling the API, which introduces latency and wasted requests.

2. **No Discord-side query wiring (pull gap):** No Discord bot in the Tango fleet is wired to query the MeetScribe corpus. Users asking "What was decided in last week's sync?" in Discord get no meeting context because the bots have no tools to reach the MeetScribe API.

The Discord bot fleet (Admiral Schubert, The Architect, Dr. Voss, Dr. Cortex, etc.) already has an agent tool-calling loop and an aiohttp webhook handler (`webhook_handler.py`). The Tango backend (FastAPI on port 8030) already has a PostgreSQL connection pool. The integration bridges these existing components to connect MeetScribe's corpus to the Discord bots.

## Decision

Implement a **hybrid push + pull integration** with three phases:

### Phase 1: Webhook Receiver (Push)

MeetScribe fires `notes.completed` webhooks to the Tango backend endpoint `POST /api/webhooks/meetscribe` in `backend/main.py`. The backend:

- Verifies the HMAC-SHA256 signature from the `X-MeetScribe-Signature` header using `MEETSCRIBE_WEBHOOK_SECRET`
- Parses the webhook payload (session ID, title, status, started_at, duration, summary, action_items, key_decisions)
- Stores the session metadata in the `tango.meetscribe_sessions` PostgreSQL table (migration `005_meetscribe_sessions.sql`)
- Returns HTTP 200 even on database failure (to prevent MeetScribe retry storms; errors are logged)

The Discord bot's `webhook_handler.py` also has a `MeetScribeWebhookHandler` class that adds a `POST /webhook/meetscribe` route to the bot's local aiohttp server. This receives forwarded webhooks, verifies signatures, caches session metadata locally, and posts rich Discord embeds announcing new meeting notes.

### Phase 2: Agent Tools (Pull)

Discord bots use the MeetScribe REST API (`/v1/sessions/query`) for RAG question answering when users ask about meetings. Six agent tools are defined in `scripts/meetscribe_tools.py`:

| Tool | MeetScribe API Endpoint | Purpose |
|---|---|---|
| `query_meetings` | `POST /v1/sessions/query` | RAG question answering with cited sources |
| `search_meetings` | `POST /v1/sessions/search` | Full-text search across titles, notes, transcripts |
| `list_recent_meetings` | `GET /v1/sessions` | List recent sessions with optional status/date filters |
| `get_meeting_notes` | `GET /v1/sessions/{id}/notes` | Fetch AI summary, action items, key decisions |
| `get_meeting_transcript` | `GET /v1/sessions/{id}/transcript` | Fetch full transcript with speaker labels and timestamps |
| `get_meetscribe_status` | `GET /v1/memory/status` | Check vector memory index health (chunk/session count) |

The `MeetScribeClient` class in `scripts/meetscribe_client.py` provides the async HTTP client (using `httpx`) with Bearer token authentication. Tool handlers format results for Discord display with markdown formatting and source citations.

### Phase 3: Local Session Metadata Cache

The `MeetScribeWebhookCache` class in `scripts/meetscribe_client.py` maintains a local JSON file cache of session metadata at `MEETSCRIBE_CACHE_PATH` (default: `/opt/Project-Tango/data/meetscribe_cache.json`). On bot startup, it bootstraps the cache by fetching recent sessions from the API (`GET /v1/sessions` with limit 200). Thereafter, it is updated incrementally by webhook events. This enables instant responses for common queries (e.g., "list recent meetings") without an API round-trip.

## Rationale

### Why Hybrid Push + Pull

A hybrid model was chosen over polling-only or webhook-only because each approach addresses a different failure mode:

1. **Push (webhooks) solves the latency problem.** Without webhooks, the only way to know when new meeting notes are available is to poll `GET /v1/sessions` at regular intervals. Polling every 5 minutes means up to 5 minutes of latency between a meeting completing and the bot knowing about it. Polling every 30 seconds means 288 API calls per day, most of which return nothing new. Webhooks deliver event notifications in real time — the bot knows about new notes within seconds of MeetScribe completing processing.

2. **Pull (API queries) solves the question-answering problem.** Webhooks alone can only notify — they cannot answer questions. When a user asks "What was decided about the Q3 roadmap?", the bot needs to query the MeetScribe RAG endpoint to get a grounded answer with cited sources. This requires a live API call; cached webhook data only contains metadata (title, summary, action items), not the full vector-indexed corpus needed for semantic search.

3. **The local cache bridges push and pull.** Webhook events populate the local cache with session metadata (title, summary, action items, key decisions). This cache serves instant responses for metadata queries ("list recent meetings", "what was the last meeting about?") without an API round-trip. For deeper queries (RAG question answering, full-text search, transcript retrieval), the bot falls back to the live API. This two-tier approach minimizes latency for common queries while maintaining full query power for complex questions.

### Why HMAC-SHA256 Webhook Signatures

MeetScribe webhooks are signed with HMAC-SHA256 using a shared secret (`MEETSCRIBE_WEBHOOK_SECRET`). The signature is sent in the `X-MeetScribe-Signature` header as `sha256=<hex_digest>`. This prevents:

- **Spoofed webhooks:** An attacker cannot forge a webhook without the secret
- **Replay attacks:** The payload includes a timestamp; stale payloads can be rejected
- **Man-in-the-middle attacks:** The signature verifies payload integrity end-to-end

The verification uses `hmac.compare_digest()` for constant-time comparison to prevent timing attacks.

### Why PostgreSQL for Webhook Storage

The Tango backend already has a PostgreSQL connection pool (used for conversation history, accounts, and memory). Storing webhook session metadata in `tango.meetscribe_sessions` provides:

- **Durability:** Survives backend restarts (unlike in-memory cache)
- **Queryability:** SQL queries for analytics, reporting, debugging
- **Consistency:** `ON CONFLICT (session_id) DO UPDATE` ensures idempotent upserts (duplicate webhooks don't create duplicate rows)
- **Integration:** Joinable with other Tango tables for cross-referencing

### Why a Separate Local Cache in Addition to PostgreSQL

The Discord bot runs as a separate process from the Tango backend. The bot's `MeetScribeWebhookCache` (JSON file) provides:

- **Independence:** The bot can answer metadata queries even if the backend is down
- **Speed:** File I/O is faster than a PostgreSQL round-trip from the bot process
- **Simplicity:** No database connection needed in the bot process (the bot already has Redis + Postgres for memory, but the MeetScribe cache is a lightweight addition)

## Alternatives Considered

### 1. Polling Only (No Webhooks)

**Rejected because:**
- **Latency:** Polling at 5-minute intervals means up to 5 minutes before the bot knows about new notes. Users asking "what was just discussed?" get stale answers.
- **Wasted requests:** Most polls return no new data. At 1-minute intervals, that's 1,440 API calls per day, 95%+ returning empty results.
- **Rate limiting:** MeetScribe API has rate limits. Polling consumes quota that could be used for actual user queries.
- **No real-time notifications:** The Discord bot cannot proactively announce "New meeting notes available!" without webhooks.

**When we might reconsider:** If MeetScribe adds webhook support natively and webhooks prove unreliable, polling could serve as a fallback sync mechanism.

### 2. Webhook Only (No API Queries)

**Rejected because:**
- **Cannot answer questions:** Webhooks only deliver event notifications with metadata. They cannot perform RAG question answering across the full corpus.
- **No semantic search:** Webhook payloads contain summaries, not vector embeddings. Semantic queries ("what was decided about the roadmap?") require the MeetScribe RAG endpoint.
- **No transcript access:** Full transcripts are too large for webhook payloads. On-demand API retrieval is necessary.
- **No historical queries:** Webhooks only fire for new events. Historical meeting data requires API queries.

**When we might reconsider:** Never. Webhooks alone fundamentally cannot provide question-answering capability.

### 3. MCP Server Direct Integration

**Rejected for now because:**
- **Not yet wired:** MeetScribe has an MCP server, but no Discord bot in the Tango fleet is currently configured to connect to it.
- **Complexity:** MCP integration requires MCP client configuration, server discovery, and tool mapping — more complex than direct REST API calls.
- **Latency:** MCP adds a protocol layer. Direct REST calls via `httpx` are simpler and faster for the bot's agent loop.
- **No push capability:** MCP is a pull-only protocol. It cannot deliver webhook notifications.

**When we might reconsider:** If the Tango fleet standardizes on MCP for all external tool access (as suggested in ADR-013 for Slack), MeetScribe's MCP server could replace the direct REST client. The webhook receiver would remain regardless (MCP cannot replace push).

### 4. In-Memory Cache Only (No PostgreSQL, No File Cache)

**Rejected because:**
- **Data loss on restart:** In-memory caches are lost when the backend or bot restarts. Meeting metadata would need to be re-fetched from the API on every restart.
- **No queryability:** In-memory data structures cannot be queried with SQL or joined with other tables.
- **No persistence:** Historical webhook events are lost forever if not stored durably.

## Consequences

### Positive

1. **Real-time meeting awareness:** Discord bots know about new meeting notes within seconds of completion (via webhooks) instead of waiting for the next poll cycle.
2. **Grounded answers with citations:** Users can ask natural language questions about meetings and get RAG-powered answers with cited source sessions.
3. **Instant metadata queries:** The local cache enables instant responses for "list recent meetings" and similar queries without API round-trips.
4. **Proactive notifications:** The Discord bot posts rich embeds announcing new meeting notes, prompting users to ask follow-up questions.
5. **Durable storage:** PostgreSQL ensures webhook data survives restarts and is queryable for analytics.

### Negative

1. **New environment variables:** Five new env vars must be configured (`MEETSCRIBE_API_KEY`, `MEETSCRIBE_WEBHOOK_SECRET`, `MEETSCRIBE_ENABLED`, `MEETSCRIBE_API_URL`, `MEETSCRIBE_CACHE_PATH`).
2. **New PostgreSQL table:** Migration `005_meetscribe_sessions.sql` must be applied. The table grows with each meeting (mitigated by the table only storing metadata, not full transcripts).
3. **Webhook endpoint exposure:** The `POST /api/webhooks/meetscribe` endpoint must be reachable by MeetScribe. This requires Caddy reverse proxy configuration and potentially Cloudflare Tunnel routing.
4. **Shared secret management:** `MEETSCRIBE_WEBHOOK_SECRET` must be securely shared between MeetScribe and Tango. If compromised, an attacker could forge webhooks.
5. **Cache file management:** The local JSON cache file must be writable by the bot process and may grow large (mitigated by `MAX_CACHE_SESSIONS = 500` cap).
6. **API rate limits:** The MeetScribe API has rate limits. High-frequency querying (e.g., multiple users asking meeting questions simultaneously) could hit limits. The local cache reduces this risk for metadata queries.

### Neutral

1. **Two storage layers:** Session metadata is stored in both PostgreSQL (backend) and JSON file (bot cache). These are eventually consistent (webhook updates both; bootstrap syncs both) but not transactionally consistent.
2. **New modules:** Two new Python modules (`meetscribe_client.py`, `meetscribe_tools.py`) add ~750 lines of code. Both are well-documented and follow existing project patterns.
3. **Agent prompt expansion:** The `MEETSCRIBE_PROMPT_ADDITION` constant adds ~10 lines to the bot's system prompt, informing the LLM about available meeting tools.

## Implementation Notes

### Files Created/Modified

| File | Type | Purpose |
|---|---|---|
| `scripts/meetscribe_client.py` | New | `MeetScribeClient` (REST API client), `MeetScribeWebhookCache` (local cache), `verify_webhook_signature()`, format helpers |
| `scripts/meetscribe_tools.py` | New | Agent tool definitions (6 tools), `handle_meetscribe_tool()`, `get_meetscribe_client()` singleton, `MEETSCRIBE_PROMPT_ADDITION` |
| `scripts/webhook_handler.py` | Modified | Added `MeetScribeWebhookHandler` class with `POST /webhook/meetscribe` route |
| `backend/main.py` | Modified | Added `POST /api/webhooks/meetscribe` endpoint with HMAC verification and PostgreSQL storage |
| `backend/migrations/005_meetscribe_sessions.sql` | New | `tango.meetscribe_sessions` table for webhook session metadata |
| `backend/.env.example` | Modified | Added `MEETSCRIBE_WEBHOOK_SECRET` template |

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MEETSCRIBE_API_KEY` | Yes | — | Bearer token for MeetScribe API (prefix `ms_live_`) |
| `MEETSCRIBE_WEBHOOK_SECRET` | Yes | — | HMAC-SHA256 signing secret for webhook verification |
| `MEETSCRIBE_ENABLED` | No | `true` | Enable/disable the integration |
| `MEETSCRIBE_API_URL` | No | `https://meetscribe.jgeronimo.com/api` | Base URL for MeetScribe API |
| `MEETSCRIBE_CACHE_PATH` | No | `/opt/Project-Tango/data/meetscribe_cache.json` | Path to local cache JSON file |

### Services Affected

- `tango-backend.service` (port 8030) — new webhook endpoint, requires restart after deployment
- Discord bot services (e.g., `schubert-bot.service`) — new agent tools and webhook handler, requires restart
- No off-limits services are affected

## References

- MeetScribe Build Spec (wiki document ID: `431ca187-6df7-4cbc-93cf-09a3f680e4ab`)
- ADR-013: MCP-only no webhooks (this integration uses webhooks for push, API for pull — the opposite of ADR-013's Slack decision, because MeetScribe has no native MCP client wired in the bot fleet yet)
- ADR-015: Discord Bot Fleet UI/UX Enhancements (the `MeetScribeWebhookHandler` follows the same `add_routes_fn` pattern as the GitHub webhook handler)
- `scripts/meetscribe_client.py` — implementation
- `scripts/meetscribe_tools.py` — implementation
- `backend/main.py` lines 1313-1395 — webhook receiver endpoint
- `backend/migrations/005_meetscribe_sessions.sql` — database schema
