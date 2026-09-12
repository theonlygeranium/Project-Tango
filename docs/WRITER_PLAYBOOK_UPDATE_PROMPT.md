# WRITER Agent Playbook Update — Discord Integration Callback

**Prompt for WRITER Agent**

Copy and paste this entire prompt to the WRITER Agent to update the "Cursor LiteLLM Session Provisioning" playbook:

---

## Task: Update Playbook to Support Discord Callback

I need you to update the "Cursor LiteLLM Session Provisioning" playbook to optionally send completion results back to Discord when invoked by The Architect bot.

### Playbook Details

**Playbook ID:** `1574c302-b407-4553-a2f6-6e42291e805c`  
**Playbook URL:** https://app.writer.com/playbooks/1574c302-b407-4553-a2f6-6e42291e805c  
**Current Status:** Active, working as-is (no breaking changes needed)

### What Needs to Change

**Step 2** (final step) needs to optionally send results to a Discord callback URL when provided as an input variable.

### Required Changes

#### 1. Add New Input Variable

Add this variable to the playbook's `variables` array:

```json
{
  "name": "discord_callback_url",
  "type": "string",
  "required": false,
  "description": "Optional Discord webhook callback URL. If provided, playbook will POST completion results to this URL.",
  "default": ""
}
```

**Important:** This variable must be **optional** (not required) so existing invocations continue working.

#### 2. Update Step 2 Logic

At the **end** of Step 2 (after generating the status summary), add this conditional logic:

**Pseudocode:**
```
IF discord_callback_url is not empty:
  1. Extract the status summary that was just generated
  2. Format it as JSON payload:
     {
       "thread_id": "{current_thread_id}",
       "status": "completed",  // or "failed" if errors were found
       "deliverables": {
         "type": "text",
         "content": "{status_summary_text}"
       },
       "error_message": null  // or error text if playbook failed
     }
  3. POST the JSON payload to discord_callback_url
  4. Log success or failure of the webhook POST
  5. Continue with normal response (don't fail if webhook fails)
END IF
```

**Actual Implementation (use WRITER connector or HTTP tool):**

If WRITER has an HTTP POST tool, use:
```
POST {discord_callback_url}
Headers:
  Content-Type: application/json
Body:
{
  "callback_id": "{extract from callback_url query param or generate UUID}",
  "thread_id": "{current_thread_id}",
  "status": "completed",
  "deliverables": {
    "type": "text",
    "content": "{full_status_summary}"
  },
  "error_message": null
}
```

**If WRITER doesn't have HTTP POST tool,** add a note in Step 2 that says:
```
"Discord callback requested but not yet implemented. 
Callback URL: {discord_callback_url}
Results are available via normal deliverables endpoint."
```

#### 3. Update Step 2 Prompt

Modify the Step 2 prompt to include:

```markdown
- If discord_callback_url input variable is provided (non-empty), attempt to POST the completion results to that URL using the following JSON format:
  {
    "callback_id": "<extract from URL query param 'callback_id' or generate a UUID>",
    "thread_id": "<current thread ID>",
    "status": "completed",
    "deliverables": {
      "type": "text",
      "content": "<full status summary generated above>"
    },
    "error_message": null
  }
- The webhook POST should be fire-and-forget (don't fail the playbook if webhook fails).
- Log whether the webhook POST succeeded or failed.
- Continue with normal playbook completion regardless of webhook result.
```

### Expected Behavior After Update

**When invoked without `discord_callback_url`:**
- Playbook runs exactly as before (no changes)
- Results available via normal deliverables endpoint

**When invoked with `discord_callback_url`:**
- Playbook runs as before
- At completion, sends POST request to callback URL with results
- Continues to provide results via normal deliverables endpoint (both methods work)

### Testing the Update

After updating, test with:

**Test 1: Normal invocation (no callback)**
```bash
curl 'https://app.writer.com/webhook/triggers/playbook/1574c302-b407-4553-a2f6-6e42291e805c' \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer 4b7ddcec2fca099542b6fb888334cfd83683465dcd60e77d2c7678ec47e6affd' \
  --data-raw '{"inputs": []}'
```

**Expected:** Playbook completes normally (no callback sent)

**Test 2: Invocation with callback**
```bash
curl 'https://app.writer.com/webhook/triggers/playbook/1574c302-b407-4553-a2f6-6e42291e805c' \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer 4b7ddcec2fca099542b6fb888334cfd83683465dcd60e77d2c7678ec47e6affd' \
  --data-raw '{
    "inputs": [
      {
        "name": "discord_callback_url",
        "value": "https://tango-api.schubert.life/api/discord/writer-callback?callback_id=test-123"
      }
    ]
  }'
```

**Expected:** 
- Playbook completes normally
- POST request sent to callback URL with results
- Check Schubert logs: `journalctl -u tango-backend | grep writer-callback`

### Discord Callback URL Format

The Discord bot will provide callback URLs in this format:
```
https://tango-api.schubert.life/api/discord/writer-callback?callback_id={unique_id}
```

Where `{unique_id}` is a one-time secret token used to route results back to the waiting Discord bot.

### Callback Endpoint Specification

The Discord callback endpoint expects this JSON schema:

```json
{
  "callback_id": "string (required) - extracted from URL query param",
  "thread_id": "string (required) - WRITER thread ID",
  "status": "string (required) - 'completed', 'failed', 'stopped', or 'awaiting_user_response'",
  "deliverables": {
    "type": "string - 'text', 'json', or 'binary'",
    "content": "string - full status summary or deliverable content",
    "...": "any other deliverable fields"
  },
  "error_message": "string or null - error details if status is 'failed'"
}
```

### Important Notes

1. **Backward Compatibility:** The `discord_callback_url` variable must be optional. Existing invocations without this parameter must continue working.

2. **Error Handling:** If the callback POST fails, log the error but don't fail the playbook. The Discord bot will fall back to polling.

3. **Security:** The callback URL is only valid for one playbook invocation. It's a one-time secret token.

4. **Timeout:** The callback should be sent within 5 seconds of playbook completion. No need to wait or retry.

5. **Thread ID:** Make sure to include the WRITER thread ID so the Discord bot can correlate the callback with the correct invocation.

### Questions?

If anything is unclear or if WRITER doesn't support HTTP POST from playbooks:
1. Update the playbook to document that callbacks are "not yet supported"
2. Let me know and we'll implement polling-only mode (which already works)
3. We can revisit callbacks in a future update when WRITER adds the capability

---

**After you make these changes, please:**
1. Save the updated playbook
2. Test both invocation methods (with and without callback URL)
3. Confirm the playbook still works for normal use cases
4. Let me know if you encountered any issues or limitations

**Thank you!**
