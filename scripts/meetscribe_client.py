"""
MeetScribe Client — Meeting Corpus Integration for Discord Bots
================================================================
Connects Discord bots to the MeetScribe Meeting Corpus REST API and
receives webhook notifications when new meeting notes are available.

Architecture:
  1. MeetScribeClient — async HTTP client for the MeetScribe REST API
     - query_corpus(): RAG question answering across meeting corpus
     - search_sessions(): full-text search across titles, notes, transcripts
     - list_sessions(): list sessions with date/status filters
     - get_session(): fetch session metadata
     - get_session_notes(): fetch AI summary, action items, key decisions
     - get_session_transcript(): fetch final transcript segments
     - get_memory_status(): check vector index status
  2. MeetScribeWebhookCache — local cache of session metadata
     - Receives notes.completed webhooks and stores session metadata
     - On bot startup, bootstraps cache via GET /v1/sessions
     - Enables instant responses for common queries without API round-trip

Configuration (environment variables):
    MEETSCRIBE_API_URL       — Base URL for MeetScribe API (default: https://meetscribe.jgeronimo.com/api)
    MEETSCRIBE_API_KEY      — Bearer token with ms_live_ prefix (required)
    MEETSCRIBE_WEBHOOK_SECRET — HMAC signing secret for webhook verification
    MEETSCRIBE_CACHE_PATH   — Path to local cache JSON file (default: /opt/Project-Tango/data/meetscribe_cache.json)
    MEETSCRIBE_ENABLED      — Enable/disable integration (default: true)

Usage:
    from meetscribe_client import MeetScribeClient, MeetScribeWebhookCache

    client = MeetScribeClient()
    result = await client.query_corpus("What was decided about the Q3 roadmap?")

    cache = MeetScribeWebhookCache()
    await cache.bootstrap(client)
    await cache.handle_webhook(payload)
    sessions = cache.list_recent_sessions(limit=10)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("schubert-bot.meetscribe")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "https://meetscribe.jgeronimo.com/api"
DEFAULT_CACHE_PATH = "/opt/Project-Tango/data/meetscribe_cache.json"
DEFAULT_TIMEOUT = 30.0
MAX_CACHE_SESSIONS = 500
BOOTSTRAP_LIMIT = 200


def _is_enabled() -> bool:
    return os.environ.get("MEETSCRIBE_ENABLED", "true").lower() not in {
        "0", "false", "no", "off",
    }


def _get_api_url() -> str:
    return os.environ.get("MEETSCRIBE_API_URL", DEFAULT_API_URL).rstrip("/")


def _get_api_key() -> str:
    return os.environ.get("MEETSCRIBE_API_KEY", "")


def _get_webhook_secret() -> str:
    return os.environ.get("MEETSCRIBE_WEBHOOK_SECRET", "")


def _get_cache_path() -> str:
    return os.environ.get("MEETSCRIBE_CACHE_PATH", DEFAULT_CACHE_PATH)


# ---------------------------------------------------------------------------
# MeetScribe API Client
# ---------------------------------------------------------------------------

class MeetScribeClient:
    """
    Async HTTP client for the MeetScribe Meeting Corpus REST API.

    All methods are async and return parsed JSON responses.
    Authentication uses a Bearer token with the ms_live_ prefix.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._api_url = api_url or _get_api_url()
        self._api_key = api_key or _get_api_key()
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._api_url,
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.request(
                method, path, json=json_body, params=params
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "MeetScribe API error %s %s: HTTP %s — %s",
                method, path, exc.response.status_code,
                exc.response.text[:500],
            )
            return {
                "error": f"HTTP {exc.response.status_code}",
                "detail": exc.response.text[:500],
            }
        except httpx.RequestError as exc:
            logger.error("MeetScribe API request error %s %s: %s", method, path, exc)
            return {"error": str(exc)}

    # -- RAG Question Answering --

    async def query_corpus(
        self, question: str, limit: int = 5
    ) -> dict[str, Any]:
        """
        Ask a natural language question across the meeting corpus.
        Returns a grounded answer with cited sources.

        Returns:
            {
                "answer": "...",
                "sources": [
                    {"session_id": ..., "title": ..., "score": ..., "snippet": ...},
                    ...
                ]
            }
        """
        return await self._request(
            "POST", "/v1/sessions/query",
            json_body={"question": question, "limit": limit},
        )

    # -- Full-text Search --

    async def search_sessions(
        self, query: str, limit: int = 10
    ) -> dict[str, Any]:
        """Search across titles, notes, and transcripts."""
        return await self._request(
            "POST", "/v1/sessions/search",
            json_body={"query": query, "limit": limit},
        )

    # -- Session Listing --

    async def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """List sessions with optional date/status filters."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return await self._request("GET", "/v1/sessions", params=params)

    # -- Session Detail --

    async def get_session(self, session_id: int | str) -> dict[str, Any]:
        """Fetch session metadata."""
        return await self._request("GET", f"/v1/sessions/{session_id}")

    async def get_session_notes(self, session_id: int | str) -> dict[str, Any]:
        """Fetch AI summary, action items, and key decisions."""
        return await self._request("GET", f"/v1/sessions/{session_id}/notes")

    async def get_session_transcript(self, session_id: int | str) -> dict[str, Any]:
        """Fetch final transcript segments."""
        return await self._request("GET", f"/v1/sessions/{session_id}/transcript")

    async def export_session(
        self, session_id: int | str, format: str = "md"
    ) -> dict[str, Any]:
        """Export session as md/txt/srt/vtt/pdf/docx."""
        return await self._request(
            "GET", f"/v1/sessions/{session_id}/export",
            params={"format": format},
        )

    # -- Memory Index --

    async def get_memory_status(self) -> dict[str, Any]:
        """Check vector memory index status (chunk/session count)."""
        return await self._request("GET", "/v1/memory/status")


# ---------------------------------------------------------------------------
# Webhook Cache — Local session metadata store
# ---------------------------------------------------------------------------

class MeetScribeWebhookCache:
    """
    Local cache of MeetScribe session metadata.

    Receives notes.completed webhooks and stores session metadata locally.
    On bot startup, bootstraps the cache via GET /v1/sessions.
    Enables instant responses for common queries without an API round-trip.
    """

    def __init__(self, cache_path: str | None = None):
        self._cache_path = cache_path or _get_cache_path()
        self._sessions: dict[int, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        async with self._lock:
            if self._loaded:
                return
            try:
                if os.path.isfile(self._cache_path):
                    with open(self._cache_path, "r") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            self._sessions = {
                                int(k): v for k, v in data.items()
                            }
                            logger.info(
                                "MeetScribe cache loaded: %d sessions",
                                len(self._sessions),
                            )
            except Exception as exc:
                logger.warning("MeetScribe cache load failed: %s", exc)
            self._loaded = True

    async def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            # Keep only the most recent sessions
            if len(self._sessions) > MAX_CACHE_SESSIONS:
                sorted_sessions = sorted(
                    self._sessions.items(),
                    key=lambda x: x[1].get("started_at", ""),
                    reverse=True,
                )
                self._sessions = dict(sorted_sessions[:MAX_CACHE_SESSIONS])
            with open(self._cache_path, "w") as f:
                json.dump(
                    {str(k): v for k, v in self._sessions.items()},
                    f, indent=2, default=str,
                )
        except Exception as exc:
            logger.warning("MeetScribe cache save failed: %s", exc)

    async def bootstrap(self, client: MeetScribeClient) -> int:
        """Fetch recent sessions from the API to populate the cache on startup."""
        await self._load()
        try:
            result = await client.list_sessions(limit=BOOTSTRAP_LIMIT)
            if isinstance(result, dict) and "error" in result:
                logger.warning(
                    "MeetScribe cache bootstrap failed: %s",
                    result.get("error"),
                )
                return 0
            sessions = result if isinstance(result, list) else result.get("sessions", [])
            async with self._lock:
                for session in sessions:
                    sid = session.get("id")
                    if sid is not None:
                        self._sessions[int(sid)] = session
            await self._save()
            logger.info(
                "MeetScribe cache bootstrapped: %d sessions", len(sessions)
            )
            return len(sessions)
        except Exception as exc:
            logger.warning("MeetScribe cache bootstrap error: %s", exc)
            return 0

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """
        Process a notes.completed webhook payload.
        Stores session metadata in the local cache.

        Returns True if the payload was processed successfully.
        """
        await self._load()
        event = payload.get("event")
        if event != "notes.completed":
            return False

        data = payload.get("data", {})
        session_id = data.get("session_id")
        if session_id is None:
            return False

        async with self._lock:
            self._sessions[int(session_id)] = {
                "id": session_id,
                "title": data.get("title", "Untitled"),
                "status": data.get("status", "completed"),
                "started_at": data.get("started_at"),
                "duration_seconds": data.get("duration_seconds"),
                "summary": data.get("summary", ""),
                "action_items": data.get("action_items", []),
                "key_decisions": data.get("key_decisions", []),
                "webhook_received_at": datetime.now(timezone.utc).isoformat(),
            }

        await self._save()
        logger.info(
            "MeetScribe webhook cached: session %s — %s",
            session_id, data.get("title", "Untitled"),
        )
        return True

    def list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recently cached sessions."""
        sessions = sorted(
            self._sessions.values(),
            key=lambda x: x.get("started_at", "")
            or x.get("webhook_received_at", ""),
            reverse=True,
        )
        return sessions[:limit]

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        """Get a cached session by ID."""
        return self._sessions.get(session_id)

    def search_cache(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Simple text search across cached session titles and summaries.
        For deeper search, use the API's search_sessions() method.
        """
        query_lower = query.lower()
        results = []
        for session in self._sessions.values():
            title = session.get("title", "").lower()
            summary = session.get("summary", "").lower()
            if query_lower in title or query_lower in summary:
                results.append(session)
        return results[:limit]

    def get_stats(self) -> dict[str, int]:
        """Return cache statistics."""
        return {
            "total_sessions": len(self._sessions),
            "with_summaries": sum(
                1 for s in self._sessions.values() if s.get("summary")
            ),
            "with_action_items": sum(
                1 for s in self._sessions.values()
                if s.get("action_items")
            ),
        }


# ---------------------------------------------------------------------------
# Webhook Signature Verification
# ---------------------------------------------------------------------------

def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Verify the HMAC-SHA256 signature of a MeetScribe webhook payload.

    The signature is sent in the X-MeetScribe-Signature header as
    sha256=<hex_digest>.
    """
    secret = _get_webhook_secret()
    if not secret:
        logger.warning("MeetScribe webhook secret not configured")
        return False

    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


# ---------------------------------------------------------------------------
# Formatting helpers for Discord
# ---------------------------------------------------------------------------

def format_corpus_answer(result: dict[str, Any]) -> str:
    """
    Format a MeetScribe RAG query result for Discord display.
    Returns a markdown-formatted string with the answer and cited sources.
    """
    if "error" in result:
        return f"❌ MeetScribe query failed: {result.get('error', 'unknown error')}"

    answer = result.get("answer", "I couldn't find information about that.")
    sources = result.get("sources", [])

    if not sources:
        return answer

    source_lines = []
    for src in sources[:5]:
        title = src.get("title", "Untitled session")
        score = src.get("score", 0)
        session_id = src.get("session_id", "?")
        date = src.get("started_at", src.get("date", ""))
        if date:
            date_str = date[:10] if len(date) >= 10 else date
        else:
            date_str = ""
        source_lines.append(
            f"  • **{title}** ({date_str}) — score: {score:.2f} [#{session_id}]"
        )

    return f"{answer}\n\n**Sources:**\n" + "\n".join(source_lines)


def format_session_list(sessions: list[dict[str, Any]]) -> str:
    """Format a list of sessions for Discord display."""
    if not sessions:
        return "No meetings found."

    lines = []
    for session in sessions[:10]:
        title = session.get("title", "Untitled")
        session_id = session.get("id", "?")
        date = session.get("started_at", "")
        if date:
            date_str = date[:10] if len(date) >= 10 else date
        else:
            date_str = "—"
        status = session.get("status", "")
        lines.append(f"  • [{date_str}] **{title}** (#{session_id}) — {status}")

    return "\n".join(lines)


def format_session_notes(notes: dict[str, Any]) -> str:
    """Format session notes (summary, action items, decisions) for Discord."""
    if "error" in notes:
        return f"❌ Failed to fetch notes: {notes.get('error', 'unknown')}"

    parts = []

    summary = notes.get("summary", "")
    if summary:
        parts.append(f"**Summary:**\n{summary[:1500]}")

    action_items = notes.get("action_items", [])
    if action_items:
        items_text = "\n".join(
            f"  ☐ {item}" for item in action_items[:15]
        )
        parts.append(f"**Action Items:**\n{items_text}")

    key_decisions = notes.get("key_decisions", [])
    if key_decisions:
        decisions_text = "\n".join(
            f"  ⚡ {decision}" for decision in key_decisions[:10]
        )
        parts.append(f"**Key Decisions:**\n{decisions_text}")

    return "\n\n".join(parts) if parts else "No notes available for this session."
