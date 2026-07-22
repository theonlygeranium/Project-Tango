from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status

PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
DEFAULT_PASSWORD_LENGTH = 12
SESSION_COOKIE = "__Host-tango_session"
CSRF_COOKIE = "__Host-tango_csrf"
DEV_SESSION_COOKIE = "tango_session"
DEV_CSRF_COOKIE = "tango_csrf"
AUTH_ERROR = "Invalid password"

_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)
_dummy_password_hash = _password_hasher.hash("project-tango-dummy-password")
# Argon2id is intentionally memory-hard. Bound concurrent verification so a
# login burst cannot multiply the 64 MiB working set without limit.
_password_verify_semaphore = asyncio.Semaphore(2)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    role: str
    session_id: uuid.UUID
    csrf_hash: bytes

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def lookup_key() -> bytes:
    raw = os.getenv("TANGO_AUTH_LOOKUP_KEY", "")
    encoded = raw.encode("utf-8")
    if len(encoded) < 32:
        raise RuntimeError("TANGO_AUTH_LOOKUP_KEY must contain at least 32 bytes")
    return encoded


def validate_auth_config() -> None:
    lookup_key()
    public_origin = os.getenv("TANGO_PUBLIC_ORIGIN", "").strip()
    if not public_origin.startswith(("https://", "http://")):
        raise RuntimeError("TANGO_PUBLIC_ORIGIN must be an absolute http(s) origin")
    _env_int("TANGO_AUTH_SESSION_TTL_HOURS", 168)
    _env_int("TANGO_AUTH_IDLE_TTL_HOURS", 12)
    _env_int("TANGO_AUTH_PASSWORD_LENGTH", DEFAULT_PASSWORD_LENGTH, minimum=10)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def generate_password() -> str:
    length = _env_int("TANGO_AUTH_PASSWORD_LENGTH", DEFAULT_PASSWORD_LENGTH, minimum=10)
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def password_lookup(password: str) -> bytes:
    return hmac.new(lookup_key(), password.encode("utf-8"), hashlib.sha256).digest()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def run_dummy_password_check(password: str) -> None:
    verify_password(_dummy_password_hash, password)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def csrf_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _secure_cookies() -> bool:
    return os.getenv("TANGO_AUTH_COOKIE_SECURE", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def session_cookie_name() -> str:
    return SESSION_COOKIE if _secure_cookies() else DEV_SESSION_COOKIE


def csrf_cookie_name() -> str:
    return CSRF_COOKIE if _secure_cookies() else DEV_CSRF_COOKIE


def set_auth_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    *,
    max_age_seconds: int,
) -> None:
    common = {
        "secure": _secure_cookies(),
        "samesite": "strict",
        "path": "/",
        "max_age": max_age_seconds,
    }
    response.set_cookie(session_cookie_name(), session_token, httponly=True, **common)
    response.set_cookie(csrf_cookie_name(), csrf_token, httponly=False, **common)
    response.headers["Cache-Control"] = "no-store"


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        session_cookie_name(), path="/", secure=_secure_cookies(), samesite="strict"
    )
    response.delete_cookie(
        csrf_cookie_name(), path="/", secure=_secure_cookies(), samesite="strict"
    )
    response.headers["Cache-Control"] = "no-store"


def request_client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    forwarded: str | None = None
    try:
        if peer and ipaddress.ip_address(peer).is_loopback:
            forwarded = request.headers.get("CF-Connecting-IP") or request.headers.get(
                "X-Forwarded-For"
            )
    except ValueError:
        pass
    candidate = (forwarded or peer or "").split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None


def _rate_key(kind: str, value: bytes | str) -> tuple[str, bytes]:
    if isinstance(value, str):
        value = hmac.new(lookup_key(), value.encode("utf-8"), hashlib.sha256).digest()
    return kind, value


def login_rate_keys(
    request: Request, credential_lookup: bytes
) -> list[tuple[str, bytes]]:
    keys = [_rate_key("credential", credential_lookup)]
    client_ip = request_client_ip(request)
    if client_ip:
        keys.append(_rate_key("ip", client_ip))
    return keys


async def ensure_login_allowed(
    pool: asyncpg.Pool, keys: list[tuple[str, bytes]]
) -> None:
    for key_type, key_value in keys:
        blocked = await pool.fetchval(
            """
            SELECT blocked_until > now()
            FROM tango.auth_rate_limits
            WHERE key_type = $1 AND key_hash = $2
            """,
            key_type,
            key_value,
        )
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": "60"},
            )


async def record_login_failure(
    pool: asyncpg.Pool, keys: list[tuple[str, bytes]]
) -> None:
    now = datetime.now(UTC)
    window_start_cutoff = now - timedelta(minutes=15)
    async with pool.acquire() as connection:
        async with connection.transaction():
            for key_type, key_value in keys:
                row = await connection.fetchrow(
                    """
                    INSERT INTO tango.auth_rate_limits AS limits
                        (key_type, key_hash, failure_count, window_started_at,
                         last_failure_at, blocked_until)
                    VALUES ($1, $2, 1, $3, $3, NULL)
                    ON CONFLICT (key_type, key_hash) DO UPDATE SET
                        failure_count = CASE
                            WHEN limits.window_started_at < $4 THEN 1
                            ELSE limits.failure_count + 1
                        END,
                        window_started_at = CASE
                            WHEN limits.window_started_at < $4 THEN $3
                            ELSE limits.window_started_at
                        END,
                        last_failure_at = $3,
                        blocked_until = NULL
                    RETURNING failure_count
                    """,
                    key_type,
                    key_value,
                    now,
                    window_start_cutoff,
                )
                failures = int(row["failure_count"])
                blocked_until: datetime | None = None
                if failures >= 10:
                    blocked_until = now + timedelta(minutes=15)
                elif failures >= 5:
                    blocked_until = now + timedelta(minutes=1)
                if blocked_until is not None:
                    await connection.execute(
                        """
                        UPDATE tango.auth_rate_limits
                        SET blocked_until = $3
                        WHERE key_type = $1 AND key_hash = $2
                        """,
                        key_type,
                        key_value,
                        blocked_until,
                    )


async def clear_login_failures(
    pool: asyncpg.Pool, keys: list[tuple[str, bytes]]
) -> None:
    for key_type, key_value in keys:
        await pool.execute(
            "DELETE FROM tango.auth_rate_limits WHERE key_type = $1 AND key_hash = $2",
            key_type,
            key_value,
        )


async def authenticate_password(
    pool: asyncpg.Pool, request: Request, password: str
) -> dict[str, Any] | None:
    if not password or len(password) > 128:
        credential_lookup = password_lookup(password[:128])
        keys = login_rate_keys(request, credential_lookup)
        async with _password_verify_semaphore:
            await ensure_login_allowed(pool, keys)
            await asyncio.to_thread(run_dummy_password_check, password[:128])
            await record_login_failure(pool, keys)
        return None
    credential_lookup = password_lookup(password)
    keys = login_rate_keys(request, credential_lookup)
    async with _password_verify_semaphore:
        # Recheck after waiting for a verification slot so failures recorded by
        # earlier attempts can block this request before another Argon2 run.
        await ensure_login_allowed(pool, keys)
        row = await pool.fetchrow(
            """
            SELECT id, first_name, last_name, email, role, password_hash, is_active
            FROM tango.users
            WHERE password_lookup = $1
            """,
            credential_lookup,
        )
        if row is None:
            await asyncio.to_thread(run_dummy_password_check, password)
            await record_login_failure(pool, keys)
            return None
        verified = await asyncio.to_thread(
            verify_password, row["password_hash"], password
        )
        if not verified or not row["is_active"]:
            await record_login_failure(pool, keys)
            return None
        await clear_login_failures(pool, keys)
        return dict(row)


async def create_auth_session(
    pool: asyncpg.Pool, request: Request, user_id: uuid.UUID
) -> tuple[str, str, int]:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    ttl_hours = _env_int("TANGO_AUTH_SESSION_TTL_HOURS", 168)
    ttl_seconds = ttl_hours * 3600
    await pool.execute(
        """
        INSERT INTO tango.auth_sessions
            (user_id, token_hash, csrf_hash, expires_at, client_ip, user_agent)
        VALUES ($1, $2, $3, now() + $4::interval, $5::inet, $6)
        """,
        user_id,
        token_hash(session_token),
        csrf_hash(csrf_token),
        timedelta(hours=ttl_hours),
        request_client_ip(request),
        (request.headers.get("user-agent") or "")[:512] or None,
    )
    await pool.execute(
        "UPDATE tango.users SET last_login_at = now() WHERE id = $1", user_id
    )
    return session_token, csrf_token, ttl_seconds


async def authenticate_request(request: Request) -> CurrentUser:
    from db import get_pool

    token = request.cookies.get(session_cookie_name())
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    pool = await get_pool()
    idle_hours = _env_int("TANGO_AUTH_IDLE_TTL_HOURS", 12)
    row = await pool.fetchrow(
        """
        SELECT s.id AS session_id, s.csrf_hash, s.last_seen_at,
               u.id, u.first_name, u.last_name, u.email, u.role
        FROM tango.auth_sessions s
        JOIN tango.users u ON u.id = s.user_id
        WHERE s.token_hash = $1
          AND s.revoked_at IS NULL
          AND s.expires_at > now()
          AND s.last_seen_at > now() - $2::interval
          AND u.is_active = TRUE
        """,
        token_hash(token),
        timedelta(hours=idle_hours),
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    now = datetime.now(UTC)
    if row["last_seen_at"] < now - timedelta(minutes=5):
        await pool.execute(
            "UPDATE tango.auth_sessions SET last_seen_at = now() WHERE id = $1",
            row["session_id"],
        )
    return CurrentUser(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        role=row["role"],
        session_id=row["session_id"],
        csrf_hash=bytes(row["csrf_hash"]),
    )


async def require_user(request: Request) -> CurrentUser:
    return await authenticate_request(request)


async def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


async def require_csrf(
    request: Request, user: CurrentUser = Depends(require_user)
) -> CurrentUser:
    expected_origin = os.getenv("TANGO_PUBLIC_ORIGIN", "").rstrip("/")
    supplied_origin = (request.headers.get("origin") or "").rstrip("/")
    if not expected_origin or not hmac.compare_digest(supplied_origin, expected_origin):
        raise HTTPException(status_code=403, detail="Invalid request origin")
    cookie_token = request.cookies.get(csrf_cookie_name(), "")
    header_token = request.headers.get("x-csrf-token", "")
    if not cookie_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if not hmac.compare_digest(csrf_hash(cookie_token), user.csrf_hash):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return user


async def require_admin_csrf(
    user: CurrentUser = Depends(require_csrf),
) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


async def revoke_session(pool: asyncpg.Pool, session_id: uuid.UUID) -> None:
    await pool.execute(
        "UPDATE tango.auth_sessions SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        session_id,
    )


async def revoke_user_sessions(pool: asyncpg.Pool, user_id: uuid.UUID) -> None:
    await pool.execute(
        """
        UPDATE tango.auth_sessions
        SET revoked_at = now()
        WHERE user_id = $1 AND revoked_at IS NULL
        """,
        user_id,
    )
    await pool.execute(
        """
        UPDATE tango.voice_room_grants
        SET revoked_at = now()
        WHERE user_id = $1 AND revoked_at IS NULL
        """,
        user_id,
    )
