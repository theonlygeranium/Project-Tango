"""EL Wiki (Outline) search and retrieval tools for Project Tango voice agents.

Provides function_tools that search the EL Wiki (a self-hosted Outline instance)
and retrieve full document content. This lets any persona look up project
knowledge, documentation, and decisions stored in the wiki during a live
voice conversation.

The tools call the Outline RPC-style API directly via httpx. Authentication
uses a Bearer API token stored in the OUTLINE_API_KEY environment variable.
The base URL defaults to the EdStratum Labs wiki but is configurable.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Annotated

import httpx
from livekit.agents.llm import function_tool

logger = logging.getLogger("project-tango.wiki-tools")

WIKI_TOOLS = []


def register_tool(func):
    WIKI_TOOLS.append(func)
    return func


def _get_outline_config() -> tuple[str, str]:
    """Return (base_url, api_key) for the Outline wiki instance."""
    base_url = os.getenv("OUTLINE_BASE_URL", "https://wiki.edstratumlabs.ai").rstrip("/")
    api_key = os.getenv("OUTLINE_API_KEY", "")
    return base_url, api_key


def _outline_request(base_url: str, api_key: str, method: str, body: dict) -> dict | None:
    """Make a POST request to the Outline RPC API and return the JSON response."""
    url = f"{base_url}/api/{method}"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        logger.warning("Outline API call failed method=%s error=%s", method, exc)
        return None


def _strip_html(text: str) -> str:
    """Remove HTML tags from Outline search context (highlight <b> tags)."""
    return re.sub(r"<[^>]+>", "", text)


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting that would sound awkward when spoken."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text


@register_tool
@function_tool
async def search_wiki(
    query: Annotated[str, "The search query to find documents in the EL Wiki."],
) -> str:
    """Search the EL Wiki (Outline) for documents matching the query.

    Use this tool when the user asks about project documentation, architecture,
    decisions, runbooks, or any knowledge stored in the EL Wiki. Returns
    document titles, snippets, and IDs for the most relevant results.
    """
    base_url, api_key = _get_outline_config()
    if not api_key:
        return "EL Wiki search is not configured. Set OUTLINE_API_KEY in the environment to enable it."

    result = _outline_request(
        base_url, api_key, "documents.search", {"query": query, "limit": 5}
    )
    if result is None:
        return "EL Wiki search request failed. The wiki may be unreachable."

    # Outline documents.search returns data as a list of {ranking, context, document} objects
    data = result.get("data", [])
    if not isinstance(data, list):
        return f"Unexpected response format from EL Wiki search for '{query}'."

    if not data:
        return f"No documents found in the EL Wiki for '{query}'."

    parts: list[str] = []
    for item in data:
        doc = item.get("document", {}) if isinstance(item, dict) else {}
        title = doc.get("title", "Untitled")
        # Use the search context snippet if available, fall back to document text
        snippet = item.get("context", "") if isinstance(item, dict) else ""
        if not snippet:
            snippet = doc.get("text", "")
        snippet = _strip_html(snippet)
        if len(snippet) > 300:
            snippet = snippet[:297] + "..."
        doc_id = doc.get("id", "")
        parts.append(f"- {title}: {snippet} (id: {doc_id})")

    return f"Found {len(data)} document(s) in the EL Wiki:\n" + "\n".join(parts)


@register_tool
@function_tool
async def get_wiki_document(
    document_id: Annotated[str, "The document ID returned from a search_wiki result."],
) -> str:
    """Retrieve the full content of a specific EL Wiki document by its ID.

    Use this after search_wiki returns a document ID and you need the complete
    document content to answer the user's question in detail.
    """
    base_url, api_key = _get_outline_config()
    if not api_key:
        return "EL Wiki is not configured. Set OUTLINE_API_KEY in the environment to enable it."

    result = _outline_request(
        base_url, api_key, "documents.info", {"id": document_id}
    )
    if result is None:
        return "EL Wiki document retrieval failed. The wiki may be unreachable."

    data = result.get("data", {})
    if not isinstance(data, dict):
        return "Unexpected response format from EL Wiki document retrieval."

    title = data.get("title", "Untitled")
    # Outline stores document content in the 'text' field (markdown), not 'body'
    content = data.get("text", "") or data.get("body", "")

    if not content:
        return f"Document '{title}' was found but has no readable content."

    content = _strip_markdown(content)

    # Truncate very long documents to keep the LLM context manageable
    # for voice responses (approximately 4000 chars)
    max_chars = 4000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[Document truncated. Use search_wiki for more specific queries.]"

    return f"Document: {title}\n\n{content}"
