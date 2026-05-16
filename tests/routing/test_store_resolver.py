"""StoreResolverMiddleware tests — path matching, ACL, contextvar lifetime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.auth.principal import Principal
from stash_mcp.db.models import Store, Tenant
from stash_mcp.git_backend import GitBackend
from stash_mcp.routing import StoreResolverMiddleware
from stash_mcp.routing.context import current_store
from stash_mcp.stores.registry import StoreRegistry


async def _make_tenant_and_store(
    sm: async_sessionmaker[AsyncSession],
    *,
    tenant_slug: str,
    store_slug: str,
) -> tuple[Tenant, Store]:
    async with sm() as session:
        tenant = Tenant(slug=tenant_slug, display_name=tenant_slug.title())
        session.add(tenant)
        await session.flush()
        store = Store(
            tenant_id=tenant.id,
            slug=store_slug,
            display_name=store_slug.title(),
            git_branch="main",
        )
        session.add(store)
        await session.commit()
        await session.refresh(tenant)
        await session.refresh(store)
        return tenant, store


def _principal(tenant_ids: list[UUID]) -> Principal:
    """Build a Principal with member membership on each given tenant_id."""
    from uuid import uuid4

    return Principal(
        user_id=uuid4(),
        oidc_sub="sub-test",
        email="test@example.com",
        display_name="Test",
        auth_method="api_token",
        tenant_roles={tid: "member" for tid in tenant_ids},
    )


def _inner_app(captured: dict):
    """A Starlette app that records the rewritten path and current_store."""

    async def echo(request: Request):
        captured["path"] = request.url.path
        captured["raw_path"] = request.scope.get("raw_path")
        store = current_store()
        captured["store_tenant_slug"] = store.tenant_slug if store else None
        captured["store_slug"] = store.slug if hasattr(store, "slug") else (
            store.store_slug if store else None
        )
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/api/{rest:path}", echo, methods=["GET", "POST"]),
            Route("/mcp/{rest:path}", echo, methods=["GET", "POST"]),
            Route("/api/health", echo, methods=["GET"]),
            Route("/api", echo, methods=["GET", "POST"]),
            Route("/mcp", echo, methods=["GET", "POST"]),
            Route("/", echo, methods=["GET"]),
        ]
    )


def _wrap_with_principal(app, principal: Principal | None):
    """Install a thin middleware that sets ``current_principal`` ahead of
    the StoreResolver. The real auth middleware does this in production."""

    class _PrincipalSetter:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http" or principal is None:
                await self.inner(scope, receive, send)
                return
            token = set_current_principal(principal)
            try:
                await self.inner(scope, receive, send)
            finally:
                reset_current_principal(token)

    return _PrincipalSetter(app)


def _build_test_app(
    inner_app, registry: StoreRegistry, principal: Principal | None
):
    resolver = StoreResolverMiddleware(
        inner_app,
        registry=registry,
        public_prefixes=("/api/health", "/auth", "/admin", "/ui", "/static"),
    )
    return _wrap_with_principal(resolver, principal)


@pytest.fixture
def captured() -> dict:
    return {}


async def test_valid_api_path_rewrites_and_sets_store(
    auth_db, content_dir: Path, captured: dict
):
    tenant, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, _principal([tenant.id]))

    client = TestClient(app)
    resp = client.get("/api/acme/docs/content")
    assert resp.status_code == 200
    assert captured["path"] == "/api/content"
    assert captured["raw_path"] == b"/api/content"
    assert captured["store_tenant_slug"] == "acme"
    assert captured["store_slug"] == "docs"


async def test_valid_mcp_path_rewrites(
    auth_db, content_dir: Path, captured: dict
):
    tenant, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, _principal([tenant.id]))

    client = TestClient(app)
    resp = client.get("/mcp/acme/docs/")
    assert resp.status_code == 200
    assert captured["path"] == "/mcp/"


async def test_malformed_tenant_slug_404s_before_db(
    auth_db, content_dir: Path, captured: dict
):
    registry = StoreRegistry()
    # If the resolver reaches the DB this lookup would also fail, but we
    # want to prove it rejects the slug *before* a DB roundtrip.
    call_count = {"n": 0}
    real_get = registry.get

    async def counting_get(t, s):
        call_count["n"] += 1
        return await real_get(t, s)

    registry.get = counting_get  # type: ignore[assignment]

    app = _build_test_app(
        _inner_app(captured), registry, _principal([])
    )
    client = TestClient(app)
    resp = client.get("/api/UPPER/docs/content")
    assert resp.status_code == 404
    assert call_count["n"] == 0


async def test_malformed_store_slug_404s_before_db(
    auth_db, content_dir: Path, captured: dict
):
    registry = StoreRegistry()
    call_count = {"n": 0}
    real_get = registry.get

    async def counting_get(t, s):
        call_count["n"] += 1
        return await real_get(t, s)

    registry.get = counting_get  # type: ignore[assignment]

    app = _build_test_app(_inner_app(captured), registry, _principal([]))
    client = TestClient(app)
    resp = client.get("/api/acme/Bad_Store/content")
    assert resp.status_code == 404
    assert call_count["n"] == 0


async def test_unknown_store_404(auth_db, content_dir: Path, captured: dict):
    tenant, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, _principal([tenant.id]))
    client = TestClient(app)
    resp = client.get("/api/acme/ghost/content")
    assert resp.status_code == 404


async def test_unknown_tenant_404(auth_db, content_dir: Path, captured: dict):
    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, _principal([]))
    client = TestClient(app)
    resp = client.get("/api/ghost/docs/content")
    assert resp.status_code == 404


async def test_principal_not_member_of_tenant_403(
    auth_db, content_dir: Path, captured: dict
):
    """Regression for the cross-tenant access bug — principal has
    membership on tenant A trying to reach a store under tenant B."""
    tenant_a, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    tenant_b, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="other", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant_a.id) / "docs")
    GitBackend.init(content_dir / str(tenant_b.id) / "docs")

    registry = StoreRegistry()
    # Principal has membership only on tenant_a.
    app = _build_test_app(
        _inner_app(captured), registry, _principal([tenant_a.id])
    )
    client = TestClient(app)
    resp = client.get("/api/other/docs/content")
    assert resp.status_code == 403


async def test_multi_tenant_principal_succeeds_on_both(
    auth_db, content_dir: Path, captured: dict
):
    tenant_a, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    tenant_b, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="other", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant_a.id) / "docs")
    GitBackend.init(content_dir / str(tenant_b.id) / "docs")

    registry = StoreRegistry()

    # Membership order in the dict should not affect outcomes.
    for order in ([tenant_a.id, tenant_b.id], [tenant_b.id, tenant_a.id]):
        principal = _principal(order)
        app = _build_test_app(_inner_app(captured), registry, principal)
        client = TestClient(app)
        assert client.get("/api/acme/docs/content").status_code == 200
        assert captured["store_tenant_slug"] == "acme"
        assert client.get("/api/other/docs/content").status_code == 200
        assert captured["store_tenant_slug"] == "other"


async def test_health_skipped_by_resolver(
    auth_db, content_dir: Path, captured: dict
):
    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, None)
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert captured["store_tenant_slug"] is None


async def test_public_prefixes_skipped(
    auth_db, content_dir: Path, captured: dict
):
    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, None)
    client = TestClient(app)
    # /auth, /admin, /ui, /static all bypass the resolver.
    for path in ("/auth/login", "/admin/foo", "/ui/", "/static/x.css"):
        # the inner app may 404 since those routes aren't defined, but
        # the resolver should NOT intercept with its own 401/404.
        resp = client.get(path)
        assert resp.status_code in (200, 404)


async def test_concurrent_requests_dont_leak_store(
    auth_db, content_dir: Path
):
    tenant_a, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    tenant_b, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="other", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant_a.id) / "docs")
    GitBackend.init(content_dir / str(tenant_b.id) / "docs")

    registry = StoreRegistry()
    principal = _principal([tenant_a.id, tenant_b.id])

    seen_slugs: list[str] = []

    async def echo(request: Request):
        await asyncio.sleep(0.02)
        s = current_store()
        seen_slugs.append(f"{s.tenant_slug}/{s.store_slug}")
        return JSONResponse({"slug": s.store_slug})

    inner = Starlette(
        routes=[Route("/api/{rest:path}", echo, methods=["GET"])]
    )
    app = _build_test_app(inner, registry, principal)

    # Drive the ASGI app concurrently with two different store URLs.
    async def call(path: str) -> int:
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
        }
        status: dict = {}
        sent = asyncio.Event()

        async def receive():
            await asyncio.Event().wait()  # never resolves; not needed for GET

        async def send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            elif message["type"] == "http.response.body":
                sent.set()

        task = asyncio.create_task(app(scope, receive, send))
        await sent.wait()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, BaseException):
            pass
        return status["code"]

    codes = await asyncio.gather(
        call("/api/acme/docs/content"),
        call("/api/other/docs/content"),
    )
    assert codes == [200, 200]
    assert sorted(seen_slugs) == ["acme/docs", "other/docs"]
    # After the responses, the contextvar must be back to its baseline.
    assert current_store() is None


async def test_missing_principal_401(
    auth_db, content_dir: Path, captured: dict
):
    """Defensive 401 if the resolver is reached without a principal.
    Production has the auth middleware in front, but this guards against
    a misconfigured stack."""
    tenant, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, None)
    client = TestClient(app)
    resp = client.get("/api/acme/docs/content")
    assert resp.status_code == 401


async def test_auth_disabled_passes_through(
    auth_db, content_dir: Path, captured: dict, monkeypatch: pytest.MonkeyPatch
):
    """When AUTH_ENABLED=False the resolver no-ops."""
    from stash_mcp.config import Config

    monkeypatch.setattr(Config, "AUTH_ENABLED", False, raising=False)
    registry = StoreRegistry()
    app = _build_test_app(_inner_app(captured), registry, None)
    client = TestClient(app)
    # Without auth the resolver leaves the path alone, hitting the inner
    # /api/{rest:path} route directly.
    resp = client.get("/api/content")
    assert resp.status_code == 200
    assert captured["path"] == "/api/content"
    assert captured["store_tenant_slug"] is None
