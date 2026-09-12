# WRITER Agent Playbook Integration — Discord Bot Fleet

**Date:** 2026-08-19  
**Status:** Active  
**Owner:** EdStratum Labs

---

## Overview

The Discord bot fleet (specifically **The Architect**) can now invoke **WRITER Agent Playbooks** via webhook and receive structured responses back to Discord. This enables Discord users to trigger complex, multi-step WRITER workflows without leaving Discord.

### Use Case

**Example:** User asks The Architect: _"Is Cursor LiteLLM working?"_

The Architect auto-detects this as a Cursor LiteLLM issue, invokes the WRITER "Cursor LiteLLM Session Provisioning" playbook, waits for completion, and posts the full diagnostic report back to Discord.

---

## Architecture

```
Discord User
    ↓
The Architect (Discord Bot)
    ↓ (webhook POST)
WRITER Playbook (app.writer.com)
    ↓ (polls status every 10s)
The Architect (polls for completion)
    ↓ (downloads deliverables)
The Architect (formats and posts to Discord)
    ↓
Discord User
```

### Components

1. **`writer_playbook_client.py`** — Async Python client for WRITER playbook webhooks
   - Triggers playbooks via POST
   - Polls status until completion
   - Downloads deliverables
   - Handles timeouts and errors

2. **`writer_integration.py`** — Discord bot integration layer
   - Auto-detects when to invoke playbooks based on message content
   - Manages Discord UI (progress updates, embeds, formatting)
   - Provides convenience functions for bot developers

3. **`architect-bot.py`** — The Architect integration
   - Checks every message for playbook triggers
   - Invokes playbooks when patterns match
   - Posts results back to Discord with rich formatting

4. **FastAPI webhook endpoint** (optional, for future use)
   - `/api/discord/writer-callback` — receives completion callbacks from WRITER
   - Currently not used (polling model preferred for simplicity)

---

## Available Playbooks

### 1. Cursor LiteLLM Session Provisioning

**Name:** `cursor-litellm`  
**Webhook URL:** `https://app.writer.com/webhook/triggers/playbook/1574c302-b407-4553-a2f6-6e42291e805c`  
**Description:** Provision and diagnose Cursor LiteLLM BYOK integration  
**Timeout:** 30 minutes  
**Inputs:** None (reads session context file attached to playbook)

**Auto-Trigger Patterns:**
- "cursor litellm"
- "litellm error"
- "cursor agent error"
- "cursor byok"
- "polyglot litellm"
- "cursor not working"
- "litellm service"
- "cursor models missing"
- "run cursor litellm playbook"
- "diagnose cursor"
- "check cursor litellm"

**What It Does:**
1. Reads full Cursor LiteLLM BYOK session context (13 patches, credentials, config)
2. Verifies LiteLLM service is active on Schubert V2
3. Checks model count (should be 55 models)
4. Fetches EL Wiki documentation revision
5. Checks recent LiteLLM logs for errors
6. Attempts auto-remediation if issues found
7. Returns status summary with diagnostics

---

## Configuration

### Environment Variables

Add to `/opt/Project-Tango/.env`:

```bash
# WRITER Agent Playbook Integration
WRITER_PLAYBOOK_API_KEY=4b7ddcec2fca099542b6fb888334cfd83683465dcd60e77d2c7678ec47e6affd
```

**Security Note:** This API key is a secret. Never commit to git.

### Verifying Configuration

```bash
# Check env var is set
grep WRITER_PLAYBOOK_API_KEY /opt/Project-Tango/.env

# Test the client directly
cd /opt/Project-Tango/scripts
python3 writer_playbook_client.py
```

---

## Usage

### From Discord (Auto-Detection)

Simply mention keywords that match a playbook's trigger patterns:

```
@The Architect is Cursor LiteLLM working?
@The Architect check cursor litellm status
@The Architect run cursor litellm playbook
```

The Architect will:
1. Auto-detect the playbook trigger
2. Send initial status message: "⏳ Invoking WRITER Agent Playbook..."
3. Update status every 10 seconds with progress
4. Post final result with embed (status, deliverables, execution time)

### From Python (Manual Invocation)

```python
from writer_integration import invoke_playbook_from_discord

result = await invoke_playbook_from_discord(
    playbook_name="cursor-litellm",
    discord_channel=message.channel,
    user_message=message.content,
    progress_updates=True
)

if result.success:
    print(f"Playbook completed in {result.execution_time_seconds}s")
    print(f"Deliverables: {result.deliverables}")
else:
    print(f"Playbook failed: {result.error_message}")
```

### From Python (Direct Client)

```python
from writer_playbook_client import invoke_writer_playbook

result = await invoke_writer_playbook(
    webhook_url="https://app.writer.com/webhook/triggers/playbook/...",
    api_key="your-api-key",
    inputs=[],
    timeout=1800
)
```

---

## Adding New Playbooks

### Step 1: Export Playbook from WRITER

1. Go to https://app.writer.com/playbooks/
2. Open the playbook
3. Click "Export" → Download `manifest.json`

### Step 2: Add to Configuration

Edit `/opt/Project-Tango/scripts/writer_integration.py`:

```python
PLAYBOOKS = {
    # ... existing playbooks ...
    
    "your-playbook-name": {
        "name": "Your Playbook Display Name",
        "webhook_url": "https://app.writer.com/webhook/triggers/playbook/YOUR-PLAYBOOK-ID",
        "api_key": os.getenv("WRITER_PLAYBOOK_API_KEY", ""),
        "description": "Brief description of what this playbook does",
        "triggers": [
            r"\byour.*trigger.*pattern\b",
            r"\banother.*trigger\b",
            # Add more regex patterns for auto-detection
        ],
        "timeout": 1800,  # seconds
    }
}
```

### Step 3: Test Auto-Detection

```python
from writer_integration import should_invoke_playbook

# Test your trigger patterns
test_messages = [
    "This should trigger the playbook",
    "This should not",
]

for msg in test_messages:
    detected = should_invoke_playbook(msg, "your-playbook-name")
    print(f"{'✓' if detected else '✗'} {msg}")
```

### Step 4: Restart The Architect

```bash
sudo systemctl restart schubert-architect.service
```

---

## Troubleshooting

### Issue: "WRITER playbook API key not configured"

**Solution:** Add `WRITER_PLAYBOOK_API_KEY` to `/opt/Project-Tango/.env`

```bash
echo "WRITER_PLAYBOOK_API_KEY=your-key-here" >> /opt/Project-Tango/.env
sudo systemctl restart schubert-architect.service
```

### Issue: Playbook times out

**Symptoms:** "⚠️ Timeout: Playbook exceeded XXXs limit"

**Solutions:**
1. Increase timeout in playbook config:
   ```python
   "timeout": 3600,  # 1 hour
   ```
2. Check WRITER playbook is not waiting for user input
3. Check WRITER connectors are accessible (Schubert V2, EL Wiki, etc.)

### Issue: Playbook fails immediately

**Symptoms:** "❌ Error: Playbook trigger failed (4XX)"

**Solutions:**
1. Check API key is correct
2. Check webhook URL is correct
3. Check playbook is active in WRITER app
4. Test webhook manually:
   ```bash
   curl 'https://app.writer.com/webhook/triggers/playbook/YOUR-ID' \
     -X POST \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer YOUR-API-KEY' \
     --data-raw '{"inputs": []}'
   ```

### Issue: No auto-detection

**Symptoms:** The Architect responds normally instead of invoking playbook

**Solutions:**
1. Check message matches trigger patterns:
   ```python
   python3 -c "from writer_integration import should_invoke_playbook; print(should_invoke_playbook('your message', 'cursor-litellm'))"
   ```
2. Check error logs:
   ```bash
   sudo journalctl -u schubert-architect.service -n 50 | grep -i writer
   ```
3. Verify module is imported:
   ```bash
   grep "writer_integration" /opt/Project-Tango/scripts/architect-bot.py
   ```

### Issue: Deliverables not showing in Discord

**Symptoms:** Playbook completes but output is empty

**Solutions:**
1. Check deliverables are actually returned:
   ```bash
   # Test manually
   python3 /opt/Project-Tango/scripts/writer_playbook_client.py
   ```
2. Check deliverables format matches expectations
3. Check Discord message isn't too long (2000 char limit per message)

---

## Performance

### Typical Execution Times

- **Cursor LiteLLM Playbook:** 60-180 seconds
  - Step 1 (Load context & verify): 30-90s
  - Step 2 (Process request): 30-90s

### Optimization Tips

1. **Reduce poll interval** for faster response (but more API calls):
   ```python
   client = WriterPlaybookClient(webhook_url, api_key, poll_interval=5)
   ```

2. **Disable progress updates** for cleaner Discord UI:
   ```python
   await invoke_playbook_from_discord(..., progress_updates=False)
   ```

3. **Run playbooks in background** (for multi-tasking):
   ```python
   asyncio.create_task(invoke_playbook_from_discord(...))
   # The Architect continues responding to other messages
   ```

---

## Security

### API Key Protection

- API key is stored in `.env` (mode 600, owner z121532)
- Never logged or exposed in error messages
- Never sent to Discord
- Transmitted only via HTTPS to app.writer.com

### Webhook Security

- Webhook URLs are publicly accessible but unique per playbook
- No sensitive data in webhook URLs (just playbook ID)
- Webhook API requires Bearer token for authentication
- Webhook calls are rate-limited by WRITER platform

### Data Flow

```
Discord → The Architect → WRITER (HTTPS)
WRITER → The Architect (polling, HTTPS)
The Architect → Discord → User
```

**No data is stored** — all results are ephemeral (in-memory during execution only).

---

## Future Enhancements

### Planned Features

1. **Async callbacks** — WRITER posts completion to FastAPI endpoint
   - Faster responses (no polling delay)
   - Requires public webhook endpoint (`/api/discord/writer-callback`)

2. **Playbook chaining** — One playbook triggers another
   - Example: Cursor diagnostic → Auto-apply patches if needed

3. **User input handling** — Interactive playbooks
   - Handle `awaiting_user_response` status
   - Post Discord buttons/modals for user input

4. **Fleet-wide integration** — Other bots can invoke playbooks
   - Admiral Schubert
   - Dr. Voss
   - The Proctor

5. **Persistent playbook history** — Store results in PostgreSQL
   - Query past playbook runs
   - Compare diagnostics over time

---

## Related Documentation

- **WRITER Playbook Manifest:** `Cursor LiteLLM Session Provisioning/manifest.json`
- **Client Implementation:** `/opt/Project-Tango/scripts/writer_playbook_client.py`
- **Integration Layer:** `/opt/Project-Tango/scripts/writer_integration.py`
- **The Architect Bot:** `/opt/Project-Tango/scripts/architect-bot.py`
- **FastAPI Endpoint:** `/opt/Project-Tango/backend/main.py` (webhook callback)

---

## ADR References

- **ADR-014:** WRITER Agent Playbook Integration (2026-08-19)
- **ADR-011:** Discord-Slack Cross-Platform Notifications (2026-08-18)
- **ADR-012:** Slack MCP Server (2026-08-18)

---

**Questions?** Ask The Architect in Discord (`#nexus`) or check logs:

```bash
sudo journalctl -u schubert-architect.service -f | grep -i writer
```
