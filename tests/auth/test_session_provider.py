"""Tests for ``SessionCookieAuthProvider``."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from stash_mcp.auth.session_provider import SessionCookieAuthProvider
from stash_mcp.auth.sessions import issue_session
from stash_mcp.config import Config
from stash_mcp.db.models import Membership, Tenant, User


def _request_with_cookie(cookie_value: str | None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie_value is not None:
        headers.append(
            (
                b"cookie",
                f"{Config.SESSION_COOKIE_NAME}={cookie_value}".encode("utf-8"),
            )
        )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/ui/",
        "headers": headers,
        "query_string": b"",
        "raw_path": b"/ui/",
    }
    return Request(scope)


async def _seed_user(sessionmaker):
    async with sessionmaker() as s:
        tenant = Tenant(slug="default", display_name="Default tenant")
        user = User(
            oidc_sub="alice-sub", email="alice@x.test", display_name="Alice"
        )
        s.add_all([tenant, user])
        await s.flush()
        s.add(
            Membership(
                user_id=user.id, tenant_id=tenant.id, role="admin", source="manual"
            )
        )
        await s.commit()
        return user.id, tenant.id


async def test_no_cookie_returns_none(auth_db):
    assert (
        await SessionCookieAuthProvider().authenticate(_request_with_cookie(None))
        is None
    )


async def test_valid_cookie_returns_principal(auth_db):
    user_id, tenant_id = await _seed_user(auth_db)
    cookie = issue_session(str(user_id), "alice-sub")
    principal = await SessionCookieAuthProvider().authenticate(
        _request_with_cookie(cookie)
    )
    assert principal is not None
    assert principal.auth_method == "session"
    assert principal.user_id == user_id
    assert principal.tenant_roles == {tenant_id: "admin"}


async def test_tampered_cookie_returns_none(auth_db):
    user_id, _ = await _seed_user(auth_db)
    cookie = issue_session(str(user_id), "alice-sub")
    tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")
    assert (
        await SessionCookieAuthProvider().authenticate(_request_with_cookie(tampered))
        is None
    )


async def test_cookie_for_deleted_user_returns_none(auth_db):
    """Cookie references a uid that no longer exists in the DB."""
    cookie = issue_session("00000000-0000-0000-0000-000000000000", "ghost-sub")
    assert (
        await SessionCookieAuthProvider().authenticate(_request_with_cookie(cookie))
        is None
    )


async def test_expired_cookie_returns_none(
    auth_db, monkeypatch: pytest.MonkeyPatch
):
    import time

    monkeypatch.setattr(Config, "SESSION_MAX_AGE_SECONDS", 1, raising=False)
    user_id, _ = await _seed_user(auth_db)
    cookie = issue_session(str(user_id), "alice-sub")
    time.sleep(2.1)
    assert (
        await SessionCookieAuthProvider().authenticate(_request_with_cookie(cookie))
        is None
    )
