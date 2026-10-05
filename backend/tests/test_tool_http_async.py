"""Voice tools must not block the LiveKit job event loop.

The same loop reads microphone audio, runs VAD, and pushes TTS frames. A
synchronous HTTP call inside an async function tool freezes all of that for
the length of the request (up to 75 s for web_search before this fix), which
shows up as mid-speech cutouts and "inference is slower than realtime".
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

import mintlify_tools
import search_tools
import wiki_tools

BACKEND = Path(__file__).resolve().parents[1]
SLOW_RESPONSE_SECONDS = 0.3


def test_no_synchronous_httpx_client_in_tool_modules() -> None:
    offenders = [
        path.name
        for path in sorted(BACKEND.glob("*_tools.py"))
        if "httpx.Client(" in path.read_text()
    ]
    assert offenders == [], f"use httpx.AsyncClient in voice tools: {offenders}"


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    delay: float = 0.0,
) -> list[httpx.Request]:
    """Route every AsyncClient created by the tools through a mock transport."""
    seen: list[httpx.Request] = []

    async def async_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if delay:
            await asyncio.sleep(delay)
        return handler(request)

    real_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(async_handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return seen


async def _ticks_while(coro: Any) -> tuple[Any, int]:
    """Run *coro* while a 10 ms ticker counts how often the loop stays free."""
    ticks = 0
    done = asyncio.Event()

    async def ticker() -> None:
        nonlocal ticks
        while not done.is_set():
            await asyncio.sleep(0.01)
            ticks += 1

    ticker_task = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        done.set()
        await ticker_task
    return result, ticks


def _sse(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        text=f"event: message\ndata: {json.dumps(payload)}\n\n",
        headers={"content-type": "text/event-stream"},
    )


def _mcp_text(text: str) -> httpx.Response:
    return _sse({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}})


@pytest.mark.asyncio
async def test_web_search_is_async_and_keeps_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://litellm.test:4000")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "google.serper.dev":
            return httpx.Response(
                200,
                json={"organic": [{"title": "T", "snippet": "S", "link": "https://example.com"}]},
            )
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Summary."}}]})

    seen = _install_transport(monkeypatch, handler, delay=SLOW_RESPONSE_SECONDS)
    tool = search_tools.SEARCH_TOOLS[0]

    result, ticks = await _ticks_while(tool(query="tango"))

    assert result == "Summary.\n\nSources: https://example.com"
    assert len(seen) == 2
    # Two 0.3 s requests: a blocking client would allow ~0 ticks.
    assert ticks >= 20


@pytest.mark.asyncio
async def test_web_search_falls_back_to_x5_when_x6_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "google.serper.dev":
            return httpx.Response(200, json={"organic": [{"title": "T", "snippet": "S"}]})
        model = json.loads(request.content)["model"]
        models.append(model)
        if model == search_tools.DEFAULT_SEARCH_MODEL:
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "From X5."}}]})

    _install_transport(monkeypatch, handler)
    result = await search_tools.SEARCH_TOOLS[0](query="tango")

    assert result == "From X5."
    assert models == [search_tools.DEFAULT_SEARCH_MODEL, search_tools.FALLBACK_SEARCH_MODEL]


@pytest.mark.asyncio
async def test_wiki_tools_are_async_and_keep_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OUTLINE_API_KEY", "test-key")
    monkeypatch.setenv("OUTLINE_BASE_URL", "https://wiki.test")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        if request.url.path == "/api/documents.search":
            return httpx.Response(
                200,
                json={"data": [{"context": "<b>Flux</b> notes", "document": {"id": "d1", "title": "STT"}}]},
            )
        assert request.url.path == "/api/documents.info"
        return httpx.Response(200, json={"data": {"title": "STT", "text": "# Heading\n**Body**"}})

    _install_transport(monkeypatch, handler, delay=SLOW_RESPONSE_SECONDS)
    search_wiki, get_wiki_document = wiki_tools.WIKI_TOOLS

    found, ticks = await _ticks_while(search_wiki(query="flux"))
    assert found == "Found 1 document(s) in the EL Wiki:\n- STT: Flux notes (id: d1)"
    assert ticks >= 10

    document = await get_wiki_document(document_id="d1")
    assert document == "Document: STT\n\nHeading\nBody"


@pytest.mark.asyncio
async def test_wiki_request_failure_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLINE_API_KEY", "test-key")
    _install_transport(monkeypatch, lambda _request: httpx.Response(500))

    result = await wiki_tools.WIKI_TOOLS[0](query="flux")

    assert result == "EL Wiki search request failed. The wiki may be unreachable."


@pytest.mark.asyncio
async def test_mintlify_tools_are_async_and_keep_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINTLIFY_BASE_URL", "https://docs.test")
    monkeypatch.setattr(mintlify_tools, "_cached_tool_names", None)
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/mcp"
        body = json.loads(request.content)
        calls.append(body)
        method = body.get("method")
        if method in {"initialize", "notifications/initialized"}:
            return _sse({"jsonrpc": "2.0", "id": body.get("id"), "result": {}})
        if method == "tools/list":
            tools = [{"name": "search_site"}, {"name": "query_docs_filesystem_site"}]
            return _mcp_text(json.dumps(tools))
        name = body["params"]["name"]
        if name == "search_site":
            return _mcp_text("Quickstart: /quickstart")
        assert name == "query_docs_filesystem_site"
        assert body["params"]["arguments"] == {"command": "cat /quickstart.mdx"}
        return _mcp_text("Quickstart page body")

    _install_transport(monkeypatch, handler, delay=SLOW_RESPONSE_SECONDS / 3)
    search_docs, read_doc = mintlify_tools.MINTLIFY_TOOLS

    found, ticks = await _ticks_while(search_docs(query="setup"))
    assert found == "Quickstart: /quickstart"
    # discovery (3 posts) + call (3 posts) at 0.1 s each
    assert ticks >= 20

    page = await read_doc(page_path="quickstart")
    assert page == "Quickstart page body"
    tool_names = [c["params"]["name"] for c in calls if c.get("method") == "tools/call"]
    assert tool_names == ["search_site", "query_docs_filesystem_site"]
