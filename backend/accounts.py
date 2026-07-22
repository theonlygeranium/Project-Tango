from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Iterable

import asyncpg

from auth import generate_password, hash_password, normalize_email, password_lookup
from personas import ALLOWED_LLM_MODELS, TANGO_PERSONAS, get_persona

PersonaAccess = dict[str, str | None]
VoiceGrant = tuple[str, str]


def validate_persona_access(access: Iterable[PersonaAccess]) -> list[PersonaAccess]:
    validated: list[PersonaAccess] = []
    seen: set[str] = set()
    for item in access:
        persona_id = str(item.get("persona_id") or "")
        model_override = item.get("llm_model_override")
        if persona_id not in TANGO_PERSONAS:
            raise ValueError(f"Unknown persona: {persona_id}")
        if persona_id in seen:
            raise ValueError(f"Duplicate persona: {persona_id}")
        if model_override is not None and model_override not in ALLOWED_LLM_MODELS:
            raise ValueError(f"Unsupported LLM model: {model_override}")
        seen.add(persona_id)
        validated.append(
            {
                "persona_id": persona_id,
                "llm_model_override": str(model_override) if model_override else None,
            }
        )
    return validated


async def replace_persona_access(
    connection: Any, user_id: uuid.UUID, access: Iterable[PersonaAccess]
) -> None:
    validated = validate_persona_access(access)
    await connection.execute(
        "DELETE FROM tango.user_persona_access WHERE user_id = $1", user_id
    )
    if validated:
        await connection.executemany(
            """
            INSERT INTO tango.user_persona_access
                (user_id, persona_id, llm_model_override)
            VALUES ($1, $2, $3)
            """,
            [
                (user_id, item["persona_id"], item["llm_model_override"])
                for item in validated
            ],
        )


async def audit_admin_action(
    connection: Any,
    *,
    actor_user_id: uuid.UUID | None,
    target_user_id: uuid.UUID | None,
    action: str,
    metadata: dict[str, Any] | None = None,
    client_ip: str | None = None,
) -> None:
    safe_metadata = metadata or {}
    forbidden = {
        "password",
        "password_hash",
        "password_lookup",
        "session_token",
        "csrf_token",
    }
    if forbidden.intersection(safe_metadata):
        raise ValueError("Secrets cannot be written to the audit log")
    await connection.execute(
        """
        INSERT INTO tango.admin_audit_log
            (actor_user_id, target_user_id, action, metadata, client_ip)
        VALUES ($1, $2, $3, $4::jsonb, $5::inet)
        """,
        actor_user_id,
        target_user_id,
        action,
        json.dumps(safe_metadata),
        client_ip,
    )


async def create_user(
    pool: asyncpg.Pool,
    *,
    first_name: str,
    last_name: str,
    email: str,
    role: str,
    persona_access: Iterable[PersonaAccess],
    created_by: uuid.UUID | None,
    client_ip: str | None = None,
    adopt_legacy_data: bool = False,
) -> tuple[dict[str, Any], str]:
    if role not in {"admin", "regular"}:
        raise ValueError("Invalid role")
    clean_first = first_name.strip()
    clean_last = last_name.strip()
    clean_email = normalize_email(email)
    if not clean_first or not clean_last:
        raise ValueError("First and last name are required")
    validated_access = validate_persona_access(persona_access)

    for _ in range(5):
        password = generate_password()
        lookup = password_lookup(password)
        password_digest = await asyncio.to_thread(hash_password, password)
        try:
            async with pool.acquire() as connection:
                async with connection.transaction():
                    row = await connection.fetchrow(
                        """
                        INSERT INTO tango.users
                            (first_name, last_name, email, role, password_hash,
                             password_lookup, created_by)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING id, first_name, last_name, email, role, is_active,
                                  created_at, updated_at, last_login_at
                        """,
                        clean_first,
                        clean_last,
                        clean_email,
                        role,
                        password_digest,
                        lookup,
                        created_by,
                    )
                    user_id = row["id"]
                    await replace_persona_access(connection, user_id, validated_access)
                    if adopt_legacy_data:
                        await connection.execute(
                            "UPDATE tango.sessions SET user_id = $1 WHERE user_id IS NULL",
                            user_id,
                        )
                        await connection.execute(
                            "UPDATE tango.memories SET user_id = $1 WHERE user_id IS NULL",
                            user_id,
                        )
                    await audit_admin_action(
                        connection,
                        actor_user_id=created_by,
                        target_user_id=user_id,
                        action="user.created" if created_by else "admin.bootstrapped",
                        metadata={
                            "role": role,
                            "persona_ids": [
                                item["persona_id"] for item in validated_access
                            ],
                            "adopted_legacy_data": adopt_legacy_data,
                        },
                        client_ip=client_ip,
                    )
            return dict(row), password
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", "") in {
                "users_password_lookup_key",
                "tango_users_password_lookup_key",
            }:
                continue
            if "email" in (getattr(exc, "constraint_name", "") or ""):
                raise ValueError("A user with that email already exists") from exc
            raise
    raise RuntimeError("Could not generate a unique password")


async def reset_user_password(
    pool: asyncpg.Pool,
    *,
    user_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_ip: str | None = None,
) -> tuple[str, list[VoiceGrant]] | None:
    for _ in range(5):
        password = generate_password()
        lookup = password_lookup(password)
        password_digest = await asyncio.to_thread(hash_password, password)
        try:
            async with pool.acquire() as connection:
                async with connection.transaction():
                    row = await connection.fetchrow(
                        """
                        UPDATE tango.users
                        SET password_hash = $2, password_lookup = $3, updated_at = now()
                        WHERE id = $1
                        RETURNING id
                        """,
                        user_id,
                        password_digest,
                        lookup,
                    )
                    if row is None:
                        return None
                    await connection.execute(
                        """
                        UPDATE tango.auth_sessions SET revoked_at = now()
                        WHERE user_id = $1 AND revoked_at IS NULL
                        """,
                        user_id,
                    )
                    revoked_grants = await connection.fetch(
                        """
                        UPDATE tango.voice_room_grants SET revoked_at = now()
                        WHERE user_id = $1 AND revoked_at IS NULL
                        RETURNING room_name, participant_identity
                        """,
                        user_id,
                    )
                    await audit_admin_action(
                        connection,
                        actor_user_id=actor_user_id,
                        target_user_id=user_id,
                        action="user.password_reset",
                        client_ip=client_ip,
                    )
            return password, [
                (row["room_name"], row["participant_identity"])
                for row in revoked_grants
            ]
        except asyncpg.UniqueViolationError as exc:
            if "password_lookup" in (getattr(exc, "constraint_name", "") or ""):
                continue
            raise
    raise RuntimeError("Could not generate a unique password")


async def list_user_access(
    pool: asyncpg.Pool, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT persona_id, llm_model_override
        FROM tango.user_persona_access
        WHERE user_id = $1
        ORDER BY persona_id
        """,
        user_id,
    )
    result = []
    for row in rows:
        persona = get_persona(row["persona_id"])
        override = row["llm_model_override"]
        effective_model = (
            override if override in ALLOWED_LLM_MODELS else persona.llm_model
        )
        result.append(
            {
                "persona_id": persona.id,
                "llm_model_override": override
                if override in ALLOWED_LLM_MODELS
                else None,
                "effective_llm_model": effective_model,
            }
        )
    return result


async def resolve_persona_policy(
    pool: asyncpg.Pool,
    *,
    user_id: uuid.UUID,
    role: str,
    persona_id: str | None,
    requested_model: str | None = None,
) -> tuple[Any, str] | None:
    if not persona_id or persona_id not in TANGO_PERSONAS:
        return None
    persona = get_persona(persona_id)
    if role == "admin":
        effective = (
            requested_model
            if requested_model in ALLOWED_LLM_MODELS
            else persona.llm_model
        )
        return persona, effective
    row = await pool.fetchrow(
        """
        SELECT llm_model_override
        FROM tango.user_persona_access
        WHERE user_id = $1 AND persona_id = $2
        """,
        user_id,
        persona.id,
    )
    if row is None:
        return None
    override = row["llm_model_override"]
    effective = override if override in ALLOWED_LLM_MODELS else persona.llm_model
    return persona, effective


async def user_payload(pool: asyncpg.Pool, user: Any) -> dict[str, Any]:
    if user.role == "admin":
        access = [
            {
                "persona_id": persona.id,
                "llm_model_override": None,
                "effective_llm_model": persona.llm_model,
            }
            for persona in TANGO_PERSONAS.values()
        ]
    else:
        access = await list_user_access(pool, user.id)
    return {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role,
        "persona_access": access,
    }
