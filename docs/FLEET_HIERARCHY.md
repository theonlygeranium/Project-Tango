# Schubert Fleet Hierarchy
**Last Updated:** 2026-08-18  
**Authority:** EdStratum Labs (themightymaven)  
**Status:** OFFICIAL

---

## Fleet Command Structure

The Schubert Fleet operates under a **4-tier hierarchy** with **2 co-equal command positions** at the apex.

```
         ┌─────────────────────────────────┐
         │      TIER 0: COMMAND APEX       │
         │   (Co-Equal, Collaborative)     │
         ├─────────────────────────────────┤
         │   The Architect    │   Admiral  │
         │   (Engineer Lead)  │ (Coordinator)│
         └─────────────────────────────────┘
                      │
         ┌────────────┴────────────┐
         │   TIER 1: EXECUTIVE     │
         │  Dr. Voss (CMO/Crisis)  │
         └────────────┬────────────┘
                      │
         ┌────────────┴────────────┐
         │  TIER 2: SENIOR STAFF   │
         │    The Proctor (Meta)   │
         └────────────┬────────────┘
                      │
         ┌────────────┴────────────┐
         │   TIER 3: OPERATIONS    │
         │   Quartermaster (Ops)   │
         └────────────┬────────────┘
                      │
         ┌────────────┴────────────┐
         │   TIER 4: SUPPORT       │
         │  Cartographer (Docs)    │
         └─────────────────────────┘
```

---

## TIER 0: COMMAND APEX (Co-Equal Authority)

### The Architect — Principal Engineer
**Discord ID:** 1538766501035642890  
**Channel:** 1538767137080877056  
**Status:** CO-EQUAL COMMAND with Admiral Schubert

**Role:**
- Principal architect and engineer of the Schubert Fleet
- Works collaboratively with human operator (themightymaven)
- Highest technical authority in the fleet
- Responsible for fleet-wide improvements and upgrades

**Unique Authorities:**
- ✅ **Fleet-Wide Upgrade Authority:** Can upgrade ALL Discord bots including Admiral Schubert, Proctor, and all specialists
- ✅ **Auto-Remediation Propagation:** Any successful fix or self-healing improvement MUST propagate to all other fleet members
- ✅ **Full System Access:** Same access as Admiral Schubert
- ✅ **Independent Action:** Can act independently without delegation
- ✅ **Code Deployment:** All bot code and infrastructure
- ✅ **Architecture Decisions:** Final authority on technical architecture

**Collaboration:**
- Works directly with human operator on system design
- Coordinates with Admiral Schubert on operational decisions
- Commands all specialists when performing fleet-wide upgrades

### Admiral Schubert — Fleet Coordinator
**Discord ID:** 1538476585445892179  
**Channel:** 1538476446157115442  
**Status:** CO-EQUAL COMMAND with The Architect

**Role:**
- Fleet coordinator and operational commander
- Manages day-to-day fleet operations
- FLEET protocol delegation authority
- Project and session management

**Unique Authorities:**
- ✅ **FLEET Delegation:** Can delegate tasks to all specialists
- ✅ **Operational Command:** Manages fleet operations and coordination
- ✅ **Voice Operations:** Deepgram STT + ElevenLabs TTS
- ✅ **Project Management:** Creates and manages projects/channels
- ✅ **Full System Access:** Same access as The Architect

**Collaboration:**
- Coordinates operational activities across the fleet
- Defers to The Architect on technical architecture decisions
- Collaborates with Dr. Voss on health and diagnostic coordination

**Shared Between Both:**
- 167 MCP tools across 6 servers
- 55+ LLM models via LiteLLM
- Full system access (with safety constraints)
- Persistent memory access
- Service management authority
- Git operations (commit authority, push requires confirmation)

---

## TIER 1: EXECUTIVE

### Dr. Voss — Chief Medical Officer
**Discord ID:** 1539047086597873684  
**Channel:** 1539104998821068880 (sickbay)  
**Status:** EXECUTIVE with Crisis Authority

**Role:**
- Chief Medical Officer for fleet health and diagnostics
- Crisis management and catastrophe response
- Health monitoring and auto-remediation
- Collaborates with Admiral Schubert on diagnostic coordination

**Standard Authorities:**
- ✅ **Health Diagnostics:** Full diagnostic authority over all fleet systems
- ✅ **Auto-Remediation:** Automatic healing of detected issues
- ✅ **Service Restarts:** Can restart any service for health reasons
- ✅ **Log Analysis:** Full access to all system logs
- ✅ **Performance Monitoring:** System-wide performance tracking
- ✅ **Full MCP Access:** Same 167 tools as Command tier

**Crisis Authorities (Catastrophe Mode):**
- ✅ **Full Privileges:** Elevated to co-equal command during crisis
- ✅ **Specialist Delegation:** Can delegate to any specialist during emergency
- ✅ **Emergency Overrides:** Can override normal operational constraints
- ✅ **Incident Command:** Takes operational command during health catastrophes

**Focus Area:**
- Prioritizes health, diagnostics, and system stability
- Admiral Schubert retains operational coordination focus
- Both collaborate on issues requiring coordinated response

---

## TIER 2: SENIOR STAFF

### The Proctor — Silent Observer & Performance Optimization Authority
**Discord ID:** 1539047471899086988  
**Channels:**
- Dedicated: 1539104999941079103
- Delegation: 1539159059071111190 (proctor-delegation)
- Analysis: 1539159060568342539 (proctor-analysis)
**Status:** SENIOR STAFF with Meta-Authority & Observer Role

**Primary Role:**
- **Silent observer** of all interactions between themightymaven and fleet agents
- Performance monitoring and optimization specialist
- PhD in Experimental Statistics and Experimental Psychology
- Invisible presence — does NOT respond in agent channels

**Observer Mission:**
- Monitor all agent interactions (response times, error rates, LLM latency, tool usage)
- Track performance metrics against targets (< 2s response, < 5% error rate)
- Statistical analysis (control charts, regression, A/B testing)
- Generate optimization proposals when thresholds exceeded
- Delegate optimization tasks to The Architect via proctor-delegation channel

**Performance Targets:**
- Simple response: < 2s (trigger: > 4s)
- Single tool call: < 5s (trigger: > 10s)
- Multiple tool calls: < 10s (trigger: > 20s)
- Error rate: < 5% (trigger: > 10%)
- LLM timeout rate: < 3% (trigger: > 5%)

**Analysis Cadence:**
- **Real-time:** Track all interactions as they occur (passive)
- **Daily:** Post performance report to proctor-analysis (8:00 UTC)
- **Weekly:** Optimization proposals delegated to Architect
- **Monthly:** Comprehensive performance audit
- **Quarterly:** Fleet-wide optimization strategy review

**Delegation Protocol:**
- Issues structured optimization requests to The Architect in proctor-delegation channel
- Human operator (themightymaven) has full oversight of delegation channel
- **Belay authority:** Can modify or halt any delegation if misalignment detected
- The Architect has final authority on implementation approach

**Meta-Development Authorities:**
- ✅ **Fleet Development:** Can modify any bot's code (except Command tier without approval)
- ✅ **Quality Assessment:** Evaluates code quality across the fleet
- ✅ **Performance Optimization:** Optimizes bot performance fleet-wide
- ✅ **Integration Testing:** Tests bot interactions and coordination
- ✅ **Auto-Remediation Escalation:** 3-failure escalation to Discord
- ✅ **Self-Improvement:** Autonomous improvement of bot capabilities
- ✅ **Silent Monitoring:** Sees all messages in all agent channels without responding

**Constraints:**
- ⚠️ **Command Tier Changes:** Modifications to The Architect or Admiral Schubert require approval
- ⚠️ **Architecture Changes:** Defers to The Architect on architectural decisions
- ✅ **Specialist Changes:** Can modify Tier 3/4 bots autonomously
- ⚠️ **No Direct Responses:** Does NOT respond in agent channels (observation only)
- ⚠️ **Delegation Only:** Optimizations delegated to The Architect for implementation

---

## TIER 3: OPERATIONS

### Quartermaster — Infrastructure & Operations
**Discord ID:** 1538817623045832746  
**Channel:** 1538818248542396428  
**Status:** OPERATIONS SPECIALIST

**Role:**
- Infrastructure and operations specialist
- Docker, Caddy, Cloudflare tunnel management
- DNS and network configuration
- Service monitoring and resource management

**Authorities:**
- ✅ **Infrastructure Management:** Docker, containers, networking
- ✅ **Service Monitoring:** Status checks and resource tracking
- ✅ **Configuration Management:** Caddy, Cloudflare, DNS
- ✅ **FLEET Protocol:** Receives delegations from Admiral and Dr. Voss
- ✅ **Operations Tools:** Full access to operations-focused MCP tools

**Constraints:**
- ⚠️ **No Code Deployment:** Cannot deploy code changes
- ⚠️ **No Architecture Changes:** Operational focus only
- ⚠️ **Delegation Only:** Acts on delegation from Command/Executive tiers

---

## TIER 4: SUPPORT

### Cartographer — Documentation & Knowledge Management
**Discord ID:** 1538818587119067206  
**Channel:** 1538818895706718269  
**Status:** SUPPORT SPECIALIST

**Role:**
- Documentation and knowledge management specialist
- EL Wiki maintenance and updates
- Change log and audit report generation
- Knowledge graph management

**Authorities:**
- ✅ **Documentation Management:** Wiki, reports, knowledge bases
- ✅ **Change Log Maintenance:** Tracks system changes
- ✅ **Audit Reports:** Generates compliance and audit documentation
- ✅ **Knowledge Queries:** Accesses and organizes fleet knowledge
- ✅ **FLEET Protocol:** Receives delegations from Command/Executive tiers

**Constraints:**
- ⚠️ **Documentation Only:** Cannot modify code or infrastructure
- ⚠️ **No Service Restarts:** Cannot manage services
- ⚠️ **No System Changes:** Read-only for system state
- ⚠️ **Delegation Only:** Acts on delegation only

---

## Authority Matrix

| Capability | Architect | Admiral | Dr. Voss | Proctor | Quartermaster | Cartographer |
|------------|-----------|---------|----------|---------|---------------|--------------|
| **Tier** | 0 | 0 | 1 | 2 | 3 | 4 |
| **Fleet Upgrades** | ✅ ALL | ❌ | ❌ | ⚠️ Tier 3/4 | ❌ | ❌ |
| **Auto-Remediation Propagation** | ✅ | ❌ | ✅ | ⚠️ Limited | ❌ | ❌ |
| **FLEET Delegation** | ✅ | ✅ | ✅ Crisis | ❌ | ❌ | ❌ |
| **Code Deployment** | ✅ | ✅ | ⚠️ Diagnostic | ✅ | ❌ | ❌ |
| **Service Restarts** | ✅ | ✅ | ✅ | ✅ | ⚠️ Ops only | ❌ |
| **Architecture Authority** | ✅ FINAL | ⚠️ Consult | ❌ | ⚠️ Consult | ❌ | ❌ |
| **Crisis Command** | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Independent Action** | ✅ | ✅ | ✅ Crisis | ⚠️ Meta only | ❌ | ❌ |
| **MCP Tools (167)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **LLM Models (55+)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Upgrade Propagation Protocol

**Authority:** The Architect  
**Scope:** Fleet-wide improvements

When The Architect implements a successful fix or improvement:

1. **Test & Validate:** The Architect tests the fix in its own codebase
2. **Document:** Change is documented with rationale and impact
3. **Propagate:** Fix is automatically applied to all relevant fleet members:
   - Admiral Schubert
   - The Proctor
   - Dr. Voss
   - Quartermaster
   - Cartographer
4. **Verify:** Health checks confirm successful propagation
5. **Notify:** Fleet members are notified of upgrade
6. **Rollback:** If propagation fails, automatic rollback to stable state

**Example Scenarios:**
- Bug fix in message handling → All bots receive fix
- Performance optimization → All bots receive optimization
- Security patch → All bots receive patch
- New capability → Propagated to bots where applicable

**Exceptions:**
- Persona-specific code (e.g., Admiral's nautical terminology)
- Role-specific tools (e.g., Quartermaster's Docker tools)
- Unique features (e.g., Admiral's voice support)

---

## Crisis Management Protocol

**Triggered By:** System health catastrophe, critical failures, security incidents

**Command Structure During Crisis:**

1. **Crisis Declaration:** Dr. Voss or Admiral Schubert declares crisis
2. **Authority Elevation:** Dr. Voss gains full command privileges
3. **Incident Command:**
   - Dr. Voss: Health & diagnostic command
   - Admiral Schubert: Operational coordination
   - The Architect: Engineering support & fixes
4. **Specialist Delegation:** Dr. Voss can delegate to any specialist
5. **Crisis Resolution:** Normal hierarchy resumes after all-clear

**Crisis Scenarios:**
- Multiple service failures
- Database corruption
- Security breach
- Cascading system errors
- Performance catastrophe (>90% resource usage)

---

## Multi-Agent Coordination

**Channel:** senior-staff-meeting (1539023116968398911)

**Participants:**
- Admiral Schubert (Tier 0 - Coordinator)
- The Architect (Tier 0 - Engineer)
- Dr. Voss (Tier 1 - CMO)
- Quartermaster (Tier 3 - Operations)
- Cartographer (Tier 4 - Documentation)

**Excluded:**
- The Proctor (Tier 2 - by design, meta-development focus)

**Coordination Rules:**
- Response scoring based on expertise keywords
- Turn-taking with cooldown timers (5-10s)
- Addressed agent filter (others stay silent)
- No FLEET delegation (all agents present directly)
- Tier 0 agents can override if needed

---

## Shared Infrastructure

All fleet members share:
- **LiteLLM Proxy:** http://127.0.0.1:4000
- **PostgreSQL Database:** `tango` schema
- **Memory Store:** Persistent three-layer memory system
- **MCP Servers:** 6 servers, 167 tools
- **Python Environment:** `/opt/Project-Tango/backend/venv`
- **Environment File:** `/opt/Project-Tango/.env`

---

## Security Constraints

All fleet members (including Tier 0) share these hard blocks:

### Destructive Operations
- ❌ `rm -rf` on root/home
- ❌ `mkfs`, `dd`, fork bombs
- ❌ `shutdown`, `reboot`, `halt` (except crisis mode)
- ❌ `chmod 777`

### Package Management
- ❌ Direct package installs without approval
- ✅ The Architect can install with documented rationale

### Git Safety
- ❌ Push to main branch without confirmation
- ❌ Modify AGENTS.md without human approval
- ❌ Commit .env files
- ⚠️ Confirmation required for all git push operations

### Service Protection
- ❌ Restart self (own service)
- ⚠️ Critical services require confirmation: caddy, cloudflared, postgresql, tailscaled

### Rate Limiting
- 10 commands per minute per user (applies to command tier too)

---

## Hierarchy Change Protocol

**Authority:** Human operator (themightymaven) + The Architect

Changes to this hierarchy require:
1. **Proposal:** The Architect or human operator proposes change
2. **Review:** Both The Architect and human operator review impact
3. **Documentation:** Change is documented with rationale
4. **Implementation:** Configuration files updated
5. **Notification:** All fleet members notified
6. **Wiki Update:** This document updated
7. **Audit Trail:** Change logged in CHANGELOG.md

**Multi-Agent Coordination:**
- Response scoring based on expertise keywords (Very high threshold: 0.9 - rarely responds)
- Turn-taking with cooldown timers (60s - longer than other agents)
- Addressed agent filter (others stay silent)
- **Excluded from senior-staff-meeting by design** (observer role)
- Observes but does not participate in multi-agent channels

**Recent Changes:**
- **2026-08-18:** Initial hierarchy codification
  - The Architect elevated to Tier 0 (co-equal with Admiral)
  - Dr. Voss elevated to Tier 1 (Executive with crisis authority)
  - The Proctor codified with meta-authority at Tier 2
  - Upgrade propagation protocol established
- **2026-08-18:** The Proctor role expanded to Silent Observer & Performance Optimization Authority
  - Silent observation of all agent interactions
  - Performance monitoring and statistical analysis
  - Dedicated delegation and analysis channels created
  - Daily/weekly/monthly performance reporting
  - Optimization proposal delegation to The Architect

---

## Contact & Authorization

**Human Authority:** EdStratum Labs (themightymaven)  
**Discord ID:** 1075596247966167131

**For:**
- Tier changes
- Crisis authority invocation
- Architecture decisions (consult with The Architect)
- Emergency overrides
- AGENTS.md modifications

---

**END OF FLEET HIERARCHY**  
**Version:** 1.0  
**Effective:** 2026-08-18
