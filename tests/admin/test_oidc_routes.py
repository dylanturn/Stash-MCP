"""End-to-end tests for ``/auth/login`` and ``/auth/callback``.

We don't stand up a real IdP — instead we monkey-patch ``get_oauth`` to
return a stub whose ``authorize_redirect`` records the call and whose
``authorize_access_token`` returns canned claims.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from starlette.testclient import TestClient

from stash_mcp.auth import routes as auth_routes
from stash_mcp.auth.routes import router as auth_router
from stash_mcp.config import Config
from stash_mcp.db.models import Membership, User
from stash_mcp.errors import install_problem_handlers


def _build_app(monkeypatch: pytest.MonkeyPatch, claims_for_callback: dict):
    """Build a FastAPI app with a stubbed OAuth client.

    ``/auth/login`` returns a fake 302 to a sentinel IdP URL; the
    callback resolves ``claims_for_callback`` as the userinfo. Tests
    cover both ends independently.
    """
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(auth_router)
    app.add_middleware(
        SessionMiddleware, secret_key="test-secret", session_cookie="oauth"
    )

    stub = type("OAuth", (), {})()
    idp = type("IdP", (), {})()

    async def _authorize_redirect(request, redirect_uri):
        return RedirectResponse(
            url=f"https://idp.example/authorize?cb={redirect_uri}",
            status_code=302,
        )

    async def _authorize_access_token(request):
        return {"userinfo": claims_for_callback}

    idp.authorize_redirect = _authorize_redirect
    idp.authorize_access_token = _authorize_access_token
    stub.idp = idp

    monkeypatch.setattr(auth_routes, "get_oauth", lambda: stub)
    monkeypatch.setattr(
        auth_routes, "_is_local_dev", lambda: True
    )  # let cookies skip Secure flag for TestClient
    return app


async def test_login_redirects_to_idp(
    auth_db, content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    app = _build_app(monkeypatch, claims_for_callback={})
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/login?next=/ui/foo")
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://idp.example/authorize")
    assert "cb=" in location
    # callback URL is encoded in the redirect.
    assert "auth/callback" in location


async def test_callback_creates_user_and_sets_cookie(
    auth_db: async_sessionmaker,
    content_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    claims = {
        "sub": "alice-sub",
        "email": "alice@x",
        "name": "Alice",
        "groups": ["stash-admins"],
    }
    app = _build_app(monkeypatch, claims_for_callback=claims)
    client = TestClient(app, follow_redirects=False)

    # Visit /login first to set the session 'next' value.
    client.get("/auth/login?next=/ui/landing")
    resp = client.get("/auth/callback")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui/landing"
    cookies = resp.headers.get_list("set-cookie")
    assert any(Config.SESSION_COOKIE_NAME in c for c in cookies)

    async with auth_db() as session:
        user = (
            await session.execute(
                select(User).where(User.oidc_sub == "alice-sub")
            )
        ).scalar_one_or_none()
        assert user is not None
        assert user.email == "alice@x"

        # Admin group → admin membership on the default tenant.
        memberships = (
            (
                await session.execute(
                    select(Membership).where(Membership.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
    assert any(m.role == "admin" for m in memberships)


async def test_callback_refreshes_existing_user(
    auth_db: async_sessionmaker,
    content_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Pre-seed user with stale display name.
    async with auth_db() as session:
        user = User(oidc_sub="alice-sub", email="old@x", display_name="Old")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        original_id = user.id

    claims = {
        "sub": "alice-sub",
        "email": "alice@x",
        "name": "Alice Updated",
        "groups": [],
    }
    app = _build_app(monkeypatch, claims_for_callback=claims)
    client = TestClient(app, follow_redirects=False)
    client.get("/auth/login")
    resp = client.get("/auth/callback")
    assert resp.status_code == 302

    async with auth_db() as session:
        refreshed = (
            await session.execute(
                select(User).where(User.oidc_sub == "alice-sub")
            )
        ).scalar_one()
    assert refreshed.id == original_id  # same row
    assert refreshed.email == "alice@x"
    assert refreshed.display_name == "Alice Updated"


async def test_callback_rejects_claims_without_sub(
    auth_db, content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    app = _build_app(monkeypatch, claims_for_callback={"email": "x@y"})
    client = TestClient(app, follow_redirects=False)
    client.get("/auth/login")
    resp = client.get("/auth/callback")
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/validation"


async def test_logout_clears_cookie(
    auth_db, content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    app = _build_app(
        monkeypatch,
        claims_for_callback={"sub": "x", "email": "x@y", "name": "X"},
    )
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/logout")
    assert resp.status_code == 302
    cookies = resp.headers.get_list("set-cookie")
    assert any(
        Config.SESSION_COOKIE_NAME in c and "Max-Age=0" in c
        for c in cookies
    )


async def test_callback_redirects_safely_for_external_next(
    auth_db, content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """An attacker-controlled ``next`` parameter must never escape the
    server. We accept only paths that start with ``/``."""
    app = _build_app(
        monkeypatch,
        claims_for_callback={"sub": "x", "email": "x@y", "name": "X"},
    )
    client = TestClient(app, follow_redirects=False)
    # Inject an absolute URL into the session next.
    client.get("/auth/login?next=https://evil.example")
    resp = client.get("/auth/callback")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui"
