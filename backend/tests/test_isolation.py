from __future__ import annotations

import uuid

import pytest

import history


class CapturePool:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple = ()

    async def fetch(self, query: str, *args):
        self.query = query
        self.args = args
        return []


@pytest.mark.asyncio
async def test_history_list_always_filters_by_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = CapturePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr(history, "get_pool", fake_pool)
    user_id = uuid.uuid4()
    assert await history.get_sessions(user_id) == []
    assert "WHERE user_id = $1" in pool.query
    assert pool.args[0] == user_id


@pytest.mark.asyncio
async def test_history_detail_joins_session_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = CapturePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr(history, "get_pool", fake_pool)
    session_id = uuid.uuid4()
    user_id = uuid.uuid4()
    assert await history.get_session_turns(session_id, user_id) == []
    assert "JOIN tango.sessions" in pool.query
    assert "s.user_id = $2" in pool.query
    assert pool.args == (session_id, user_id)
