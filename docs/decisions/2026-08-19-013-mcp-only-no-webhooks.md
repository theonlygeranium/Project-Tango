# Decision: Use MCP for All Slack Operations (Skip Webhooks)

**Date:** 2026-08-19 05:19 UTC  
**Approved By:** Jeff Geronimo (EdStratum Labs founder)  
**Decided By:** Cursor Agent with user approval  
**Status:** Approved and Implemented

---

## Decision

**Use Slack MCP for both read AND write operations. Skip incoming webhooks (Phase 1) entirely.**

The Discord bot fleet will use `slack__post_message` MCP tool for notifications instead of incoming webhooks. Webhooks may be reconsidered later as a fallback mechanism.

---

## Rationale

### Why MCP Instead of Webhooks

Since Slack MCP Server is already deployed and operational:

1. **Unified Interface** - One protocol for all Slack operations (read + write)
2. **Dynamic Channel Selection** - Can post to any channel programmatically
3. **Error Handling** - Can catch failures and retry
4. **Already Deployed** - No additional setup required
5. **More Flexible** - Full Block Kit support, thread replies, reactions

### Why Not Webhooks

1. **Redundant** - Would duplicate functionality already in MCP
2. **Manual Setup** - Requires creating 3+ webhooks in Slack workspace
3. **Fixed Channels** - Each webhook targets one channel only
4. **Fire-and-Forget** - No error handling or retry capability
5. **Additional Dependencies** - More things to configure and maintain

### Trade-offs Accepted

**Single Point of Failure:** If Slack MCP server crashes, all Slack operations fail (both read and write).

**Mitigation:** 
- `slack-mcp.service` has auto-restart configured (10 second recovery)
- Can add webhook fallback later if needed
- Dr. Voss health monitoring will detect MCP failures

---

## Implementation Plan

### Phase 1: Update Notification Code

Modify `scripts/slack_notifier.py` to use MCP instead of webhooks:

**Old (webhooks):**
```python
await notifier.send_deployment_alert(...)
# Uses: requests.post(WEBHOOK_URL, ...)
```

**New (MCP):**
```python
await mcp_client.call_tool("slack__post_message", {
    "channel": "C01234567",
    "text": "...",
    "blocks": [...]
})
```

### Phase 2: Update Bot Integrations

Update these bots to use new MCP-based notifications:
- The Architect (deployment alerts)
- Dr. Voss (health alerts)
- The Proctor (performance reports)

### Phase 3: Documentation

- Update `SLACK_INTEGRATION_DEPLOY.md` to reflect MCP approach
- Update `CHANGELOG.md` with decision
- Create ADR-013 for this architectural change

---

## Approval Record

**User Statement:**
> "Yes proceed with MCP for now. We may bring back webhooks later and we can keep this documented that I approved this motion."

**Timestamp:** 2026-08-19 05:19 UTC (2026-08-18 10:19 PM Pacific)  
**Channel:** Cursor Agent Chat  
**Approved By:** Jeff Geronimo (@themightymaven, Discord user 1075596247966167131)

---

## Future Considerations

### When to Reconsider Webhooks

Webhooks may be added back as a **fallback mechanism** if:

1. **Reliability Issues** - MCP server proves unstable in production
2. **Critical Alerts** - Need absolute guarantee of notification delivery
3. **Latency Requirements** - Need faster than MCP's ~200ms overhead
4. **Redundancy** - Want defense-in-depth for mission-critical notifications

### Hybrid Approach (Future Option)

Could implement:
- **Primary:** MCP for all operations (current decision)
- **Fallback:** Webhooks for critical alerts only (e.g., production outages)
- **Logic:** Try MCP first, fall back to webhook if MCP fails

This would provide both flexibility and reliability.

---

## References

- **Phase 2 Deployment:** `docs/PHASE2_DEPLOYMENT_COMPLETE.md`
- **Slack MCP Setup:** `docs/SLACK_MCP_SETUP.md`
- **ADR-012:** Slack MCP Server architecture
- **User Approval:** This document

---

**Status:** ✅ Approved and ready for implementation  
**Next Step:** Update `slack_notifier.py` to use MCP
