# Outline Wiki MCP Integration

## Overview

Your EdStratum Labs wiki is now accessible via MCP! The self-hosted Outline instance (v1.9.2) at https://wiki.edstratumlabs.ai is connected via the built-in MCP server.

## Configuration

**MCP Endpoint:** `http://127.0.0.1:3101/mcp` (local access via SSH)  
**Public URL:** `https://wiki.edstratumlabs.ai` (protected by Cloudflare Access)  
**API Key:** `ol_api_0HrC2D96bEAy4wlYB5Mz1CN4P3SKrYYftACiYY`  
**Outline Version:** 1.9.2

## Available Tools (20 Total)

### Collections
- `list_collections` - List all collections with optional search
- `create_collection` - Create a new collection
- `update_collection` - Update collection name, description, icon, color
- `delete_collection` - Delete or archive a collection

### Documents
- `list_documents` - Search documents by content or title
- `list_collection_documents` - Get full hierarchical document tree
- `create_document` - Create from markdown/HTML or template
- `move_document` - Move/reorder documents
- `update_document` - Update with smart patch mode (preserves formatting)
- `delete_document` - Delete or archive a document
- `restore_document` - Restore archived/trashed documents

### Comments
- `list_comments` - List comments on documents
- `create_comment` - Add comments (top-level or replies)
- `update_comment` - Edit comment text or resolve/unresolve threads
- `delete_comment` - Delete comments

### Resources
- `fetch` - Fetch document, collection, user, attachment, or template by ID
- `list_templates` - List available document templates with content
- `list_users` - List workspace users with role/status filters
- `create_attachment` - Get pre-signed upload URL for file attachments

## Key Features

### Smart Document Updates
The `update_document` tool supports 4 edit modes:
- **`patch`** (recommended) - Surgically replace a specific section, preserves rich formatting
- **`replace`** - Replace entire document (loses formatting)
- **`append`** - Add content to end
- **`prepend`** - Add content to beginning

**Always use `patch` mode** to preserve highlights, comments, table widths, and other rich formatting.

### Template Support
- `list_templates` returns full template markdown
- Pass `templateId` to `create_document` to pre-fill from template
- Can modify template text before creating document

### @Mentions
Documents support @mentions using: `@[Display Name](mention://user/userId)`  
Use `list_users` to find user IDs for mentions.

### Attachments
- `create_attachment` provides pre-signed upload URL
- `fetch` with `resource: "attachment"` returns signed download URL
- Attachments can be read/downloaded by agents

## Important Constraints

### Document Content Rules
- **No H1 headings in content** - Title is separate, start with H2 or body text
- **Markdown preferred** - Use `format: "markdown"` (default)
- **HTML supported** - Use `format: "html"` for rich HTML input
- **Full-width sparingly** - Only set `fullWidth: true` when explicitly requested

### Authentication
- **Local endpoint** - `http://127.0.0.1:3101/mcp` works via SSH Remote
- **Public endpoint** - `https://wiki.edstratumlabs.ai/mcp` blocked by Cloudflare Access (403)
- **API key** - Required for all requests, passed as Bearer token

## Setup Status

✅ **MCP team preference enabled** in Outline database  
✅ **API key generated** for jeff@jgeronimo.com (admin)  
✅ **MCP endpoint verified** - Returns 20 tools  
✅ **Cursor config created** - `/opt/Project-Tango/.cursor/mcp.json`

## Activation Steps

### 1. Reload Cursor Window
```
Cmd/Ctrl + Shift + P → "Developer: Reload Window"
```

### 2. Verify in Settings
```
Cursor → Settings → Tools & MCP
```
You should see:
- **context7** - Cursor/Discord documentation
- **outline** - EdStratum Labs wiki (20 tools)

### 3. Test Connection
The MCP server should now be available to AI agents. Try:
- "List all collections in the wiki"
- "Search for documents about [topic]"
- "Show me the document hierarchy in [collection]"

## Usage Examples

### List Collections
```
Use the outline::list_collections tool to see all wiki collections
```

### Search Documents
```
Use outline::list_documents with query "Discord bot" to find relevant docs
```

### Get Document Content
```
Use outline::fetch with resource "document" and id "<doc-id>" to read full content
```

### Create New Document
```
Use outline::create_document with:
- title: "New Document"
- text: "# Introduction\n\nContent here..."
- collectionId: "<collection-id>"
```

### Update Document (Smart Patch)
```
Use outline::update_document with:
- id: "<doc-id>"
- editMode: "patch"
- findText: "## Old Section\n\nOld content..."
- text: "## Updated Section\n\nNew content..."
```

This preserves all formatting in the rest of the document.

## Network Details

### Why Local Endpoint?
Since you connect to Schubert via SSH Remote, Cursor runs on the server itself. The MCP server can reach `127.0.0.1:3101` directly without:
- Cloudflare Access authentication
- External network hops
- VPN tunneling

**Benefits:**
- Lower latency
- API key stays on server
- No Cloudflare Access barrier
- Simpler configuration

### Docker Container
```bash
# Check Outline container status
docker ps | grep outline

# Container: outline (port 127.0.0.1:3101->3000)
# Version: outlinewiki/outline:latest (v1.9.2)
# Healthy: Yes (24 hours uptime)
```

### Dependencies
- **outline-postgres** - PostgreSQL database
- **outline-redis** - Redis cache
- Both healthy and running

## Security Notes

- **API key scope:** User account (jeff@jgeronimo.com, admin role)
- **MCP feature:** Team-level preference, enabled in database
- **Cloudflare Access:** Public URL requires authentication, local endpoint bypasses
- **Bearer token:** Passed in Authorization header, stored in `.cursor/mcp.json`

## Troubleshooting

### If MCP server doesn't appear in Cursor:
1. Disconnect from SSH Remote and reconnect
2. Verify `/opt/Project-Tango/.cursor/mcp.json` exists
3. Check Outline container is running: `docker ps | grep outline`
4. Test endpoint manually:
   ```bash
   curl -X POST http://127.0.0.1:3101/mcp \
     -H "Authorization: Bearer ol_api_0HrC2D96bEAy4wlYB5Mz1CN4P3SKrYYftACiYY" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
   ```

### If tools not available:
- Reload Cursor window
- Check MCP team preference in Outline: should be enabled
- Verify API key is valid and has admin role

## Integration with Discord Bots

The Discord bots (Admiral Schubert, etc.) can now access the wiki via this MCP server. They can:
- Search wiki for project documentation
- Read architecture decisions and runbooks
- Update documentation based on code changes
- Create new documents for new features
- Link to wiki pages in Discord responses

This completes the documentation ecosystem:
- **Context7 MCP** - Live Cursor/Discord API docs
- **Outline MCP** - Internal project knowledge base
- **GitHub MCP** - Code repositories and issues

All accessible to AI agents for comprehensive project context!
