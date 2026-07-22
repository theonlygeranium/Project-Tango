from __future__ import annotations

import re
import uuid

import pytest
from fastapi import HTTPException, Request, Response

import auth


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TANGO_AUTH_LOOKUP_KEY", "a" * 64)
    monkeypatch.setenv("TANGO_PUBLIC_ORIGIN", "https://project-tango.schubert.life")
    monkeypatch.setenv("TANGO_AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("TANGO_AUTH_PASSWORD_LENGTH", "12")


def request_with_headers(
    *headers: tuple[str, str], client: str = "127.0.0.1"
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "scheme": "https",
            "server": ("project-tango.schubert.life", 443),
            "client": (client, 12345),
            "headers": [
                (key.lower().encode(), value.encode()) for key, value in headers
            ],
        }
    )


def test_generated_password_is_simple_and_high_entropy_shape() -> None:
    passwords = {auth.generate_password() for _ in range(100)}
    assert len(passwords) == 100
    assert all(re.fullmatch(r"[a-z2-9]{12}", password) for password in passwords)
    assert all(not set(password).intersection("lo01") for password in passwords)


def test_argon2_hash_never_contains_plaintext_and_verifies() -> None:
    password = "abc234def567"
    digest = auth.hash_password(password)
    assert digest.startswith("$argon2id$")
    assert password not in digest
    assert auth.verify_password(digest, password)
    assert not auth.verify_password(digest, "wrong234pass")


def test_password_lookup_is_keyed_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = auth.password_lookup("abc234def567")
    assert first == auth.password_lookup("abc234def567")
    monkeypatch.setenv("TANGO_AUTH_LOOKUP_KEY", "b" * 64)
    assert first != auth.password_lookup("abc234def567")


def test_auth_config_rejects_short_lookup_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TANGO_AUTH_LOOKUP_KEY", "short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        auth.validate_auth_config()


def test_auth_cookies_have_host_security_attributes() -> None:
    response = Response()
    auth.set_auth_cookies(response, "session-value", "csrf-value", max_age_seconds=3600)
    cookies = response.headers.getlist("set-cookie")
    assert any("__Host-tango_session=session-value" in cookie for cookie in cookies)
    assert any("HttpOnly" in cookie for cookie in cookies if "tango_session" in cookie)
    assert all("Secure" in cookie and "SameSite=strict" in cookie for cookie in cookies)
    assert any("__Host-tango_csrf=csrf-value" in cookie for cookie in cookies)


def test_forwarded_ip_is_trusted_only_from_loopback() -> None:
    local = request_with_headers(("CF-Connecting-IP", "203.0.113.7"))
    remote = request_with_headers(
        ("CF-Connecting-IP", "203.0.113.7"), client="198.51.100.8"
    )
    assert auth.request_client_ip(local) == "203.0.113.7"
    assert auth.request_client_ip(remote) == "198.51.100.8"


@pytest.mark.asyncio
async def test_csrf_requires_matching_origin_cookie_header_and_session_hash() -> None:
    csrf_token = "csrf-secret"
    request = request_with_headers(
        ("Origin", "https://project-tango.schubert.life"),
        ("X-CSRF-Token", csrf_token),
        ("Cookie", f"{auth.CSRF_COOKIE}={csrf_token}"),
    )
    user = auth.CurrentUser(
        id=uuid.uuid4(),
        first_name="Test",
        last_name="User",
        email="test@example.com",
        role="regular",
        session_id=uuid.uuid4(),
        csrf_hash=auth.csrf_hash(csrf_token),
    )
    assert await auth.require_csrf(request, user) == user

    bad_request = request_with_headers(
        ("Origin", "https://evil.example"),
        ("X-CSRF-Token", csrf_token),
        ("Cookie", f"{auth.CSRF_COOKIE}={csrf_token}"),
    )
    with pytest.raises(HTTPException) as error:
        await auth.require_csrf(bad_request, user)
    assert error.value.status_code == 403
