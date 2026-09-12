# Discord to Slack Automation - Writer Event Feedback Summary

## Overview

This automation sends the Writer Event Feedback Summary from Discord (kickstart-demo channel) to Slack (#demo-cape-webinars channel).

## Setup Complete

✅ Script created: `/opt/Project-Tango/scripts/send_feedback_slack.py`
✅ Message formatted and ready
✅ Target Slack channel: `C0BR92E39PW` (demo-cape-webinars)

## How to Use

### Option 1: Via Discord Bot Command (Recommended)

In the Discord **kickstart-demo** channel (ID: 1539657495142998078), use any of these methods:

**Natural Language:**
```
@Admiral Schubert send the Writer Event Feedback Summary to Slack
```

**Command:**
```
!send-feedback
```

The bot will automatically post the full formatted message to Slack #demo-cape-webinars.

### Option 2: Manually via Slack MCP

From any Cursor Agent session with Slack MCP access:

```python
from send_feedback_slack import FEEDBACK_MESSAGE, SLACK_CHANNEL_ID

# Use Slack MCP tool
await slack_send_message(SLACK_CHANNEL_ID, FEEDBACK_MESSAGE)
```

### Option 3: Direct Script Execution

The message has been sent successfully to Slack channel #demo-cape-webinars!

## Message Content

The message includes:
- **At a Glance** - Key metrics (NPS +60, 4.50/5 rating, 90% ready to implement)
- **What's Working** - Top 5 positive themes (integration, automation, playbooks)
- **What Needs Improvement** - 8 signals (pacing, breakout rooms, security coverage)
- **Top Use Cases** - 10 requested use cases (meeting summaries, lead enrichment)
- **Barriers to Adoption** - 6 barriers (ROI data, executive buy-in, pricing)
- **Action Items** - Sales (6 actions) and Marketing (6 actions)
- **Follow-Up Pipeline** - Distribution of follow-up types
- **Hot Accounts** - Datadog, Snowflake, Asana, Box, Slack, Atlassian, Workday, Twilio, Monday.com, Stripe
- **3 Most Important Insights**
- **Single Highest-Priority Next Action** - ROI one-pager

## Technical Details

**Discord Channel:** `1539657495142998078` (kickstart-demo)
**Slack Channel:** `C0BR92E39PW` (demo-cape-webinars)
**Message Format:** Slack markdown (tables, headers, emojis supported)
**Message Length:** ~6,400 characters
**Delivery Method:** Slack MCP (`slack_send_message` tool)

## Automation Files

1. `/opt/Project-Tango/scripts/send_feedback_slack.py` - Core script with message content
2. `/opt/Project-Tango/scripts/discord_to_slack_automation.py` - Discord UI integration (buttons, commands)
3. `/opt/Project-Tango/scripts/kickstart-demo-bot.py` - Standalone bot (alternative, not deployed)

## Future Enhancements

- [ ] Schedule automatic weekly sends
- [ ] Add dynamic date/response count updates
- [ ] Create Discord slash command for easier triggering
- [ ] Add confirmation dialog before sending
- [ ] Track send history/analytics

## Status

✅ **DEPLOYED AND READY TO USE**

The Writer Event Feedback Summary has been successfully sent to Slack #demo-cape-webinars. You can trigger future sends using the methods documented above.

---

Last Updated: 2026-08-19  
Created by: Cursor Agent
