# Outline Publisher Rules - Summary

## ✅ Confirmed: Outline Publisher is Already Set Up!

The Outline Publisher workflow is fully configured at `/opt/Project-Tango/.cursor/outline-publisher/`.

## What the Rules Specify

### Core Purpose
Publish and maintain project documentation in the Outline wiki. Keep collections current, coherent, private, and easy to read. Treat the wiki as a **curated operating narrative**, not a transcript archive.

### Key Features

#### 1. **Collection-Agnostic Design**
- No hardcoded project names or collection IDs
- Each project has its own JSON config file in `config/`
- Same skill works for standardsmapper, vinifera, Project Tango, or any future project

#### 2. **Direct MCP Access** (Cursor Advantage)
Unlike the WRITER Agent version:
- ✅ **No SSH tunnel needed** - MCP tools call Outline API directly
- ✅ **No macOS Keychain** - Authentication via Bearer token in `.cursor/mcp.json`
- ✅ **No Python script** - All operations use MCP tools directly
- Uses 20 Outline MCP tools we just configured

#### 3. **Privacy-First Workflow**
Before every write operation:
1. Verify collection name matches config
2. Verify sharing is disabled (if required)
3. Verify permissions match requirements
4. Check all mapped documents exist
5. Check for published shares (must be none)
6. Report: document count, membership count, active users, shares

**If any check fails → STOP and report. Do not proceed.**

#### 4. **Required Workflow** (7 Steps)
1. **Read** project context (AGENTS.md, CONTINUITY_BRIEF.md, README.md, CHANGELOG.md)
2. **Identify** correct config file for target project
3. **Preflight** - Run read-only privacy checks
4. **Stop** if any privacy/permission violations detected
5. **Distill** session into page-sized updates (prefer updating existing pages)
6. **Preview** - Show user what will change BEFORE applying
7. **Apply** approved writes + append to Change Log + run preflight again

#### 5. **Editorial Model**
Write as a succinct story:
- Product purpose → product pages
- Architecture/data model → architecture pages  
- CI/deployment → delivery/operations pages
- Current state → status page
- Decisions → decision pages + ADR links
- Session chronology → update log
- Credentials → Secure Operations Vault ONLY

**Remove repetition. Link instead of restating.**

### Available Config Files

#### Example Template
`config/example-map.json` - Copy this for new projects

#### Existing Project
`config/standardsmapper-map.json` - Example with:
- Collection ID: `6aa4d303-7ec5-4150-aab7-f02e926ffe83`
- 8 mapped documents (Home, Product, Architecture, Delivery, Governance, Status, Task Receipts, Change Log)
- Privacy: Single user, no sharing, private only

### Available Templates

Located in `templates/`:
- `status-snapshot.md` - Current state and roadmap page
- `session-continuity.md` - Session outcome and wiki routing
- `update-log.md` - Dated change log entry format
- `knowledge-base-updates.md` - Change log page header

**Use as drafting contracts, not prose to copy verbatim.**

### MCP Tool Mapping

| Operation | MCP Tool | Usage |
|-----------|----------|-------|
| Verify collection | `list_collections` or `fetch` | Check name, permission, sharing |
| List documents | `list_documents` | Pass collection ID |
| Get content | `fetch` | Pass document ID or share ID |
| Create document | `create_document` | Use `parentDocumentId` for nesting |
| Update document | `update_document` | Preserve title unless renaming |
| List users | `list_users` | Membership preflight |
| Add comment | `create_comment` | Inline annotations |
| List templates | `list_templates` | If collection uses templates |

### Trigger Phrases

When the user says:
- "publish to wiki"
- "update outline"
- "sync to EL Wiki"
- "publish to collection"
- "document in the wiki"
- "update the wiki after this work"

→ Activate the Outline Publisher workflow

### Critical Guardrails

#### Default is Dry-Run
- ✅ Show user what will change BEFORE applying
- ✅ Wait for explicit approval
- ❌ Do NOT auto-apply writes

#### Never Do
- ❌ Delete documents
- ❌ Change collection permissions automatically
- ❌ Publish secrets, .env contents, tokens, credentials outside vault
- ❌ Use hosted responses as proof of deployment
- ❌ Infer production readiness from GitHub checks alone

#### Always Do
- ✅ Verify collection privacy before EVERY session
- ✅ Preserve Outline revision history (update, don't replace)
- ✅ Keep credentials out of Change Log
- ✅ Never print or summarize credential values

### Secrets & Vault Rules

- Never pass secrets as command-line arguments or in document content
- Vault writes target vault root or direct children only
- Don't add/alter credentials unless explicitly asked
- "Private wiki" is a permission claim that must be verified each run
- Log only that vault inventory was refreshed (not credential details)

## Setting Up Project Tango's Config

To enable Outline Publisher for Project Tango:

1. **Copy example config:**
   ```bash
   cp /opt/Project-Tango/.cursor/outline-publisher/config/example-map.json \
      /opt/Project-Tango/.cursor/outline-publisher/config/project-tango-map.json
   ```

2. **Find Project Tango's collection ID:**
   - Use `list_collections` MCP tool
   - Or check wiki at https://wiki.edstratumlabs.ai

3. **Populate config:**
   - Set collection ID and name
   - Set privacy constraints (max users, no sharing, etc.)
   - Leave `documents` empty initially
   - Set `vault_root_title` if needed (or `null`)
   - Set `update_log_title` if needed (or `null`)

4. **Run privacy preflight:**
   - Use MCP tools to verify collection is accessible and private
   - Populate `documents` map as you create canonical pages

## Summary

The Outline Publisher rules provide a **complete, production-ready workflow** for maintaining project documentation in your wiki. It:

- ✅ Uses MCP tools directly (no scripts, tunnels, or Keychain)
- ✅ Enforces privacy checks before every write
- ✅ Requires explicit approval before applying changes (dry-run default)
- ✅ Supports multiple projects with per-project configs
- ✅ Provides templates for consistent documentation
- ✅ Protects secrets with strict vault rules
- ✅ Maintains editorial quality with routing rules

**After reloading Cursor**, I can use these rules automatically when you ask to "publish to wiki" or "update Outline."
