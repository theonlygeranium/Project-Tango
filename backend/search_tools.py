"""Web search tool with Palmyra X6 summarization.

Provides a web_search function_tool that searches the web via the Serper.dev
Google Search API and summarizes the results using writer/palmyra-x6 through
the LiteLLM proxy. The tool is always available to every persona regardless
of the session's conversational LLM model — X6 is used specifically for the
summarization leg, not the conversation.

This mirrors the web_search capability already deployed in the Discord bots
(commit 98353f8), but routes the summarization through Tango's own LiteLLM
proxy and uses X6 as the default summarization model.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Annotated

import httpx
from livekit.agents.llm import function_tool

logger = logging.getLogger("project-tango.search-tools")

# Default model for summarizing search results. Palmyra X6 is the dev-only
# cutting-edge model; it is used here because web search summarization is a
# high-value task that benefits from the strongest available model, and the
# summarization leg is separate from the conversational model so using X6
# here does not affect real-time voice latency.
DEFAULT_SEARCH_MODEL = "writer/palmyra-x6"

# Fallback model if X6 (dev endpoint) is unavailable. Palmyra X5 is the
# production flagship and is stable.
FALLBACK_SEARCH_MODEL = "writer/palmyra-x5"

SEARCH_TOOLS = []


def register_tool(func):
    SEARCH_TOOLS.append(func)
    return func


def _get_litellm_config() -> tuple[str, str]:
    """Return (base_url, api_key) for the LiteLLM proxy."""
    base_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1" if not base_url.endswith("/v1") else base_url
        # Normalize: ensure we have a clean base for appending /chat/completions
        base_url = base_url.rstrip("/v1")
        base_url = f"{base_url}/v1"
    return base_url, os.getenv("LITELLM_MASTER_KEY", "dummy")


def _serper_search(query: str, num_results: int = 5) -> dict:
    """Perform a Google search via the Serper.dev API."""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return {"error": "SERPER_API_KEY is not configured in the .env file."}

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num_results},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        logger.warning("Serper search failed for query=%r: %s", query, exc)
        return {"error": f"Search request failed: {exc}"}


def _summarize_with_x6(query: str, search_results: dict) -> str:
    """Summarize search results using writer/palmyra-x6 via LiteLLM."""
    base_url, api_key = _get_litellm_config()

    # Build a compact representation of the search results for the LLM
    organic = search_results.get("organic", [])
    knowledge_graph = search_results.get("knowledgeGraph", {})
    answer_box = search_results.get("answerBox", {})

    context_parts: list[str] = []
    if answer_box:
        context_parts.append(f"Answer box: {json.dumps(answer_box, ensure_ascii=False)[:500]}")
    if knowledge_graph:
        context_parts.append(f"Knowledge graph: {json.dumps(knowledge_graph, ensure_ascii=False)[:500]}")
    for item in organic[:5]:
        context_parts.append(
            f"- {item.get('title', '')}: {item.get('snippet', '')} ({item.get('link', '')})"
        )

    if not context_parts:
        return "I searched but couldn't find relevant results for that query."

    search_context = "\n".join(context_parts)

    system_prompt = (
        "You are a search result summarizer. Given a user's search query and "
        "the raw search results, produce a concise, accurate summary that "
        "directly answers the query. Cite sources by name when the information "
        "comes from a specific result. Do not hallucinate information that is "
        "not present in the search results. Keep the summary to 2-3 sentences "
        "unless the query requires more detail."
    )

    user_prompt = f"Search query: {query}\n\nSearch results:\n{search_context}\n\nProvide a concise summary answering the query."

    payload = {
        "model": DEFAULT_SEARCH_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 512,
        "temperature": 0.3,
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        logger.warning(
            "X6 summarization failed for query=%r: %s; falling back to %s",
            query,
            exc,
            FALLBACK_SEARCH_MODEL,
        )
        # Fall back to X5 (production) if X6 (dev) fails
        payload["model"] = FALLBACK_SEARCH_MODEL
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc2:
            logger.error("Fallback X5 summarization also failed for query=%r: %s", query, exc2)
            # Last resort: return raw snippets
            snippets = [item.get("snippet", "") for item in organic[:3] if item.get("snippet")]
            return f"Search completed but summarization failed. Top results: {' '.join(snippets)}"


@register_tool
@function_tool
async def web_search(
    query: Annotated[str, "The search query to look up on the web."],
) -> str:
    """Search the web for current information and return a summarized answer.

    Use this tool when the user asks about current events, recent news, or
    any information that may be beyond your training data. The search results
    are summarized by a dedicated summarization model for accuracy.
    """
    serper_key = os.getenv("SERPER_API_KEY")
    if not serper_key:
        return "Web search is not configured. Set SERPER_API_KEY in the environment to enable it."

    search_results = _serper_search(query)
    if "error" in search_results:
        return search_results["error"]

    summary = _summarize_with_x6(query, search_results)

    # Include source URLs for transparency
    organic = search_results.get("organic", [])
    sources = [item.get("link") for item in organic[:3] if item.get("link")]
    if sources:
        summary = f"{summary}\n\nSources: {', '.join(sources)}"

    return summary
