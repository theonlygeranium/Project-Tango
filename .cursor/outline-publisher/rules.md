# Outline Publisher

Publish project documentation to the Outline wiki. Keep any project's Outline collection current, coherent, private, and easy to read. Treat the wiki as a curated operating narrative, not a transcript archive.

This skill is **collection-agnostic**. It does not hardcode any project, collection ID, or document map. Instead, it reads a per-project JSON config file that declares which Outline collection to target, which documents exist, and the privacy contract. This lets you use the same skill for standardsmapper, vinifera, Project Tango, or any future project without modification.

## How it works in Cursor

Unlike the WRITER Agent version (which used a Python script with an SSH tunnel and macOS Keychain), Cursor has **direct MCP access** to the Outline instance via the `outline` MCP server configured in `.cursor/mcp.json`. The MCP server provides 20 tools (`list_collections`, `list_documents`, `create_document`, `update_document`, `fetch`, `create_comment`, `list_users`, `list_templates`, etc.) with authentication handled automatically by the Bearer token in the config.

**You do not need an SSH tunnel, Keychain, or Python script.** Use MCP tools directly.

## Config files

Each project has a JSON config file in `/opt/Project-Tango/.cursor/outline-publisher/config/` (e.g., `standardsmapper-map.json`). Each config file declares:

- `workspace_url` — The Outline workspace URL (e.g., `https://wiki.edstratumlabs.ai`)
- `api_base_url` — Outline API base URL (e.g., `http://127.0.0.1:3101/api`) — not needed for MCP, kept for reference
- `collection` — Target collection ID, name, privacy constraints, and membership limits
- `documents` — Canonical document title → ID map (populated as pages are created)
- `vault_root_title` — Title of the secure vault root page (or `null` if the project has no vault)
- `update_log_title` — Title of the change log document (or `null` if the project has no change log)

See `config/example-map.json` for a template. Copy it, rename it for your project, and fill in the values.

## When to use

- The user asks to publish, update, sync, or hand off project knowledge to an Outline wiki
- The user asks to document project status, architecture, delivery, operations, or governance in the wiki
- The user asks to update a project's wiki collection after completing work
- The user asks to create or update canonical documentation pages in EL Wiki
- Triggers: "publish to wiki", "update outline", "sync to EL Wiki", "publish to collection", "document in the wiki"

## Required workflow

1. Read the project's `AGENTS.md` and continuity/session material. At minimum inspect `CONTINUITY_BRIEF.md`, `README.md`, `CHANGELOG.md`, and `docs/agent-workflow.md` when present.
2. Identify the correct config file for the target project. If none exists, create one from `config/example-map.json`.
3. Run the read-only preflight (see "Privacy preflight" below).
4. **Stop** if collection identity or permission differs from its configured privacy contract, membership exceeds the configured limits, any public share exists, a mapped document is missing, or a title resolves ambiguously.
5. Distill the session into page-sized updates. Prefer updating existing canonical pages over creating new pages.
6. Preview every write — show the user what will change before applying.
7. Apply approved, in-scope writes.
8. Append one entry to the project's Change Log (if configured).
9. Run the preflight again and report exactly which pages changed.

## Privacy preflight (replaces `publish.py verify`)

Before any write, perform these checks using MCP tools:

1. Call `list_collections` or `fetch` to verify the collection name matches the config's `collection.name`.
2. Verify `collection.sharing` is disabled if `sharing_must_be_disabled` is `true` in the config.
3. Verify `collection.permission` matches `required_permission` if set.
4. Call `list_documents` on the collection and verify every mapped document title in `config.documents` exists and its ID matches.
5. Check for published shares — if any exist, stop and report.
6. Report: document count, membership count, active user count, public share count.

If any check fails, **stop and report**. Do not proceed with writes.

## Editorial model

Write the collection as a succinct story:

- Start with what the project is and where it stands.
- Explain how the product works before how it is implemented.
- Separate architecture, delivery, operations, and security.
- Put current truth in canonical pages; put chronology in the update log and archives.
- Use tables for exact mappings, callouts for risks, Mermaid only where relationships materially benefit, and code blocks for commands or contracts.
- Remove repetition. Link to the canonical page instead of restating it.
- Distinguish `implemented`, `CI-verified`, `deployed`, `live-verified`, `pending`, and `blocked`.
- Include dates and exact revisions for time-sensitive evidence.

Use the templates in `templates/` as drafting contracts, not as prose to copy verbatim.

## Routing rules

- Product purpose, personas, workflows, and features → product pages.
- Runtime components, data model, tenancy, integrations, and routes → architecture pages.
- Branches, CI, promotion, deployments, activation gates, and rollback → delivery/operations pages.
- Current state and next actions → status page.
- Decisions with durable consequences → decision/architecture page plus source ADR link.
- Session chronology → update log.
- Raw historical continuity → archive page only when it has unique evidence.
- Credentials and secret values → `Secure Operations Vault` only (if the project config declares one).
- Cross-project server and access mechanics → a separate companion collection (if configured).

Do not create a new top-level section for a single session. Create a page only when the content has a durable audience and no canonical home.

## MCP tool mapping

| Operation | MCP tool | Notes |
|---|---|---|
| Verify collection | `list_collections` or `fetch` | Check name, permission, sharing |
| List documents | `list_documents` | Pass collection ID |
| Get document content | `fetch` | Pass document ID or share ID |
| Create document | `create_document` | Use `parentDocumentId` for child pages |
| Update document | `update_document` | Preserve title unless renaming intentionally |
| List users | `list_users` | For membership/active-user preflight |
| Create comment | `create_comment` | For inline annotations if needed |
| List templates | `list_templates` | If the collection uses Outline templates |

## Secrets and vault rules

- Never print or summarize credential values.
- Never pass secret text directly as a command-line argument or into document content.
- For a vault write, target only the vault root or one of its direct children.
- Do not add or alter credentials unless the user explicitly asks.
- Treat "private wiki" as a permission claim that must be verified each run.
- Keep credentials out of the Change Log; log only that the vault inventory was refreshed.

## Guardrails

- **Default is dry-run.** Show the user what will change before applying any write. Only apply after explicit approval.
- Do not delete documents.
- Do not change collection permissions automatically.
- Do not publish repository secrets, `.env` contents, private keys, tokens, or credential envelopes outside the vault.
- Do not use current hosted responses as proof of deployment activation.
- Do not infer that a GitHub check, deploy workflow, or static response proves production readiness.
- Preserve Outline revision history by updating documents rather than replacing their identity.
- Verify collection privacy before every publishing session, not just the first.

## Setting up a new project

1. Copy `config/example-map.json` to `config/<project>-map.json`.
2. Fill in the collection ID, name, and privacy constraints from the Outline workspace (use `list_collections` MCP tool to find the collection).
3. Leave `documents` empty initially; populate it as you create canonical pages (use `list_documents` to discover IDs).
4. Set `vault_root_title` and `update_log_title` if the project needs them, or `null` if not.
5. Run the privacy preflight (described above) to confirm the collection is accessible and private.

## Templates

Templates are in `/opt/Project-Tango/.cursor/outline-publisher/templates/`. Use them as drafting contracts:

- `status-snapshot.md` — Current state and roadmap page
- `session-continuity.md` — Session outcome and wiki routing
- `update-log.md` — Dated change log entry format
- `knowledge-base-updates.md` — Change log page header

## Key differences from the WRITER Agent version

1. **No SSH tunnel** — MCP tools call the Outline API directly. The `ssh_host` and `api_base_url` fields in config files are kept for reference but not used.
2. **No macOS Keychain** — Authentication is handled by the Bearer token in `.cursor/mcp.json`. The `keychain` section in config files is kept for reference but not used.
3. **No `publish.py` script** — All operations use MCP tools directly. The workflow (verify → draft → preview → apply → log) is the same, but executed through tool calls rather than a Python CLI.
4. **Dry-run is judgment-enforced, not code-enforced** — The script enforced dry-run-by-default in code. Without the script, you must show the user what will change and wait for approval before applying. This is a guardrail, not a suggestion.
5. **Privacy preflight is manual** — The script's `verify` command programmatically checked permissions, memberships, and shares. Without the script, you must perform these checks using MCP tools before any write. Follow the "Privacy preflight" section above.
