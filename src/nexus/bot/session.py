"""Session management — load, save, and validate conversation sessions.

Sessions are validated against REQUIRED_SESSION_KEYS. load() falls back
to a fresh session on validation failure rather than crashing. save()
refuses to persist invalid sessions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

REQUIRED_SESSION_KEYS = frozenset({"session_id", "bot_id", "channel_id"})


@dataclass
class Session:
    """A conversation session for a single bot/channel pair."""

    session_id: str
    bot_id: str
    channel_id: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""


class SessionManager:
    """Manages conversation session lifecycle with validation."""

    def __init__(
        self,
        storage: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._storage = storage
        self._logger = logger or logging.getLogger(__name__)

    def validate(self, data: dict) -> bool:
        """Check that *data* contains all required session keys."""
        return REQUIRED_SESSION_KEYS.issubset(data.keys())

    async def load(self, session_id: str) -> Session:
        """Load a session by ID. Falls back to a fresh session on failure."""
        if self._storage is None:
            self._logger.debug(
                "No storage configured, returning fresh session for %s", session_id
            )
            return await self.create_fresh()

        try:
            raw = await self._storage.get(session_id)
            if raw is None:
                self._logger.debug(
                    "Session %s not found, returning fresh session", session_id
                )
                return await self.create_fresh()

            data = json.loads(raw) if isinstance(raw, str) else raw
            if not self.validate(data):
                self._logger.warning(
                    "Session %s failed validation, returning fresh session", session_id
                )
                return await self.create_fresh()

            return Session(
                session_id=data["session_id"],
                bot_id=data["bot_id"],
                channel_id=data["channel_id"],
                messages=data.get("messages", []),
                created_at=data.get("created_at", ""),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self._logger.warning(
                "Failed to load session %s: %s, returning fresh session",
                session_id,
                e,
            )
            return await self.create_fresh()

    async def save(self, session: Session) -> None:
        """Save a session. Refuses to persist invalid sessions."""
        data = {
            "session_id": session.session_id,
            "bot_id": session.bot_id,
            "channel_id": session.channel_id,
            "messages": session.messages,
            "created_at": session.created_at,
        }

        if not self.validate(data):
            self._logger.error(
                "Refusing to save invalid session %s", session.session_id
            )
            return

        if self._storage is None:
            self._logger.debug(
                "No storage configured, session %s not persisted", session.session_id
            )
            return

        try:
            await self._storage.set(
                session.session_id, json.dumps(data, default=str)
            )
        except Exception as e:
            self._logger.error("Failed to save session %s: %s", session.session_id, e)

    async def create_fresh(self) -> Session:
        """Create a new empty session."""
        return Session(
            session_id=str(uuid4()),
            bot_id="",
            channel_id=0,
            messages=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
