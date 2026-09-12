"""Session management — file-based session storage for schubert-bot-v2.

This is a simplified file-based session manager that stores sessions as JSON files
in a directory. Each session is a separate file named by session_id.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """A conversation session for a single bot/channel pair."""

    session_id: str
    bot_id: str
    channel_id: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""


class SessionManager:
    """File-based session manager for schubert-bot-v2."""

    def __init__(self, sessions_dir: str) -> None:
        """Initialize with a directory path for storing session files."""
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(__name__)

    def _session_id(self, channel_id: int, thread_id: str | None = None) -> str:
        """Build a deterministic session ID from the parent channel.

        Discord threads of a channel share one session so follow-ups in a
        bot-created thread keep the parent conversation. `thread_id` is
        accepted for call-site compatibility and ignored.
        """
        return str(channel_id)

    def list_sessions(self) -> list[str]:
        """List all session IDs (filenames without .json extension)."""
        try:
            return [
                f.stem
                for f in self.sessions_dir.glob("*.json")
                if f.is_file()
            ]
        except Exception as e:
            self._logger.error(f"Failed to list sessions: {e}")
            return []

    def load(self, session_id: str) -> Session | None:
        """Load a session by ID from disk. Returns None if not found."""
        session_file = self.sessions_dir / f"{session_id}.json"

        if not session_file.exists():
            self._logger.debug(f"Session {session_id} not found")
            return None

        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            return Session(
                session_id=data.get("session_id", session_id),
                bot_id=data.get("bot_id", ""),
                channel_id=data.get("channel_id", 0),
                messages=data.get("messages", []),
                created_at=data.get("created_at", ""),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self._logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def save(self, session: Session) -> bool:
        """Save a session to disk. Returns True on success."""
        session_file = self.sessions_dir / f"{session.session_id}.json"

        data = {
            "session_id": session.session_id,
            "bot_id": session.bot_id,
            "channel_id": session.channel_id,
            "messages": session.messages,
            "created_at": session.created_at,
        }

        try:
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            return True
        except Exception as e:
            self._logger.error(f"Failed to save session {session.session_id}: {e}")
            return False

    def create_fresh(self, bot_id: str = "", channel_id: int = 0) -> Session:
        """Create a new empty session."""
        return Session(
            session_id=str(uuid4()),
            bot_id=bot_id,
            channel_id=channel_id,
            messages=[],
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Returns True on success."""
        session_file = self.sessions_dir / f"{session_id}.json"

        try:
            if session_file.exists():
                session_file.unlink()
                return True
            return False
        except Exception as e:
            self._logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    # ── Methods required by schubert-bot-v2.py ──────────────────────────

    def get_session(self, channel_id: int, thread_id: str | None = None) -> Session | None:
        """Get (or create) a session for a channel/thread pair."""
        sid = self._session_id(channel_id, thread_id)
        session = self.load(sid)
        if session is None:
            session = Session(
                session_id=sid,
                bot_id="",
                channel_id=channel_id,
                messages=[],
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self.save(session)
        return session

    def get_history(self, channel_id: int, thread_id: str | None = None) -> list[dict[str, Any]]:
        """Get message history for a channel/thread pair."""
        session = self.get_session(channel_id, thread_id)
        if session is None:
            return []
        return session.messages

    def append_exchange(
        self,
        channel_id: int,
        user_msg: str | None = None,
        assistant_msg: str | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Append a user+assistant exchange to the session history.

        Accepts both (user_msg, assistant_msg) and the Admiral/Cortex aliases
        (user_message, assistant_response). Never raises on None content.
        """
        user_msg = user_msg if user_msg is not None else kwargs.get("user_message")
        assistant_msg = assistant_msg if assistant_msg is not None else kwargs.get("assistant_response")
        if user_msg is None and assistant_msg is None:
            self._logger.warning("append_exchange called with no messages; skipping")
            return

        session = self.get_session(channel_id, thread_id)
        if session is None:
            session = Session(
                session_id=self._session_id(channel_id, thread_id),
                bot_id="",
                channel_id=channel_id,
                messages=[],
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        if user_msg is not None:
            session.messages.append({"role": "user", "content": str(user_msg)})
        if assistant_msg is not None:
            session.messages.append({"role": "assistant", "content": str(assistant_msg)})

        # Cap history at 100 messages to prevent unbounded growth
        if len(session.messages) > 100:
            session.messages = session.messages[-100:]

        self.save(session)

    def get_session_info(self, channel_id: int, thread_id: str | None = None) -> dict[str, Any]:
        """Get metadata about a session."""
        session = self.get_session(channel_id, thread_id)
        if session is None:
            return {"exists": False, "message_count": 0}
        return {
            "exists": True,
            "session_id": session.session_id,
            "channel_id": session.channel_id,
            "message_count": len(session.messages),
            "created_at": session.created_at,
        }

    def clear_session(self, channel_id: int, thread_id: str | None = None) -> bool:
        """Clear (delete) a session for a channel/thread pair."""
        sid = self._session_id(channel_id, thread_id)
        return self.delete(sid)

    def save_all(self) -> None:
        """Save all in-memory sessions. 

        For this file-based implementation, sessions are saved on each
        append_exchange call, so this is a no-op but must exist for
        interface compatibility.
        """
        pass
