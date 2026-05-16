"""Tests for ``StashAuthMiddleware``."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from stash_mcp.auth.context import current_principal
from stash_mcp.auth.middleware import StashAuthMiddleware
from stash_mcp.auth.principal import Principal
from stash_mcp.auth.provider import AuthError
from stash_mcp.config import Config


def _whoami(_request: Request) -> JSONResponse:
    p = current_principal()
    if p is None:
        return JSONResponse({"principal": None})
    return JSONResponse(
        {
            "principal": {
                "user_id": str(p.user_id),
                "auth_method": p.auth_method,
            }
        }
    )


def _build_app(*, providers: list[Any]) -> Starlette:
    app = Starlette(
        routes=[
            Route("/api/whoami", _whoami),
            Route("/api/health", lambda _r: JSONResponse({"ok": True})),
            Route("/ui/", lambda _r: JSONResponse({"ui": True})),
            Route("/ui/static/x.js", lambda _r: JSONResponse({"asset": True})),
            Route("/static/x.js", lambda _r: JSONResponse({"asset": True})),
        ]
    )
    app.add_middleware(StashAuthMiddleware, providers=providers)
    return app


def _client(app: Starlette) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class _StubProvider:
    """Configurable AuthProvider double."""

    def __init__(
        self,
        *,
        name: str,
        result: Principal | None = None,
        raises: AuthError | None = None,
    ) -> None:
        self.name = name
        self._result = result
        self._raises = raises
        self.calls = 0

    async def authenticate(self, request: Request) -> Principal | None:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._result


def _principal(method: str = "session") -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        oidc_sub="alice-sub",
        email="alice@x.test",
        display_name="Alice",
        auth_method=method,  # type: ignore[arg-type]
    )


async def test_auth_disabled_noops(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", False, raising=False)
    stub = _StubProvider(name="oidc")
    app = _build_app(providers=[stub])

    async with _client(app) as c:
        r = await c.get("/api/whoami")
    assert r.status_code == 200
    assert r.json()["principal"] is None
    assert stub.calls == 0


async def test_no_credentials_api_returns_401(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    app = _build_app(providers=[_StubProvider(name="oidc")])

    async with _client(app) as c:
        r = await c.get("/api/whoami")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate", "").startswith("Bearer")
    assert r.json()["error"] == "unauthenticated"


async def test_no_credentials_ui_redirects_to_login(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    app = _build_app(providers=[_StubProvider(name="oidc")])

    async with _client(app) as c:
        r = await c.get("/ui/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"] == "/auth/login?next=/ui/"


async def test_public_health_skips_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    stub = _StubProvider(name="oidc")
    app = _build_app(providers=[stub])

    async with _client(app) as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    assert stub.calls == 0


async def test_static_assets_skip_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    stub = _StubProvider(name="oidc")
    app = _build_app(providers=[stub])

    async with _client(app) as c:
        r = await c.get("/static/x.js")
    assert r.status_code == 200
    assert stub.calls == 0


async def test_successful_auth_sets_principal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    principal = _principal(method="api_token")
    app = _build_app(
        providers=[_StubProvider(name="api_token", result=principal)]
    )

    async with _client(app) as c:
        r = await c.get(
            "/api/whoami", headers={"Authorization": "Bearer stash_pat_x"}
        )
    assert r.status_code == 200
    assert r.json()["principal"] == {
        "user_id": str(principal.user_id),
        "auth_method": "api_token",
    }


async def test_second_provider_wins_when_first_returns_none(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    second_principal = _principal(method="oidc")
    p1 = _StubProvider(name="session", result=None)
    p2 = _StubProvider(name="oidc", result=second_principal)
    app = _build_app(providers=[p1, p2])

    async with _client(app) as c:
        r = await c.get("/api/whoami", headers={"Authorization": "Bearer eyJ..."})
    assert r.status_code == 200
    assert r.json()["principal"]["auth_method"] == "oidc"
    assert p1.calls == 1
    assert p2.calls == 1


async def test_active_rejection_stops_chain(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    p1 = _StubProvider(
        name="api_token",
        raises=AuthError(
            "revoked",
            www_authenticate='Bearer realm="stash", error="invalid_token"',
        ),
    )
    p2 = _StubProvider(name="oidc", result=_principal())
    app = _build_app(providers=[p1, p2])

    async with _client(app) as c:
        r = await c.get(
            "/api/whoami", headers={"Authorization": "Bearer stash_pat_x"}
        )
    assert r.status_code == 401
    assert "invalid_token" in r.headers["WWW-Authenticate"]
    assert p1.calls == 1
    assert p2.calls == 0  # short-circuited


async def test_principal_is_reset_after_request(monkeypatch: pytest.MonkeyPatch):
    """Two requests on the same loop: principal from request A must not leak
    into request B."""
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    p_a = _principal(method="api_token")
    provider = _StubProvider(name="api_token", result=p_a)
    app = _build_app(providers=[provider])

    async with _client(app) as c:
        r1 = await c.get(
            "/api/whoami", headers={"Authorization": "Bearer stash_pat_x"}
        )
        assert r1.json()["principal"]["user_id"] == str(p_a.user_id)
        # Now hit a public path which doesn't auth — principal should be None.
        r2 = await c.get("/api/health")
        assert r2.status_code == 200

    # And current_principal() in this test scope should still be None.
    assert current_principal() is None
