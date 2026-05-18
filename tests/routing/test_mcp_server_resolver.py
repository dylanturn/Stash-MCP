"""McpServerResolverMiddleware tests (spec 04)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

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
from stash_mcp.config import Config
from stash_mcp.db.models import (
    McpServer,
    McpServerMount,
    Store,
    Tenant,
)
from stash_mcp.errors import install_problem_handlers
from stash_mcp.routing import (
    McpServerResolverMiddleware,
    StoreResolverMiddleware,
    current_mcp_server,
)
from stash_mcp.routing.context import current_store
from stash_mcp.stores.registry import StoreRegistry


async def _seed(sm: async_sessionmaker[AsyncSession], content_dir: Path):
    """Create a tenant, a single store with an on-disk repo, and a
    minimal MCP-server config that mounts it."""
    async with sm() as session:
        tenant = Tenant(slug="acme", display_name="Acme")
        session.add(tenant)
        await session.flush()
        store = Store(
            tenant_id=tenant.id,
            slug="docs",
            display_name="Docs",
            git_branch="main",
        )
        session.add(store)
        await session.commit()
        await session.refresh(tenant)
        await session.refresh(store)

    # Provision on-disk repo for the store.
    on_disk = content_dir / str(tenant.id) / store.slug
    on_disk.mkdir(parents=True)
    (on_disk / "hello.md").write_text("hello from docs")

    async with sm() as session:
        config = McpServer(
            tenant_id=tenant.id,
            slug="eng",
            name="Engineering",
            kind="simple",
            enabled=True,
        )
        session.add(config)
        await session.flush()
        session.add(
            McpServerMount(
                mcp_server_id=config.id,
                store_id=store.id,
                subpath="",
                virtual_prefix="",
                sort_order=0,
            )
        )
        await session.commit()
        await session.refresh(config)

    return tenant, store, config


def _principal_with_token(
    config_id: UUID | None, *, tenant_id: UUID
) -> Principal:
    claims: dict[str, object] = {"scopes": "read,write"}
    if config_id is not None:
        claims["mcp_server_id"] = str(config_id)
    return Principal(
        user_id=uuid4(),
        oidc_sub="sub",
        email="x@y",
        display_name="X",
        auth_method="api_token",
        tenant_roles={tenant_id: "member"},
        claims=claims,
    )


class _PrincipalSetter:
    """Pin a principal for the request, mimicking StashAuthMiddleware."""

    def __init__(self, inner, principal: Principal | None):
        self.inner = inner
        self.principal = principal

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.principal is None:
            await self.inner(scope, receive, send)
            return
        token = set_current_principal(self.principal)
        try:
            await self.inner(scope, receive, send)
        finally:
            reset_current_principal(token)


def _capture_app(captured: dict):
    async def echo(request: Request):
        captured["path"] = request.url.path
        store = current_store()
        captured["store_type"] = type(store).__name__ if store else None
        captured["is_single_store"] = (
            getattr(store, "is_single_store", None) if store else None
        )
        config = current_mcp_server()
        captured["config_slug"] = config.slug if config else None
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/api/{rest:path}", echo, methods=["GET"]),
            Route("/mcp/{rest:path}", echo, methods=["GET"]),
            Route("/api", echo, methods=["GET"]),
            Route("/mcp", echo, methods=["GET"]),
        ]
    )
    install_problem_handlers(app)
    return app


async def test_unscoped_token_passes_through(
    auth_db, content_dir: Path, monkeypatch
):
    monkeypatch.setattr(Config, "MCP_CONFIGS_ENABLED", True, raising=False)
    tenant, store, config = await _seed(auth_db, content_dir)

    captured: dict = {}
    app = _capture_app(captured)
    principal = _principal_with_token(None, tenant_id=tenant.id)

    registry = StoreRegistry()
    wrapped = StoreResolverMiddleware(
        app,
        registry=registry,
        public_prefixes=("/api/health",),
    )
    wrapped = McpServerResolverMiddleware(wrapped, registry=registry)
    wrapped = _PrincipalSetter(wrapped, principal)
    client = TestClient(wrapped)
    resp = client.get(f"/api/{tenant.slug}/{store.slug}/")
    assert resp.status_code == 200
    # Legacy resolver bound a single-store LoadedStore.
    assert captured["store_type"] == "LoadedStore"
    assert captured["config_slug"] is None


async def test_scoped_token_binds_composite_store(
    auth_db, content_dir: Path, monkeypatch
):
    monkeypatch.setattr(Config, "MCP_CONFIGS_ENABLED", True, raising=False)
    tenant, store, config = await _seed(auth_db, content_dir)

    captured: dict = {}
    app = _capture_app(captured)
    principal = _principal_with_token(config.id, tenant_id=tenant.id)

    registry = StoreRegistry()
    wrapped = StoreResolverMiddleware(
        app,
        registry=registry,
        public_prefixes=("/api/health",),
    )
    wrapped = McpServerResolverMiddleware(wrapped, registry=registry)
    wrapped = _PrincipalSetter(wrapped, principal)
    client = TestClient(wrapped)
    # Hit the bare /mcp/anything — the resolver doesn't care about URL
    # shape on a scoped token; it binds from the token.
    resp = client.get("/mcp/whatever/")
    assert resp.status_code == 200
    assert captured["store_type"] == "CompositeLoadedStore"
    assert captured["is_single_store"] is True
    assert captured["config_slug"] == "eng"


async def test_disabled_config_returns_403(
    auth_db: async_sessionmaker, content_dir: Path, monkeypatch
):
    monkeypatch.setattr(Config, "MCP_CONFIGS_ENABLED", True, raising=False)
    tenant, store, config = await _seed(auth_db, content_dir)
    async with auth_db() as session:
        cfg = await session.get(McpServer, config.id)
        cfg.enabled = False
        await session.commit()

    captured: dict = {}
    app = _capture_app(captured)
    principal = _principal_with_token(config.id, tenant_id=tenant.id)
    registry = StoreRegistry()
    wrapped = StoreResolverMiddleware(
        app, registry=registry, public_prefixes=()
    )
    wrapped = McpServerResolverMiddleware(wrapped, registry=registry)
    wrapped = _PrincipalSetter(wrapped, principal)
    client = TestClient(wrapped)
    resp = client.get("/mcp/whatever/")
    assert resp.status_code == 403
    assert resp.json()["type"] == "/problems/mcp-server/disabled"


async def test_flag_off_short_circuits(
    auth_db, content_dir: Path, monkeypatch
):
    monkeypatch.setattr(Config, "MCP_CONFIGS_ENABLED", False, raising=False)
    tenant, store, config = await _seed(auth_db, content_dir)
    captured: dict = {}
    app = _capture_app(captured)
    principal = _principal_with_token(config.id, tenant_id=tenant.id)
    registry = StoreRegistry()
    wrapped = StoreResolverMiddleware(
        app, registry=registry, public_prefixes=("/api/health",)
    )
    wrapped = McpServerResolverMiddleware(wrapped, registry=registry)
    wrapped = _PrincipalSetter(wrapped, principal)
    client = TestClient(wrapped)
    # With the flag off, the request behaves as if the token were
    # unscoped — URL-shape match required for the legacy resolver.
    resp = client.get(f"/api/{tenant.slug}/{store.slug}/")
    assert resp.status_code == 200
    assert captured["store_type"] == "LoadedStore"
    assert captured["config_slug"] is None
