# Discord Channel Map — Nexus Fleet Model

> **Last updated:** 2026-08-21
> **Architecture:** Nexus Fleet Model (NX-SPEC-06)

This document maps the Schubert Discord server channels to the Nexus Fleet
Model tier architecture. Each channel has a dedicated bot, a defined purpose,
and a tier assignment.

---

## Tier Architecture Overview

```
Tier 0 (Command)
  └── Admiral Schubert — Sole fleet commander

Tier 1 (Executive)
  ├── The Architect — Lead developer
  ├── Dr. Voss — Chief Medical Officer / crisis response
  └── Dr. Cortex — Science Officer / research & analysis

Tier 2 (Operations)
  ├── Quartermaster — Infrastructure & operations
  ├── Cartographer — Documentation & knowledge management
  └── Sentinel — Autonomous testing & validation
```

---

## Channel Assignments

### Tier 0 — Command

| Channel | Channel ID | Bot | Topic |
|---------|-----------|-----|-------|
| #admiral-schubert | 1538476446157115442 | Admiral Schubert | Tier 0 — Fleet Commander \| Sole authority for fleet operations, task routing, and delegation. Nexus Bus orchestrator. |

**Admiral Schubert** is the sole Tier 0 commander. All task routing,
delegation, and fleet-wide coordination flows through this channel.
Capabilities include the Orchestrator Router, Acknowledgment Protocol
(30-second ack with 2 retries), Escalation Ladder (retry → reroute →
Dr. Voss → human operator), Nexus Bus (Redis Streams), Voice Operations
(Deepgram STT + ElevenLabs TTS), and Fleet Delegation (send and receive).

---

### Tier 1 — Executive

| Channel | Channel ID | Bot | Topic |
|---------|-----------|-----|-------|
| #the-architect | 1539473266400432208 | The Architect | Tier 1 — Lead Developer \| Code implementation, architecture decisions, and fleet-wide upgrades. Reports to Admiral. |
| #dr-voss | 1539104998821068880 | Dr. Voss | Tier 1 — Chief Medical Officer \| Health monitoring, diagnostics, crisis response, and auto-remediation. Reports to Admiral. |
| #dr-cortex | 1539173946698498088 | Dr. Cortex | Tier 1 — Science Officer \| Research, analysis, data flywheel, and weekly fleet analysis reports. Reports to Admiral. |

**The Architect** — Lead developer responsible for code implementation,
architecture decisions, and fleet-wide upgrades. Features self-healing
health monitoring, self-improvement auto-updater, Cloudflare tooling, and
Writer integration. Previously held a higher tier; demoted to Tier 1
Executive under the new model.

**Dr. Voss** — Chief Medical Officer responsible for health monitoring,
diagnostics, crisis response, and auto-remediation. Runs 60-second health
checks with escalation, intensive monitoring during incidents (10-second
intervals), and automated remediation with retry limits. Activated
automatically during fleet health incidents via the escalation ladder.

**Dr. Cortex** — Science Officer responsible for research, analysis, the
data flywheel, and weekly fleet analysis reports. Features voice mode,
fleet delegation (send and receive), polls, web search, and coding
capabilities. Provides research and analysis support to all tiers.

---

### Tier 2 — Operations

| Channel | Channel ID | Bot | Topic |
|---------|-----------|-----|-------|
| #quartermaster | 1538818248542396428 | Quartermaster | Tier 2 — Operations \| Infrastructure monitoring, service health, disk/process management. Reports to Admiral. |
| #cartographer | 1538818895706718269 | Cartographer | Tier 2 — Documentation \| Wiki maintenance, knowledge management, and change logs. Reports to Admiral. |
| #sentinel | 1539159059071111190 | Sentinel | Tier 2 — Autonomous Testing & Validation \| Conversational testing, Agent-as-a-Judge evaluation, auto-generated test cases, and repair loop. Reports to Admiral. |

**Quartermaster** — Operations specialist responsible for infrastructure
monitoring, service health, disk usage, and process management. Provides
operational data to Dr. Voss for health-related decisions.

**Cartographer** — Documentation officer responsible for wiki maintenance,
knowledge management, and change logs. Maintains the fleet's knowledge base
for all tiers.

**Sentinel** — Autonomous testing and validation specialist. Replaces The
Proctor. Implements test recipes, rubrics, a conversation runner,
Agent-as-a-Judge evaluation, a test case generator, a repair engine, and
posterior capability tracking. Test results feed into Dr. Cortex's data
flywheel for fleet-wide analysis.

---

### Multi-Agent Collaborative

| Channel | Channel ID | Purpose |
|---------|-----------|---------|
| #senior-staff-meeting | 1539023116968398911 | Multi-Agent Collaborative Channel \| All bots collaborate here. Admiral coordinates. Nexus Bus events visible to all. |

All fleet bots participate in this channel. Admiral Schubert coordinates
discussions and task assignments. Each bot responds when addressed via
`@bot_name` or when the conversation is relevant to their role. Response
thresholds and cooldowns apply per bot configuration. Nexus Bus events
(Redis Streams) are visible to all participants for real-time awareness of
fleet-wide task routing, delegations, and acknowledgments.

---

### Archive Channels

| Channel | Channel ID | Purpose |
|---------|-----------|---------|
| #sentinel-analysis-archive | 1539159060568342539 | Sentinel Analysis Archive \| Test results, posterior scores, and capability tracking. Historical Proctor data preserved. |
| #proctor-archive | 1539104999941079103 | Archive — Former Proctor Channel \| Replaced by Sentinel. Historical reference only. |

**Sentinel Analysis Archive** — Stores test run results, posterior scores,
capability tracking data, Agent-as-a-Judge evaluations, and repair loop
outcomes. Historical Proctor data is preserved here. Previously served as
The Proctor's analysis channel.

**Proctor Archive** — Archived channel. The Proctor has been replaced by
Sentinel. Messages are preserved for historical reference. No new testing
activity occurs here.

---

## Channel-to-Bot Mapping Summary

| Bot | Tier | Primary Channel | Channel ID | Service |
|-----|------|----------------|-----------|---------|
| Admiral Schubert | Tier 0 | #admiral-schubert | 1538476446157115442 | schubert-bot.service |
| The Architect | Tier 1 | #the-architect | 1539473266400432208 | schubert-architect.service |
| Dr. Voss | Tier 1 | #dr-voss | 1539104998821068880 | schubert-dr-voss.service |
| Dr. Cortex | Tier 1 | #dr-cortex | 1539173946698498088 | cortex-bot.service |
| Quartermaster | Tier 2 | #quartermaster | 1538818248542396428 | schubert-quartermaster.service |
| Cartographer | Tier 2 | #cartographer | 1538818895706718269 | schubert-cartographer.service |
| Sentinel | Tier 2 | #sentinel | 1539159059071111190 | (replaces schubert-proctor.service) |

---

## Proctor → Sentinel Transition

The Proctor has been replaced by Sentinel under the Nexus Fleet Model. The
transition maps as follows:

| Proctor Channel | Proctor Purpose | Sentinel Equivalent | New Purpose |
|----------------|----------------|---------------------|------------|
| #proctor-dedicated (1539104999941079103) | Proctor's dedicated channel | #proctor-archive | Archived — historical reference only |
| #proctor-delegation (1539159059071111190) | Proctor's delegation channel | #sentinel | Sentinel's primary testing channel |
| #proctor-analysis (1539159060568342539) | Proctor's analysis channel | #sentinel-analysis-archive | Sentinel's analysis archive |

All historical Proctor data is preserved. Sentinel continues the testing
mission with enhanced capabilities.

---

## Updating Channels

To update channel topics and post starter messages, run:

```bash
# Dry run (preview changes without applying)
python scripts/update_discord_channels.py --dry-run

# Live run (requires SCHUBERT_BOT_TOKEN)
export SCHUBERT_BOT_TOKEN='your_token_here'
python scripts/update_discord_channels.py
```

The script:
- Updates the topic for each channel listed above
- Posts a starter message explaining the bot's role in the new architecture
- Does NOT delete any channels or messages
- Includes rate-limit safety delays between operations
- Logs all actions for audit purposes

---

## References

- **NX-SPEC-06**: Nexus Fleet Model specification
- **fleet-manifest.yaml**: Fleet manifest with tier assignments
- **fleet-config.json**: Runtime fleet configuration
- **AGENTS.md**: Project Tango agent collaboration guide
