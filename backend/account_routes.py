from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from accounts import (
    audit_admin_action,
    create_user,
    list_user_access,
    replace_persona_access,
    reset_user_password,
    user_payload,
    validate_persona_access,
)
from auth import (
    AUTH_ERROR,
    CurrentUser,
    authenticate_password,
    clear_auth_cookies,
    create_auth_session,
    request_client_ip,
    require_admin,
    require_admin_csrf,
    require_csrf,
    require_user,
    revoke_session,
    set_auth_cookies,
)
from db import get_pool
from personas import list_llm_models, list_personas

router = APIRouter()
logger = logging.getLogger("project-tango.accounts")


async def _disconnect_voice_grants(grants: list[tuple[str, str]]) -> None:
    """Best-effort removal of participants whose account access was revoked."""
    if not grants:
        return
    livekit_url = os.getenv("LIVEKIT_URL")
    livekit_api_key = os.getenv("LIVEKIT_API_KEY")
    livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not all((livekit_url, livekit_api_key, livekit_api_secret)):
        logger.warning(
            "Cannot disconnect revoked voice grants: LiveKit API is not configured"
        )
        return

    from livekit import api as livekit_api

    try:
        async with livekit_api.LiveKitAPI(
            livekit_url, livekit_api_key, livekit_api_secret
        ) as client:
            for room_name, participant_identity in set(grants):
                await client.room.remove_participant(
                    livekit_api.RoomParticipantIdentity(
                        room=room_name,
                        identity=participant_identity,
                    )
                )
    except Exception:
        # Credential revocation is already committed and the worker monitor is
        # the backstop. A control-plane outage must not suppress the one-time
        # replacement password or make the admin repeat the reset.
        logger.exception("Could not disconnect one or more revoked voice participants")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class PersonaAccessRequest(BaseModel):
    persona_id: str = Field(min_length=1, max_length=50)
    llm_model_override: str | None = Field(default=None, max_length=100)


class UserCreateRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    persona_access: list[PersonaAccessRequest] = Field(default_factory=list)

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank")
        return cleaned


class UserUpdateRequest(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = None
    persona_access: list[PersonaAccessRequest] | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank")
        return cleaned


def _time(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


async def _account_payload(pool: asyncpg.Pool, row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "email": row["email"],
        "role": row["role"],
        "is_active": row["is_active"],
        "created_at": _time(row.get("created_at")),
        "updated_at": _time(row.get("updated_at")),
        "last_login_at": _time(row.get("last_login_at")),
        "persona_access": await list_user_access(pool, row["id"]),
    }


async def _fetch_account(pool: asyncpg.Pool, user_id: uuid.UUID) -> Any:
    return await pool.fetchrow(
        """
        SELECT id, first_name, last_name, email, role, is_active,
               created_at, updated_at, last_login_at
        FROM tango.users WHERE id = $1
        """,
        user_id,
    )


def _parse_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id") from None


@router.post("/api/auth/login")
async def login(body: LoginRequest, request: Request) -> Response:
    pool = await get_pool()
    account = await authenticate_password(pool, request, body.password)
    if account is None:
        raise HTTPException(status_code=401, detail=AUTH_ERROR)
    session_token, csrf_token, max_age = await create_auth_session(
        pool, request, account["id"]
    )
    current = CurrentUser(
        id=account["id"],
        first_name=account["first_name"],
        last_name=account["last_name"],
        email=account["email"],
        role=account["role"],
        session_id=uuid.UUID(int=0),
        csrf_hash=b"",
    )
    response = JSONResponse(
        {"user": await user_payload(pool, current), "csrf_token": csrf_token}
    )
    set_auth_cookies(
        response,
        session_token,
        csrf_token,
        max_age_seconds=max_age,
    )
    return response


@router.get("/api/auth/me")
async def me(user: CurrentUser = Depends(require_user)) -> Response:
    pool = await get_pool()
    return JSONResponse(
        {"user": await user_payload(pool, user)},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/auth/logout")
async def logout(user: CurrentUser = Depends(require_csrf)) -> Response:
    pool = await get_pool()
    await revoke_session(pool, user.session_id)
    response = JSONResponse({"status": "logged_out"})
    clear_auth_cookies(response)
    return response


@router.get("/api/admin/personas")
async def admin_personas(_: CurrentUser = Depends(require_admin)) -> Response:
    return JSONResponse(
        {"personas": list_personas(), "llm_models": list_llm_models()},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/admin/users")
async def admin_users(_: CurrentUser = Depends(require_admin)) -> Response:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, first_name, last_name, email, role, is_active,
               created_at, updated_at, last_login_at
        FROM tango.users
        ORDER BY role = 'admin' DESC, lower(last_name), lower(first_name), lower(email)
        """
    )
    users = [await _account_payload(pool, row) for row in rows]
    return JSONResponse({"users": users}, headers={"Cache-Control": "no-store"})


@router.get("/api/admin/users/{user_id}")
async def admin_user_detail(
    user_id: str, _: CurrentUser = Depends(require_admin)
) -> Response:
    pool = await get_pool()
    row = await _fetch_account(pool, _parse_user_id(user_id))
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return JSONResponse(
        {"user": await _account_payload(pool, row)},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    body: UserCreateRequest,
    request: Request,
    admin: CurrentUser = Depends(require_admin_csrf),
) -> Response:
    pool = await get_pool()
    access = [item.model_dump() for item in body.persona_access]
    try:
        row, password = await create_user(
            pool,
            first_name=body.first_name,
            last_name=body.last_name,
            email=str(body.email),
            role="regular",
            persona_access=access,
            created_by=admin.id,
            client_ip=request_client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    account = await _fetch_account(pool, row["id"])
    response = JSONResponse(
        {"user": await _account_payload(pool, account), "generated_password": password},
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )
    return response


@router.patch("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    admin: CurrentUser = Depends(require_admin_csrf),
) -> Response:
    parsed_id = _parse_user_id(user_id)
    pool = await get_pool()
    existing = await _fetch_account(pool, parsed_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")
    access = None
    if body.persona_access is not None:
        access = [item.model_dump() for item in body.persona_access]
        try:
            validate_persona_access(access)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    UPDATE tango.users
                    SET first_name = $2, last_name = $3, email = $4, updated_at = now()
                    WHERE id = $1
                    """,
                    parsed_id,
                    body.first_name
                    if body.first_name is not None
                    else existing["first_name"],
                    body.last_name
                    if body.last_name is not None
                    else existing["last_name"],
                    str(body.email).lower()
                    if body.email is not None
                    else existing["email"],
                )
                if access is not None:
                    await replace_persona_access(connection, parsed_id, access)
                await audit_admin_action(
                    connection,
                    actor_user_id=admin.id,
                    target_user_id=parsed_id,
                    action="user.updated",
                    metadata={
                        "profile_updated": any(
                            value is not None
                            for value in (body.first_name, body.last_name, body.email)
                        ),
                        "persona_policy_updated": access is not None,
                    },
                    client_ip=request_client_ip(request),
                )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=409, detail="A user with that email already exists"
        ) from exc
    row = await _fetch_account(pool, parsed_id)
    return JSONResponse(
        {"user": await _account_payload(pool, row)},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin_csrf),
) -> Response:
    parsed_id = _parse_user_id(user_id)
    pool = await get_pool()
    reset_result = await reset_user_password(
        pool,
        user_id=parsed_id,
        actor_user_id=admin.id,
        client_ip=request_client_ip(request),
    )
    if reset_result is None:
        raise HTTPException(status_code=404, detail="User not found")
    password, revoked_grants = reset_result
    await _disconnect_voice_grants(revoked_grants)
    return JSONResponse(
        {"user_id": str(parsed_id), "generated_password": password},
        headers={"Cache-Control": "no-store"},
    )


async def _set_active(
    *,
    pool: asyncpg.Pool,
    target_id: uuid.UUID,
    active: bool,
    admin: CurrentUser,
    request: Request,
) -> list[tuple[str, str]]:
    if target_id == admin.id and not active:
        raise HTTPException(
            status_code=409, detail="You cannot deactivate your own account"
        )
    async with pool.acquire() as connection:
        async with connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE tango.users
                SET is_active = $2, updated_at = now()
                WHERE id = $1
                RETURNING id, role
                """,
                target_id,
                active,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="User not found")
            if not active:
                await connection.execute(
                    "UPDATE tango.auth_sessions SET revoked_at = now() WHERE user_id = $1 AND revoked_at IS NULL",
                    target_id,
                )
                revoked_grants = await connection.fetch(
                    """
                    UPDATE tango.voice_room_grants SET revoked_at = now()
                    WHERE user_id = $1 AND revoked_at IS NULL
                    RETURNING room_name, participant_identity
                    """,
                    target_id,
                )
            else:
                revoked_grants = []
            await audit_admin_action(
                connection,
                actor_user_id=admin.id,
                target_user_id=target_id,
                action="user.reactivated" if active else "user.deactivated",
                client_ip=request_client_ip(request),
            )
    return [
        (grant["room_name"], grant["participant_identity"]) for grant in revoked_grants
    ]


@router.post("/api/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(
    user_id: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin_csrf),
) -> dict[str, Any]:
    parsed_id = _parse_user_id(user_id)
    pool = await get_pool()
    revoked_grants = await _set_active(
        pool=pool,
        target_id=parsed_id,
        active=False,
        admin=admin,
        request=request,
    )
    await _disconnect_voice_grants(revoked_grants)
    return {"user_id": str(parsed_id), "is_active": False}


@router.post("/api/admin/users/{user_id}/reactivate")
async def admin_reactivate_user(
    user_id: str,
    request: Request,
    admin: CurrentUser = Depends(require_admin_csrf),
) -> dict[str, Any]:
    parsed_id = _parse_user_id(user_id)
    pool = await get_pool()
    await _set_active(
        pool=pool, target_id=parsed_id, active=True, admin=admin, request=request
    )
    return {"user_id": str(parsed_id), "is_active": True}
