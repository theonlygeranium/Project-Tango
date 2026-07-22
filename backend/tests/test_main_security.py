from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException

import main
from auth import CurrentUser


def current_user(role: str = "regular") -> CurrentUser:
    return CurrentUser(
        id=uuid.uuid4(),
        first_name="Test",
        last_name="User",
        email="test@example.com",
        role=role,
        session_id=uuid.uuid4(),
        csrf_hash=b"hash",
    )


def test_only_post_connection_details_is_exposed() -> None:
    routes = {
        (method, route.path)
        for route in main.app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("POST", "/api/connection-details") in routes
    assert ("GET", "/api/connection-details") not in routes
    assert main.app.docs_url is None
    assert main.app.openapi_url is None


def test_participant_context_accepts_only_valid_uuid() -> None:
    user_id = uuid.uuid4()

    class Participant:
        metadata = json.dumps(
            {
                "user_id": str(user_id),
                "persona_id": "therapy",
                "llm_model": "local/qwen3-fast",
            }
        )
        attributes = {}

    assert main._history_context_from_participant(Participant())["user_id"] == str(
        user_id
    )
    Participant.metadata = json.dumps(
        {"user_id": "not-a-uuid", "persona_id": "therapy"}
    )
    assert "user_id" not in main._history_context_from_participant(Participant())


class GrantPool:
    def __init__(self, granted: bool) -> None:
        self.granted = granted
        self.args = None

    async def fetchrow(self, query: str, *args):
        self.args = args
        return {"room_name": args[0]} if self.granted else None


class JsonRequest:
    async def json(self):
        return {"room_name": "tango_therapy_authorized"}


@pytest.mark.asyncio
async def test_dispatch_is_bound_to_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = GrantPool(True)

    async def fake_pool():
        return pool

    dispatched: list[str] = []

    async def fake_dispatch(room_name: str):
        dispatched.append(room_name)

    monkeypatch.setattr(main, "get_pool", fake_pool)
    monkeypatch.setattr(main, "_dispatch_agent", fake_dispatch)
    user = current_user()
    result = await main.dispatch_agent_to_room(JsonRequest(), user)
    assert result["dispatched"] is True
    assert pool.args == ("tango_therapy_authorized", user.id)
    assert dispatched == ["tango_therapy_authorized"]


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_or_consumed_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_pool():
        return GrantPool(False)

    monkeypatch.setattr(main, "get_pool", fake_pool)
    with pytest.raises(HTTPException) as error:
        await main.dispatch_agent_to_room(JsonRequest(), current_user())
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_voice_monitor_stops_after_account_or_grant_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RevokedPool:
        query = ""
        args = ()

        async def fetchval(self, query: str, *args):
            self.query = query
            self.args = args
            return False

    class Context:
        reason = None

        def shutdown(self, reason: str) -> None:
            self.reason = reason

    pool = RevokedPool()
    context = Context()

    async def fake_pool():
        return pool

    monkeypatch.setattr(main, "get_pool", fake_pool)
    user_id = uuid.uuid4()
    await main._account_access_monitor(
        context,
        user_id,
        "tango_therapy_authorized",
        interval_seconds=0,
    )

    assert context.reason == "account access revoked"
    assert pool.args == (user_id, "tango_therapy_authorized")
    assert "voice_room_grants" in pool.query
    assert "users.is_active" in pool.query
