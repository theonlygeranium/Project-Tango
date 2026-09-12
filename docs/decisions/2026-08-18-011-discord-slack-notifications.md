# ADR-011: Discord-Slack Cross-Platform Notifications

**Date:** 2026-08-18
**Status:** Accepted
**Decided by:** Cursor Agent (via EdStratum Labs)

## Context

Project Tango operates a Discord bot fleet (Admiral Schubert, The Architect, Dr. Voss, The Proctor, Quartermaster, Cartographer, Dr. Cortex) that performs critical operational activities: deployments, health monitoring, performance analysis, and system management. However, team members and stakeholders often work primarily in Slack and may miss important Discord notifications.

The Discord bot fleet has rich operational context and real-time system visibility, while the team's primary communication hub is Slack. This creates a visibility gap where important system events may go unnoticed by team members who aren't actively monitoring Discord channels.

## Decision

Implement **unidirectional Discord → Slack notifications** using Slack incoming webhooks as Phase 1 of a multi-phase cross-platform integration strategy.

### Technical Implementation

1. **Shared notification module**: Create `scripts/slack_notifier.py` with a reusable `SlackNotifier` class
2. **Async webhook delivery**: Use `aiohttp` with `asyncio.create_task()` for non-blocking Slack notifications
3. **Slack Block Kit formatting**: Rich message formatting with color coding, emoji prefixes, metadata sections
4. **Three webhook targets**:
   - `SLACK_WEBHOOK_TANGO_OPS` → #tango-ops (deployments, health alerts, system operations)
   - `SLACK_WEBHOOK_TANGO_REPORTS` → #tango-reports (performance reports, analytics)
   - `SLACK_WEBHOOK_TANGO_DEV` → #tango-dev (development updates, debug info)
5. **Graceful degradation**: Webhooks are optional; bots function normally when not configured

### Integration Points

| Discord Bot | Activity | Notification Type | Target Channel |
|---|---|---|---|
| The Architect | `deploy_file` operations | Deployment alert | #tango-ops |
| The Architect | `restart_service` operations | Deployment alert | #tango-ops |
| Dr. Voss | Health escalations | Health alert | #tango-ops |
| The Proctor | Daily performance reports (8:00 UTC) | Performance report | #tango-reports |

## Rationale

### Why Webhooks (Not Slack Bot API)

- **Simplicity**: Incoming webhooks require zero OAuth flow, no bot installation, no permission management
- **Reliability**: Webhooks are fire-and-forget HTTP POST — no persistent connection or rate limit concerns
- **Security**: No long-lived Slack tokens in Discord bot processes
- **Ease of setup**: Team can create webhooks in 30 seconds via Slack UI

### Why Unidirectional (Phase 1)

- **Quick win**: Can be implemented and deployed in 1-2 hours
- **Low risk**: Discord bots remain authoritative; Slack is read-only notification sink
- **Validates use case**: Confirms Slack notifications provide value before investing in bi-directional sync
- **Foundation for future phases**: Establishes patterns and infrastructure for Phase 2+ (search, bridge, commands)

### Why Async Non-Blocking

- Discord bot operations (deployments, health checks, reports) must never be delayed by Slack webhook latency
- `asyncio.create_task()` fires notification in background; Discord operation continues immediately
- 5-second timeout prevents hung Slack webhooks from affecting bot responsiveness

## Alternatives Considered

### Option 1: Slack Bot with OAuth (Full API Access)

**Rejected because:**
- OAuth flow adds complexity (permission scopes, token refresh, error handling)
- Requires persistent Slack token storage in Discord bot `.env`
- Slack Bot API rate limits (20-100 req/min) more restrictive than webhooks (1 msg/sec per channel)
- Overkill for one-way notifications; useful only when we need bi-directional sync (Phase 3)

### Option 2: Dedicated Integration Service (Separate Process)

**Rejected because:**
- Adds deployment complexity (new systemd service, new failure mode)
- Requires message queue or pub/sub between Discord bots and integration service
- Over-engineering for Phase 1; may be justified in Phase 3 (message bridge)

### Option 3: Use Existing Slack Bot Token (WRITER Agent Playbook Bot)

**Rejected because:**
- WRITER Agent Playbook Bot is scoped for different functionality
- Would create coupling between Discord bot fleet and WRITER Agent infrastructure
- Webhook approach maintains clean separation of concerns

### Option 4: Discord Webhooks to Mirror Slack in Discord

**Rejected because:**
- Inverts the problem; team members still need to monitor Discord
- Does not solve visibility gap for Slack-primary users
- Discord → Slack is the correct direction for team workflow

## Consequences

### Positive

- **Immediate visibility**: Team sees Discord bot activities in Slack without switching contexts
- **Audit trail**: Slack serves as searchable archive of bot operations
- **Foundation for Phase 2+**: Establishes patterns for future cross-platform features
- **Zero risk**: Discord bots remain fully functional if Slack webhooks fail or aren't configured
- **Simple deployment**: Three environment variables in `.env`, no OAuth, no new services

### Negative

- **One-way only**: Slack users cannot yet interact with Discord bot fleet (addressed in Phase 5)
- **Manual webhook setup**: Admin must create three Slack webhooks and add to `.env` (acceptable tradeoff)
- **No message history sync**: Only new notifications forward to Slack (Phase 3 feature)
- **Webhook URL security**: Webhook URLs are secrets; must not be committed to git (already handled via `.env`)

### Future Phases (Not Implemented Yet)

- **Phase 2: Unified Knowledge Search** — Search both Discord and Slack from either platform
- **Phase 3: Bi-Directional Message Bridge** — Mirror conversations between Discord and Slack channels
- **Phase 4: Shared Persistent Memory** — Admiral Schubert's pgvector memory includes Slack conversations
- **Phase 5: Cross-Platform Commands** — Execute Discord FLEET commands from Slack (`/architect`, `/dr-voss`, etc.)

## References

- Wiki: https://wiki.edstratumlabs.ai/doc/discord-slack-integration-opportunities-2yY7IDXbeW
- Slack Incoming Webhooks: https://api.slack.com/messaging/webhooks
- Slack Block Kit: https://api.slack.com/block-kit
- Implementation: `/opt/Project-Tango/scripts/slack_notifier.py`
- AGENTS.md (Project Tango collaboration guide)
