#!/usr/bin/env python3
"""
Simple Discord Slash Command for Sending Feedback to Slack
===========================================================
This script can be run standalone or integrated into an existing bot.

Usage:
    python3 send_feedback_slack.py

Or call the function directly from another bot:
    from send_feedback_slack import send_feedback_to_slack
    result = await send_feedback_to_slack(slack_mcp_tool_func)
"""

import asyncio

# The message to send (Slack markdown format)
FEEDBACK_MESSAGE = """# 📊 Writer Event Feedback Summary

_30 responses · Dec 7, 2025 – Feb 3, 2026 · 10 events_

## 🔍 At a Glance

| Metric | Value |
|---|---|
| ⭐ Avg Overall Rating | 4.50 / 5 |
| 💯 Avg NPS Score | 8.97 / 10 |
| 📈 NPS Score | +60 |
| 🚀 Ready to implement ≤30 days | 90% (27/30) |
| ⚠️ Outlier low scores (1–2) | None (lowest = 3) |

## ✨ What's Working — top positive themes

1. 🔗 Integration with existing tools (Slack, Gmail) — 8 mentions
2. ⚙️ Can see 5+ workflows to automate — 8 mentions
3. 📒 Playbooks concept > just chatting with AI — 6 mentions
4. 💪 More powerful than ChatGPT/Copilot — 6 mentions
5. 🎙️ Voice/brand consistency for regulated industries — 6 mentions

_(Also: ⏱️ Save 10+ hrs/week (5), 🧠 Knowledge Graphs (5), 🛠️ Practical examples (5), 🎬 Live demo (5))_

## 🛠️ What Needs Improvement

| Signal | Count |
|---|---|
| 🐢 Pacing / session too fast | 3 |
| 🌀 Breakout rooms chaotic | 3 |
| 🔒 Security & compliance coverage | 3 |
| 📊 ROI / before-after metrics | 2 |
| 🧪 Hands-on practice environment | 2 |
| 🏥 Industry-specific examples | 1 |
| ❓ More Q&A time | 1 |
| 🔌 Deeper Connectors coverage | 1 |

_(13 of 30 said "no major concerns" ✅)_

## 🎯 Top Use Cases Requested

| Use Case | Count |
|---|---|
| 📝 Meeting summaries | 11 |
| 🧲 Lead enrichment | 11 |
| 📋 Customer case studies | 10 |
| 📆 Event recap automation | 9 |
| ⚔️ Competitive analysis | 7 |
| 📑 RFP responses | 6 |
| ✍️ Proposal generation | 6 |
| 📧 Sales email personalization | 6 |
| 🚀 Product launch materials | 6 |
| 📢 Marketing campaign briefs | 6 |

## 🚧 Top Barriers to Adoption

| Barrier | Count |
|---|---|
| 📊 Want to see more ROI data | 8 |
| 👔 Need executive buy-in | 6 |
| 💰 Need to understand pricing | 5 |
| ✅ No barriers, ready to go | 5 |
| 🧪 Test with our workflows | 4 |
| 🔐 Waiting on IT/Security review | 2 |

## 🎯 Action Items — Sales

- 📄 Build an ROI one-pager with before/after metrics (addresses the #1 barrier — 8 mentions)
- 💵 Create pricing & packaging FAQ to share with evaluators (5 pricing asks)
- 🤝 Stand up a champion enablement deck for securing executive buy-in (6 mentions)
- 🔐 Prepare a security & compliance brief (3 explicit asks + 2 in IT/Security review)
- 🧪 Offer a guided hands-on sandbox / follow-up advanced session (2 practice + 1 advanced ask)
- 📞 Prioritize outreach to hot accounts (see pipeline below)

## 📣 Action Items — Marketing

- 🎯 Lead campaigns with the top use cases: Meeting summaries, Lead enrichment, Customer case studies
- 🎬 Capture the live-demo "campaign brief in real-time" moment as a reusable video asset (5 mentions)
- ⚔️ Build competitive battlecards vs. ChatGPT/Copilot (6 "more powerful" mentions)
- 🏭 Develop industry-specific examples (healthcare flagged)
- ⏱️ Tighten breakout-room logistics & extend sessions to 2.5 hrs (pacing feedback)
- 🎙️ Showcase voice/brand consistency for regulated-industry prospects (6 mentions)

## 📈 Follow-Up Pipeline

| Follow-Up Type | Count |
|---|---|
| 🕐 Office hours | 11 |
| 📚 Send resources/docs | 7 |
| 📅 Schedule follow-up demo | 3 |
| 🤔 Still evaluating | 4 |
| 🚫 No follow-up needed | 5 |

🔥 **Top hot accounts** (strong buying intent / enterprise pricing / "move fast"):
Datadog, Snowflake, Asana, Box, Slack, Atlassian, Workday, Twilio, Monday.com, Stripe

_Footer: 30 total responses across 10 events, Dec 7, 2025 – Feb 3, 2026._

---

## 💡 3 Most Important Insights

1️⃣ **Demand is strong and near-term** — 90% ready to implement within 30 days, NPS +60, no outlier low scores.
2️⃣ **ROI data is the #1 barrier** (8 mentions) — prospects need quantified before/after proof to buy.
3️⃣ **Meeting summaries & lead enrichment are the gateway use cases** (11 mentions each) — the best hooks for Sales and Marketing.

## 🏁 Single Highest-Priority Next Action

Produce an ROI one-pager with before/after metrics from existing customers and arm Sales with it immediately — it unblocks the top barrier and the largest share of warm leads."""

SLACK_CHANNEL_ID = "C0BR92E39PW"  # demo-cape-webinars


async def send_feedback_to_slack(slack_send_message_func):
    """
    Send the Writer Event Feedback Summary to Slack.

    DISABLED — Slack notifications turned off to prevent messages being sent as user to work channels.

    Args:
        slack_send_message_func: Async function that sends message to Slack
                                Format: await func(channel, message)

    Returns:
        dict with success status and message
    """
    return {
        "success": False,
        "error": "Slack notifications have been disabled."
    }


if __name__ == "__main__":
    print("Writer Event Feedback Summary - Slack Sender")
    print(f"Target Channel: {SLACK_CHANNEL_ID} (demo-cape-webinars)")
    print(f"Message length: {len(FEEDBACK_MESSAGE)} characters")
    print("\nThis script requires integration with a Slack MCP client to actually send.")
    print("Use from a bot with Slack MCP access.")
