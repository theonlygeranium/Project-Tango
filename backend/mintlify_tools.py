"""Mintlify documentation search and retrieval tools for Project Tango voice agents.

Provides function_tools that search and read the EdStratum Labs Mintlify
documentation site via its MCP (Model Context Protocol) endpoint. This lets
any persona look up product documentation, API references, and guides during
a live voice conversation.

The tools communicate with the Mintlify MCP server using JSON-RPC 2.0 over
HTTP. The MCP endpoint is at {MINTLIFY_BASE_URL}/mcp and requires no
credentials for read-only access. Responses use Server-Sent Events (SSE)
format and are parsed to extract text content.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated

import httpx
from livekit.agents.llm import function_tool

logger = logging.getLogger("project-tango.mintlify-tools")

MINTLIFY_TOOLS = []

# MCP protocol version supported by the Mintlify server
_MCP_PROTOCOL_VERSION = "2025-06-18"


def register_tool(func):
    MINTLIFY_TOOLS.append(func)
    return func


def _get_mintlify_base_url() -> str:
    return os.getenv("MINTLIFY_BASE_URL", "https://edstratumlabs.mintlify.site").rstrip("/")


def _mcp_call(base_url: str, method: str, params: dict | None = None, *, request_id: int = 1) -> str | None:
    """Make a single MCP JSON-RPC call and extract text from the SSE response.

    Each call is stateless from the HTTP perspective — the Mintlify MCP server
    handles each request independently. We include the initialize handshake
    in every call to ensure the session is ready, then send the actual method.
    """
    mcp_url = f"{base_url}/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            # Step 1: Initialize the MCP session
            init_response = client.post(
                mcp_url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "project-tango", "version": "1.0"},
                    },
                },
            )
            init_response.raise_for_status()

            # Step 2: Send initialized notification (no response expected)
            client.post(
                mcp_url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            # Step 3: Send the actual method call
            payload: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = params

            response = client.post(mcp_url, headers=headers, json=payload)
            response.raise_for_status()

            return _parse_sse_response(response.text)
    except httpx.HTTPError as exc:
        logger.warning("Mintlify MCP call failed method=%s error=%s", method, exc)
        return None


def _parse_sse_response(text: str) -> str | None:
    """Extract text content from an SSE-formatted MCP response."""
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        result = data.get("result", {})
        content_list = result.get("content", [])
        texts: list[str] = []
        for content in content_list:
            if isinstance(content, dict) and content.get("type") == "text":
                texts.append(content.get("text", ""))
        if texts:
            return "\n".join(texts)
    return None


def _discover_tool_names(base_url: str) -> tuple[str | None, str | None]:
    """Discover the actual search and filesystem tool names from the MCP server.

    Tool names include a site-specific suffix (e.g., 'search_threadmark').
    We discover them dynamically rather than hardcoding.
    """
    mcp_url = f"{base_url}/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            # Initialize
            client.post(
                mcp_url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "project-tango", "version": "1.0"},
                    },
                },
            )
            # Notify initialized
            client.post(
                mcp_url,
                headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            # List tools
            response = client.post(
                mcp_url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            response.raise_for_status()

            tools_text = _parse_sse_response(response.text)
            if not tools_text:
                return None, None

            tools_data = json.loads(tools_text)
            tools = tools_data if isinstance(tools_data, list) else tools_data.get("tools", [])

            search_name = None
            filesystem_name = None
            for tool in tools:
                name = tool.get("name", "")
                if "search" in name and "filesystem" not in name:
                    search_name = name
                elif "filesystem" in name:
                    filesystem_name = name

            return search_name, filesystem_name
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning("Mintlify tool discovery failed: %s", exc)
        return None, None


# Cache discovered tool names to avoid repeated discovery calls
_cached_tool_names: tuple[str | None, str | None] | None = None


def _get_tool_names(base_url: str) -> tuple[str, str]:
    """Get the search and filesystem tool names, discovering them if needed."""
    global _cached_tool_names
    if _cached_tool_names is None or _cached_tool_names[0] is None:
        _cached_tool_names = _discover_tool_names(base_url)
    search_name, fs_name = _cached_tool_names
    return search_name or "search_threadmark", fs_name or "query_docs_filesystem_threadmark"


@register_tool
@function_tool
async def search_docs(
    query: Annotated[str, "The search query to find documentation pages."],
) -> str:
    """Search the EdStratum Labs documentation site for pages matching the query.

    Use this tool when the user asks about product documentation, API references,
    guides, or any published docs content. Returns page titles, links, and content
    snippets for the most relevant results.
    """
    base_url = _get_mintlify_base_url()
    search_name, _ = _get_tool_names(base_url)

    result = _mcp_call(
        base_url,
        "tools/call",
        params={"name": search_name, "arguments": {"query": query}},
        request_id=10,
    )
    if result is None:
        return "Documentation search request failed. The docs site may be unreachable."

    if not result.strip():
        return f"No documentation pages found for '{query}'."

    # Truncate to keep voice response manageable
    max_chars = 3000
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n[Results truncated. Use read_doc for specific page content.]"

    return result


@register_tool
@function_tool
async def read_doc(
    page_path: Annotated[str, "The documentation page path to read (e.g., 'articles/setup' or 'quickstart'). The .mdx extension is added automatically."],
) -> str:
    """Read the full content of a specific documentation page by its path.

    Use this after search_docs returns a page path and you need the complete
    page content to answer the user's question in detail. The path should not
    include the .mdx extension — it is added automatically.
    """
    base_url = _get_mintlify_base_url()
    _, fs_name = _get_tool_names(base_url)

    # Ensure the path starts with / and ends with .mdx
    if not page_path.startswith("/"):
        page_path = "/" + page_path
    if not page_path.endswith(".mdx"):
        page_path = page_path + ".mdx"

    result = _mcp_call(
        base_url,
        "tools/call",
        params={"name": fs_name, "arguments": {"command": f"cat {page_path}"}},
        request_id=20,
    )
    if result is None:
        return "Documentation page retrieval failed. The docs site may be unreachable."

    if not result.strip():
        return f"Page '{page_path}' was not found or has no readable content."

    # Truncate very long documents for voice context management
    max_chars = 4000
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n[Document truncated. Use search_docs for more specific queries.]"

    return result
