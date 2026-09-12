# MeetScribe → Discord Bot Context Integration

## Overview

The MeetScribe integration connects MeetScribe's Meeting Corpus REST API to Project Tango's Discord bot fleet, enabling Discord bots to answer questions about meetings, search through notes and transcripts, and proactively notify users when new meeting notes become available.

The integration uses a **hybrid push + pull architecture**:

- **Push:** MeetScribe fires `notes.completed` webhooks to the Tango backend, which stores session metadata in PostgreSQL and forwards events to the Discord bot's webhook handler. The bot posts rich Discord embeds announcing new notes and caches metadata locally.
- **Pull:** Discord bots use the MeetScribe REST API (`/v1/sessions/query`) for RAG question answering when users ask about meetings. Six agent tools provide full query, search, list, notes, transcript, and status capabilities.

A local session metadata cache (`MeetScribeWebhookCache`) bridges the push and pull layers, enabling instant responses for common metadata queries without API round-trips.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Schubert Nexus                                   │
│                                                                         │
│  ┌──────────────┐         ┌──────────────────────┐                      │
│  │  MeetScribe   │         │  Tango Backend       │                      │
│  │  (port 8010)  │         │  (port 8030)         │                      │
│  │               │  POST   │                      │                      │
│  │  Meeting      │  webhook │  /api/webhooks/     │                      │
│  │  Corpus API   │────────▶│  meetscribe          │                      │
│  │  + RAG        │         │                      │                      │
│  │  + Vector     │         │  HMAC-SHA256 verify  │                      │
│  │  Memory       │         │  PostgreSQL storage  │                      │
│  └──────┬───────┘         │  tango.meetscribe_   │                      │
│         │                  │  sessions            │                      │
│         │                  └──────────────────────┘                      │
│         │                          │                                    │
│         │ REST API                 │ Forward webhook                   │
│         │ (pull)                   ▼                                    │
│         │                  ┌──────────────────────┐                      │
│         │                  │ Discord Bot          │                      │
│         │                  │ (aiohttp server)     │                      │
│         │                  │                      │                      │
│         │   GET /v1/       │ /webhook/meetscribe  │                      │
│         ├─────────────────▶│  (port 8095)         │                      │
│         │   POST /v1/      │                      │                      │
│         ├─────────────────▶│ MeetScribeWebhook    │                      │
│         │   sessions/query │ Cache (JSON file)    │                      │
│         │                  │                      │                      │
│         │                  │ 6 Agent Tools:       │                      │
│         │                  │  query_meetings      │                      │
│         │                  │  search_meetings     │                      │
│         │                  │  list_recent_meetings│                      │
│         │                  │  get_meeting_notes   │                      │
│         │                  │  get_meeting_        │                      │
│         │                  │   transcript         │                      │
│         │                  │  get_meetscribe_     │                      │
│         │                  │   status             │                      │
│         │                  └──────────┬───────────┘                      │
│         │                             │                                   │
│         │                             ▼                                   │
│         │                  ┌──────────────────────┐                      │
│         │                  │  Discord Channel     │                      │
│         │                  │  (rich embeds)      │                      │
│         │                  └──────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Meeting completes in MeetScribe** → MeetScribe processes audio, generates AI summary, action items, key decisions, and indexes the transcript in vector memory.
2. **MeetScribe fires webhook** → `POST /api/webhooks/meetscribe` to Tango backend with `notes.completed` event, signed with HMAC-SHA256.
3. **Tango backend verifies and stores** → Verifies signature, upserts session metadata into `tango.meetscribe_sessions` PostgreSQL table.
4. **Discord bot receives forwarded webhook** → `POST /webhook/meetscribe` on the bot's local aiohttp server. Verifies signature, caches metadata in local JSON file, posts rich Discord embed.
5. **User asks about meetings in Discord** → Bot's LLM calls one of the 6 MeetScribe agent tools. `MeetScribeClient` makes a REST API call to MeetScribe. Result is formatted and returned to the LLM, which generates a natural language response.

## Configuration

### Environment Variables

All variables must be set in `/opt/Project-Tango/backend/.env` (for the Tango backend) and `/opt/Project-Tango/scripts/.env` (for the Discord bot).

| Variable | Required | Default | Description |
|---|---|---|---|
| `MEETSCRIBE_API_KEY` | Yes | — | Bearer token for MeetScribe API authentication. Must have `ms_live_` prefix. |
| `MEETSCRIBE_WEBHOOK_SECRET` | Yes | — | HMAC-SHA256 signing secret shared between MeetScribe and Tango for webhook verification. |
| `MEETSCRIBE_ENABLED` | No | `true` | Master switch for the integration. Set to `false` to disable all MeetScribe features. |
| `MEETSCRIBE_API_URL` | No | `https://meetscribe.jgeronimo.com/api` | Base URL for the MeetScribe REST API. |
| `MEETSCRIBE_CACHE_PATH` | No | `/opt/Project-Tango/data/meetscribe_cache.json` | Filesystem path for the local session metadata cache. |

### `.env.example` Entry

```bash
# MeetScribe webhook receiver (HMAC-SHA256 secret shared with MeetScribe)
MEETSCRIBE_WEBHOOK_SECRET=
```

## API Endpoints

### Tango Backend Endpoints

#### `POST /api/webhooks/meetscribe`

Receives `notes.completed` webhooks from MeetScribe.

**Headers:**
- `X-MeetScribe-Signature`: `sha256=<hex_digest>` (HMAC-SHA256 signature of the raw body)
- `Content-Type`: `application/json`

**Request Body:**
```json
{
  "event": "notes.completed",
  "data": {
    "session_id": 42,
    "title": "Weekly Engineering Sync",
    "status": "completed",
    "started_at": "2026-08-19T14:00:00Z",
    "duration_seconds": 3600,
    "summary": "Discussed Q3 roadmap priorities...",
    "action_items": ["Deploy v2.0 by Friday", "Review PR #123"],
    "key_decisions": ["Adopt microservices architecture"]
  }
}
```

**Responses:**
- `200 {"status": "received"}` — Webhook processed (or ignored if not `notes.completed`)
- `401` — Signature verification failed or missing signature header
- `503` — `MEETSCRIBE_WEBHOOK_SECRET` not configured

**Note:** The endpoint returns 200 even on database failure to prevent MeetScribe retry storms. Database errors are logged.

### Discord Bot Endpoints

#### `POST /webhook/meetscribe`

Receives forwarded MeetScribe webhooks on the bot's local aiohttp server (port 8095).

**Headers:**
- `X-MeetScribe-Signature`: `sha256=<hex_digest>`

**Response:** `200 {"status": "received"}`

Side effects: Caches session metadata in local JSON file, posts rich Discord embed to configured channel.

#### `GET /webhook/health`

Health check for the webhook server. Returns `200 {"status": "ok", "service": "schubert-webhook"}`.

### MeetScribe API Endpoints

The `MeetScribeClient` class calls the following MeetScribe REST API endpoints:

| Method | Path | Purpose | Tool |
|---|---|---|---|
| `POST` | `/v1/sessions/query` | RAG question answering with cited sources | `query_meetings` |
| `POST` | `/v1/sessions/search` | Full-text search across titles, notes, transcripts | `search_meetings` |
| `GET` | `/v1/sessions` | List sessions with optional date/status filters | `list_recent_meetings` |
| `GET` | `/v1/sessions/{id}` | Fetch session metadata | — |
| `GET` | `/v1/sessions/{id}/notes` | Fetch AI summary, action items, key decisions | `get_meeting_notes` |
| `GET` | `/v1/sessions/{id}/transcript` | Fetch full transcript segments | `get_meeting_transcript` |
| `GET` | `/v1/sessions/{id}/export` | Export session as md/txt/srt/vtt/pdf/docx | — |
| `GET` | `/v1/memory/status` | Check vector memory index status | `get_meetscribe_status` |

All MeetScribe API requests require `Authorization: Bearer <MEETSCRIBE_API_KEY>` header.

## Agent Tools

Six agent tools are defined in `scripts/meetscribe_tools.py` and registered with the Discord bot's LLM for function calling. All tools are async and return formatted markdown strings.

### 1. `query_meetings`

RAG question answering across the meeting corpus. Asks a natural language question and gets a grounded answer with cited source sessions.

**Parameters:**
- `question` (string, required) — Natural language question about meetings
- `limit` (integer, optional, default 5) — Maximum number of source sessions to consider

**Example:** "What was decided about the Q3 roadmap?"

**Returns:** Answer text with cited sources (session title, date, relevance score, session ID).

### 2. `search_meetings`

Full-text search across meeting titles, notes, and transcripts. Use for keyword searches when looking for specific terms or topics.

**Parameters:**
- `query` (string, required) — Search query (keywords or phrases)
- `limit` (integer, optional, default 10) — Maximum number of results

**Example:** "budget", "Q3 roadmap", "action item: deploy"

**Returns:** List of matching sessions with title, date, session ID, and status.

### 3. `list_recent_meetings`

List recent meeting sessions. Use to show the user what meetings are available.

**Parameters:**
- `limit` (integer, optional, default 10) — Maximum number of sessions to return
- `status` (string, optional) — Filter by status (e.g., "completed", "processing")

**Returns:** List of sessions with title, date, session ID, and status.

### 4. `get_meeting_notes`

Fetch AI summary, action items, and key decisions for a specific meeting.

**Parameters:**
- `session_id` (integer, required) — MeetScribe session ID

**Returns:** Formatted notes with summary, action items (checkbox list), and key decisions.

### 5. `get_meeting_transcript`

Fetch the full transcript for a specific meeting. Returns transcript segments with speaker labels and timestamps.

**Parameters:**
- `session_id` (integer, required) — MeetScribe session ID

**Returns:** Transcript segments formatted as `[timestamp] **Speaker:** text` (max 50 segments).

### 6. `get_meetscribe_status`

Check the MeetScribe memory index status. Returns the number of indexed chunks and sessions.

**Parameters:** None

**Returns:** Indexed chunk count, session count, and index status.

### System Prompt Addition

The `MEETSCRIBE_PROMPT_ADDITION` constant is appended to the bot's system prompt to inform the LLM about available meeting tools:

```
### MeetScribe Meeting Integration
You have access to MeetScribe tools that let you query meeting notes and transcripts:
- Use `query_meetings` when the user asks about what was discussed/decided in meetings
- Use `search_meetings` for keyword searches across meeting content
- Use `list_recent_meetings` to show recent meetings
- Use `get_meeting_notes` to fetch detailed notes for a specific meeting
- Use `get_meeting_transcript` to fetch the full transcript of a meeting
- Use `get_meetscribe_status` to check the MeetScribe memory index

When a user asks about work meetings, projects discussed in meetings, or decisions made in meetings,
use these tools to provide grounded answers with cited sources.
```

## Webhook Payload Format

### `notes.completed` Event

```json
{
  "event": "notes.completed",
  "data": {
    "session_id": 42,
    "title": "Weekly Engineering Sync",
    "status": "completed",
    "started_at": "2026-08-19T14:00:00Z",
    "duration_seconds": 3600,
    "summary": "Discussed Q3 roadmap priorities, reviewed deployment pipeline, and assigned action items for the migration.",
    "action_items": [
      "Deploy v2.0 by Friday",
      "Review PR #123",
      "Update architecture documentation"
    ],
    "key_decisions": [
      "Adopt microservices architecture",
      "Move to weekly release cadence"
    ]
  }
}
```

### Signature Verification

Webhooks are signed with HMAC-SHA256 using the `MEETSCRIBE_WEBHOOK_SECRET`. The signature is sent in the `X-MeetScribe-Signature` header as:

```
X-MeetScribe-Signature: sha256=<hex_digest>
```

Verification is performed using `hmac.compare_digest()` for constant-time comparison to prevent timing attacks.

## Setup Guide

### Prerequisites

- MeetScribe deployed and running on Schubert Nexus (port 8010)
- Tango backend running (port 8030)
- Discord bot running with aiohttp webhook server (port 8095)
- PostgreSQL 18 with `tango` schema

### Step 1: Apply Database Migration

```bash
cd /opt/Project-Tango
sudo -u z121532 git pull
psql -U tango -d tango -f backend/migrations/005_meetscribe_sessions.sql
```

Verify the table was created:

```bash
psql -U tango -d tango -c "\d tango.meetscribe_sessions"
```

### Step 2: Configure Environment Variables

Add the following to `/opt/Project-Tango/backend/.env`:

```bash
MEETSCRIBE_API_KEY=ms_live_your_api_key_here
MEETSCRIBE_WEBHOOK_SECRET=your_hmac_secret_here
MEETSCRIBE_ENABLED=true
MEETSCRIBE_API_URL=https://meetscribe.jgeronimo.com/api
MEETSCRIBE_CACHE_PATH=/opt/Project-Tango/data/meetscribe_cache.json
```

Add the same variables to `/opt/Project-Tango/scripts/.env` for the Discord bot.

### Step 3: Configure MeetScribe Webhook

In MeetScribe's settings, configure the webhook target URL:

```
https://tango-api.schubert.life/api/webhooks/meetscribe
```

Set the webhook secret to match `MEETSCRIBE_WEBHOOK_SECRET`.

### Step 4: Restart Services

```bash
sudo systemctl restart tango-backend
sudo systemctl restart schubert-bot
```

### Step 5: Verify

Check the backend health:

```bash
curl -s https://tango-api.schubert.life/healthz
```

Check the webhook endpoint is registered:

```bash
curl -s -X POST https://tango-api.schubert.life/api/webhooks/meetscribe \
  -H "Content-Type: application/json" \
  -d '{"event":"ping"}'
# Should return {"status":"received"}
```

Check the Discord bot webhook handler:

```bash
curl -s http://localhost:8095/webhook/health
# Should return {"status":"ok","service":"schubert-webhook"}
```

Check the local cache was bootstrapped:

```bash
cat /opt/Project-Tango/data/meetscribe_cache.json | python3 -m json.tool | head -20
```

## Security Considerations

### HMAC-SHA256 Webhook Verification

All webhook endpoints verify the HMAC-SHA256 signature from the `X-MeetScribe-Signature` header before processing the payload. The verification uses `hmac.compare_digest()` for constant-time comparison, preventing timing attacks. If the secret is not configured, the backend returns 503 and the bot returns 401, ensuring no unauthenticated webhooks are processed.

### API Key Scoping

The `MEETSCRIBE_API_KEY` is a Bearer token with the `ms_live_` prefix. It should be scoped to read-only access (query, search, list, get) and should not have write or delete permissions. The key is stored in `.env` files and never committed to the repository.

### SSRF Prevention

The `MeetScribeClient` uses a configurable base URL (`MEETSCRIBE_API_URL`) that defaults to `https://meetscribe.jgeronimo.com/api`. The client does not follow redirects and does not allow user-controlled URLs in API calls. Webhook payloads are parsed but session IDs are validated as integers before use in API paths, preventing path traversal.

### Secret Management

- `MEETSCRIBE_WEBHOOK_SECRET` and `MEETSCRIBE_API_KEY` are stored in `.env` files, not committed to source
- `.env.example` contains only the variable name with an empty value
- Secrets are loaded at startup and held in memory; they are not logged

## Troubleshooting

### Webhook Signature Verification Fails

**Symptom:** Backend logs show "MeetScribe webhook signature verification failed" or bot logs show "MeetScribe webhook signature verification failed".

**Causes:**
1. `MEETSCRIBE_WEBHOOK_SECRET` differs between MeetScribe and Tango
2. The webhook secret is not set in `.env`
3. The webhook payload was modified in transit (proxy issue)

**Fix:**
```bash
# Verify the secret is set
grep MEETSCRIBE_WEBHOOK_SECRET /opt/Project-Tango/backend/.env
grep MEETSCRIBE_WEBHOOK_SECRET /opt/Project-Tango/scripts/.env

# Ensure the same secret is configured in MeetScribe's webhook settings
# Restart services after updating .env
sudo systemctl restart tango-backend
sudo systemctl restart schubert-bot
```

### Bot Tools Not Available

**Symptom:** Discord bot does not use MeetScribe tools when asked about meetings.

**Causes:**
1. `MEETSCRIBE_ENABLED` is set to `false`
2. `MEETSCRIBE_API_KEY` is not set
3. `meetscribe_tools.py` not imported in the bot script
4. `get_meetscribe_client()` returns `None` (integration disabled or unconfigured)

**Fix:**
```bash
# Check if integration is enabled
grep MEETSCRIBE_ENABLED /opt/Project-Tango/scripts/.env
grep MEETSCRIBE_API_KEY /opt/Project-Tango/scripts/.env

# Check bot logs for MeetScribe initialization
sudo journalctl -u schubert-bot -n 50 --no-pager | grep -i meetscribe
```

### Local Cache Not Populating

**Symptom:** `meetscribe_cache.json` is empty or missing.

**Causes:**
1. Bot has not received any webhooks yet
2. Bootstrap API call failed (MeetScribe API unreachable or API key invalid)
3. Cache path is not writable

**Fix:**
```bash
# Check if cache file exists
ls -la /opt/Project-Tango/data/meetscribe_cache.json

# Check directory permissions
ls -ld /opt/Project-Tango/data/

# Check bootstrap in logs
sudo journalctl -u schubert-bot -n 100 --no-pager | grep -i "cache bootstrap"

# Manually trigger bootstrap by restarting the bot
sudo systemctl restart schubert-bot
```

### Database Insert Fails

**Symptom:** Backend logs show "MeetScribe webhook DB insert failed".

**Causes:**
1. Migration `005` not applied
2. PostgreSQL connection pool exhausted
3. JSON serialization error in action_items or key_decisions

**Fix:**
```bash
# Verify table exists
psql -U tango -d tango -c "SELECT * FROM tango.meetscribe_sessions LIMIT 1;"

# Apply migration if table is missing
psql -U tango -d tango -f /opt/Project-Tango/backend/migrations/005_meetscribe_sessions.sql

# Check PostgreSQL is running
systemctl is-active postgresql@18-main
```

### MeetScribe API Unreachable

**Symptom:** Tool calls return "MeetScribe API request error" or timeout.

**Causes:**
1. MeetScribe service is down
2. `MEETSCRIBE_API_URL` is incorrect
3. Network connectivity issue
4. API key is invalid or expired

**Fix:**
```bash
# Check MeetScribe is running
systemctl is-active meetscribe

# Test API connectivity
curl -s -H "Authorization: Bearer $MEETSCRIBE_API_KEY" \
  "$MEETSCRIBE_API_URL/v1/memory/status"

# Check API URL configuration
grep MEETSCRIBE_API_URL /opt/Project-Tango/scripts/.env
```

## Related Documentation

- [ADR-016: MeetScribe → Discord Bot Context Integration](decisions/2026-08-19-016-meetscribe-discord-context-integration.md)
- [ADR-013: MCP-only no webhooks](decisions/2026-08-19-013-mcp-only-no-webhooks.md)
- [ADR-015: Discord Bot Fleet UI/UX Enhancements](decisions/2026-08-19-015-discord-bot-ui-ux-enhancements.md)
- `scripts/meetscribe_client.py` — MeetScribeClient and MeetScribeWebhookCache implementation
- `scripts/meetscribe_tools.py` — Agent tool definitions and handlers
- `backend/main.py` — Webhook receiver endpoint (lines 1313-1395)
- `backend/migrations/005_meetscribe_sessions.sql` — Database schema
