# ADR-014: WRITER Agent Playbook Integration

**Date:** 2026-08-19  
**Status:** Accepted  
**Decided by:** Cursor Agent (via user request)

## Context

Project Tango operates a Discord bot fleet that provides AI-powered assistance to users. The fleet includes specialized bots like The Architect (development & deployment), Dr. Voss (health monitoring), and The Proctor (performance optimization).

Meanwhile, WRITER Agent operates sophisticated multi-step playbooks that can perform complex diagnostic and operational tasks. One such playbook, "Cursor LiteLLM Session Provisioning," provides comprehensive diagnostics for the Cursor/LiteLLM/WRITER BYOK integration running on Schubert Nexus.

**The Problem:** Users in Discord may encounter issues that require WRITER playbook diagnostics, but there was no way to invoke playbooks from Discord and receive results back. This created a context-switching burden (Discord → WRITER app → back to Discord) and prevented Discord bots from leveraging WRITER's advanced capabilities.

**The Opportunity:** Enable Discord bots to invoke WRITER playbooks via webhook, auto-detect when playbooks should run, and post structured results back to Discord.

## Decision

Implement **bidirectional Discord ↔ WRITER Agent integration** using webhook-based playbook invocation with polling for completion.

### Technical Architecture

**Components:**

1. **`writer_playbook_client.py`** — Async Python client for WRITER webhooks
   - Triggers playbooks via POST to `https://app.writer.com/webhook/triggers/playbook/{playbook_id}`
   - Polls `/threads/{thread_id}/status` every 10 seconds until completion
   - Downloads deliverables from `/threads/{thread_id}/deliverables`
   - Handles timeouts (default 30 minutes), retries, and exponential backoff

2. **`writer_integration.py`** — Discord bot integration layer
   - Auto-detection: Regex patterns match user messages to playbooks
   - Discord UI: Progress updates, embeds, status messages
   - Result formatting: Converts WRITER deliverables to Discord-friendly format
   - Convenience functions: `should_invoke_playbook()`, `invoke_playbook_from_discord()`

3. **The Architect bot integration**
   - Message handler checks for playbook triggers before normal processing
   - Auto-invokes playbooks when patterns match
   - Posts results with rich embeds (status, execution time, deliverables)
   - Graceful degradation: If playbook fails, continues to normal message handling

4. **FastAPI webhook callback endpoint** (optional, future use)
   - `/api/discord/writer-callback` — receives completion notifications from WRITER
   - Uses `asyncio.Future` to resolve pending playbook results
   - Currently not used (polling model preferred for simplicity)

### Playbook Configuration

Playbooks are configured in `writer_integration.py` with:

- **Name:** Human-readable display name
- **Webhook URL:** WRITER playbook webhook endpoint
- **API Key:** Bearer token from environment (`WRITER_PLAYBOOK_API_KEY`)
- **Description:** Brief description for documentation
- **Triggers:** List of regex patterns for auto-detection
- **Timeout:** Maximum execution time in seconds

**Example:**

```python
PLAYBOOKS = {
    "cursor-litellm": {
        "name": "Cursor LiteLLM Session Provisioning",
        "webhook_url": "https://app.writer.com/webhook/triggers/playbook/1574c302-b407-4553-a2f6-6e42291e805c",
        "api_key": os.getenv("WRITER_PLAYBOOK_API_KEY", ""),
        "description": "Provision and diagnose Cursor LiteLLM BYOK integration",
        "triggers": [
            r"\bcursor.*litellm\b",
            r"\blitellm.*error\b",
            r"\bcursor.*agent.*error\b",
            # ... more patterns ...
        ],
        "timeout": 1800,  # 30 minutes
    }
}
```

### Auto-Detection Flow

```
1. User sends message to The Architect
2. Message handler calls handle_architect_message()
3. Iterate through all playbooks, check trigger patterns
4. If match found:
   a. Send initial status message to Discord
   b. Invoke WRITER playbook via webhook
   c. Poll status every 10 seconds
   d. Update Discord message with progress
   e. Download deliverables when completed
   f. Post final result with embed
   g. Return True (message handled)
5. If no match, return False (normal bot processing)
```

### Authentication

- **API Key:** Stored in `.env` as `WRITER_PLAYBOOK_API_KEY`
- **Transport:** HTTPS only (app.writer.com)
- **Authorization:** Bearer token in `Authorization` header
- **Scoping:** API key is scoped to webhook invocations only (not full WRITER API)

## Rationale

### Why Polling (Not Callbacks)

**Polling Pros:**
- Simpler implementation (no public webhook endpoint required)
- No firewall/routing configuration needed
- Works with Cloudflare Tunnel without additional setup
- Stateless (no callback ID management)
- More reliable (no webhook delivery failures)

**Polling Cons:**
- Higher latency (10-60 second delay vs instant callback)
- More API calls (1 per poll interval vs 1 callback)

**Decision:** Polling is preferred for Phase 1 because:
1. Simplicity is more valuable than 10-second faster responses
2. WRITER playbooks take 60-180 seconds anyway (10s latency is < 10% overhead)
3. Can add callbacks later if polling proves insufficient

### Why Auto-Detection (Not Commands)

**Auto-Detection Pros:**
- Natural language interaction ("check cursor litellm" works)
- No need to learn command syntax
- Reduces cognitive load on users
- More AI-like behavior

**Auto-Detection Cons:**
- Risk of false positives (invoking playbook when not needed)
- Harder to debug (why did it trigger?)
- Requires careful regex pattern tuning

**Decision:** Auto-detection is preferred because:
1. Trigger patterns can be made very specific (low false positive rate)
2. Users can always use explicit commands if auto-detection fails
3. Matches the "AI assistant" persona of the Discord bot fleet
4. Can be disabled per-playbook if problematic

### Why The Architect (Not All Bots)

**Decision:** Phase 1 integration is only in The Architect because:
1. The Architect is the "developer/diagnostic" bot (natural fit)
2. Cursor LiteLLM playbook is development-focused
3. Limits blast radius if integration has issues
4. Can expand to other bots (Admiral, Dr. Voss, Proctor) in Phase 2

### Why Environment Variable (Not Hardcoded)

**Decision:** API key is in `.env` (not hardcoded in `writer_integration.py`) because:
1. Security: Prevents accidental git commits of secrets
2. Flexibility: Can be changed without code changes
3. Consistency: Matches existing patterns (all secrets in `.env`)
4. Deployment: `/opt/Project-Tango/.env` is mode 600, owner z121532

## Alternatives Considered

### Option 1: Synchronous HTTP Request (No Polling)

**Approach:** Invoke playbook and wait for 200 response with deliverables.

**Rejected because:**
- WRITER playbooks take 60-180 seconds (may time out)
- Discord interactions have 15-minute timeout (may exceed)
- No progress updates (user sees nothing for 2-3 minutes)

### Option 2: Discord Slash Commands

**Approach:** `/run-playbook cursor-litellm`

**Rejected because:**
- Requires slash command registration (more setup)
- Less natural than auto-detection
- Doesn't match AI assistant persona
- Can still be added later if desired

### Option 3: Webhook Callbacks with FastAPI

**Approach:** WRITER posts results to `/api/discord/writer-callback` when complete.

**Rejected for Phase 1 because:**
- Requires public webhook endpoint (Caddy config, Cloudflare Tunnel)
- More complex error handling (callback delivery failures)
- Need callback ID management (security, state tracking)
- Polling is "good enough" for Phase 1

**Kept as future enhancement:** FastAPI endpoint is implemented (but unused) for Phase 2.

### Option 4: WRITER SDK (Not Webhook)

**Approach:** Use official WRITER SDK instead of raw webhooks.

**Rejected because:**
- WRITER webhook API is the official SDK for playbook invocation
- No higher-level Python SDK available
- Custom client is simple (< 300 lines) and maintainable

## Consequences

### Positive

- **Unified experience:** Users can diagnose issues without leaving Discord
- **Faster diagnostics:** WRITER playbooks automate complex multi-step diagnostics
- **Better context:** The Architect can understand when playbooks are needed
- **Extensible:** Easy to add more playbooks in future
- **Foundation for automation:** Bots can invoke playbooks autonomously (not just on user request)
- **Audit trail:** Discord messages provide history of playbook invocations

### Negative

- **New dependency:** Discord bots now depend on WRITER playbook availability
- **Error handling:** If WRITER is down, playbooks fail (graceful degradation handles this)
- **Latency:** Polling adds 10-60 second delay compared to callbacks
- **API costs:** Polling creates more API calls (1 per 10 seconds while running)
- **Maintenance:** Need to keep trigger patterns updated as playbooks evolve

### Operational Impact

- **New environment variable:** `WRITER_PLAYBOOK_API_KEY` must be configured
- **Service restart:** The Architect must be restarted after adding new playbooks
- **Monitoring:** Should track playbook invocation success rate and latency
- **Documentation:** Users need to understand auto-detection patterns

### Security Considerations

- **API key exposure:** Mitigated by storing in `.env` (mode 600)
- **Playbook abuse:** Mitigated by admin-only channels (only trusted users)
- **Data leakage:** WRITER playbooks may expose credentials/configs (reviewed case-by-case)
- **Webhook hijacking:** Mitigated by HTTPS + Bearer token auth

### Performance Impact

- **The Architect:** Minimal (regex matching is fast, playbook invocation is async)
- **WRITER API:** 1 trigger + N status polls + 1 deliverable download per playbook
- **Discord API:** 1-3 messages per playbook (initial, updates, final result)

## Future Phases

### Phase 2: Callback-Based Invocation

- Implement `/api/discord/writer-callback` webhook endpoint
- WRITER posts completion to callback URL
- Faster responses (no polling delay)
- Requires public endpoint configuration

### Phase 3: Fleet-Wide Integration

- Expand to Admiral Schubert, Dr. Voss, The Proctor
- Each bot can invoke playbooks relevant to their specialization
- Example: Dr. Voss auto-invokes health diagnostic playbooks

### Phase 4: Interactive Playbooks

- Handle `awaiting_user_response` status
- Post Discord buttons/modals for user input
- Resume playbook execution with user response

### Phase 5: Playbook Chaining

- One playbook can trigger another
- Example: Diagnostic playbook → Auto-remediation playbook
- Orchestration logic in Discord bot or WRITER

### Phase 6: Persistent History

- Store playbook results in PostgreSQL
- Query past invocations
- Compare diagnostics over time
- Analytics dashboard

## References

- **WRITER Playbook Documentation:** `/opt/Project-Tango/docs/WRITER_PLAYBOOK_INTEGRATION.md`
- **Implementation:** `/opt/Project-Tango/scripts/writer_playbook_client.py`
- **Integration Layer:** `/opt/Project-Tango/scripts/writer_integration.py`
- **The Architect Bot:** `/opt/Project-Tango/scripts/architect-bot.py` (line ~4020)
- **FastAPI Endpoint:** `/opt/Project-Tango/backend/main.py` (line ~1258)
- **WRITER Webhook API:** https://dev.writer.com/api-guides/webhooks
- **Cursor LiteLLM Playbook:** https://app.writer.com/playbooks/1574c302-b407-4553-a2f6-6e42291e805c

---

**Approved by:** User (Jeff Geronimo)  
**Implemented by:** Cursor Agent  
**Date:** 2026-08-19
