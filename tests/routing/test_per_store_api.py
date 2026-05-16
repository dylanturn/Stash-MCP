"""Per-store REST API tests — isolation + ETag conditional requests.

Builds an auth-enabled FastAPI app on top of a temp content dir and an
in-memory DB, drives it through ``TestClient`` with a fake auth
middleware that injects a principal.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.testclient import TestClient

from stash_mcp.api import USE_CURRENT_STORE, create_api
from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.auth.principal import Principal
from stash_mcp.db.models import Store, Tenant
from stash_mcp.git_backend import GitBackend
from stash_mcp.routing import StoreResolverMiddleware
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
    from uuid import uuid4

    return Principal(
        user_id=uuid4(),
        oidc_sub="sub-test",
        email="test@example.com",
        display_name="Test",
        auth_method="api_token",
        tenant_roles={tid: "member" for tid in tenant_ids},
    )


def _principal_setter(principal: Principal):
    class _Middleware:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.inner(scope, receive, send)
                return
            token = set_current_principal(principal)
            try:
                await self.inner(scope, receive, send)
            finally:
                reset_current_principal(token)

    return _Middleware


def _build_app(registry: StoreRegistry, principal: Principal):
    api = create_api(USE_CURRENT_STORE)
    resolver = StoreResolverMiddleware(
        api,
        registry=registry,
        public_prefixes=("/api/health",),
    )
    return _principal_setter(principal)(resolver)


@pytest.fixture
async def two_stores(auth_db, content_dir: Path) -> tuple[Tenant, Tenant]:
    tenant_a, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    tenant_b, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="other", store_slug="docs"
    )
    GitBackend.init(content_dir / str(tenant_a.id) / "docs")
    GitBackend.init(content_dir / str(tenant_b.id) / "docs")
    return tenant_a, tenant_b


async def test_store_isolation_create_in_a_404_in_b(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, tenant_b = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id, tenant_b.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    # Write to store A
    resp = client.post(
        "/api/acme/docs/content/hello.md", json={"content": "from A"}
    )
    assert resp.status_code == 201

    # Reading from store B should 404 — different repo
    resp = client.get("/api/other/docs/content/hello.md")
    assert resp.status_code == 404

    # Reading from store A returns the content
    resp = client.get("/api/acme/docs/content/hello.md")
    assert resp.status_code == 200
    assert resp.json()["content"] == "from A"


async def test_list_reflects_only_one_store(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, tenant_b = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id, tenant_b.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/a-only.md", json={"content": "A"})
    client.post("/api/other/docs/content/b-only.md", json={"content": "B"})

    resp = client.get("/api/acme/docs/content?recursive=true")
    paths_a = [item["path"] for item in resp.json()["items"]]
    assert "a-only.md" in paths_a
    assert "b-only.md" not in paths_a

    resp = client.get("/api/other/docs/content?recursive=true")
    paths_b = [item["path"] for item in resp.json()["items"]]
    assert "b-only.md" in paths_b
    assert "a-only.md" not in paths_b


async def test_delete_in_a_doesnt_affect_b(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, tenant_b = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id, tenant_b.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/shared-name.md", json={"content": "A"})
    client.post("/api/other/docs/content/shared-name.md", json={"content": "B"})

    resp = client.delete("/api/acme/docs/content/shared-name.md")
    assert resp.status_code == 200

    assert client.get("/api/acme/docs/content/shared-name.md").status_code == 404
    assert client.get("/api/other/docs/content/shared-name.md").status_code == 200


# --- ETag tests --------------------------------------------------------


async def test_get_returns_etag_header(auth_db, content_dir: Path, two_stores):
    tenant_a, _ = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/etag.md", json={"content": "hello"})
    resp = client.get("/api/acme/docs/content/etag.md")
    assert resp.status_code == 200
    assert "etag" in {k.lower() for k in resp.headers}
    etag = resp.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')


async def test_if_none_match_returns_304(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, _ = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/etag.md", json={"content": "v1"})
    first = client.get("/api/acme/docs/content/etag.md")
    etag = first.headers["etag"]

    resp = client.get(
        "/api/acme/docs/content/etag.md",
        headers={"If-None-Match": etag},
    )
    assert resp.status_code == 304
    # 304 must keep the ETag and have empty body
    assert resp.headers["etag"] == etag
    assert resp.content == b""


async def test_if_none_match_nonmatching_returns_200(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, _ = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/etag.md", json={"content": "v1"})
    resp = client.get(
        "/api/acme/docs/content/etag.md",
        headers={"If-None-Match": '"deadbeef"'},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "v1"


async def test_put_with_matching_if_match_updates(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, _ = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/etag.md", json={"content": "v1"})
    first = client.get("/api/acme/docs/content/etag.md")
    etag = first.headers["etag"]

    resp = client.put(
        "/api/acme/docs/content/etag.md",
        json={"content": "v2"},
        headers={"If-Match": etag},
    )
    assert resp.status_code == 200
    new_etag = resp.headers.get("etag")
    assert new_etag is not None and new_etag != etag

    confirmed = client.get("/api/acme/docs/content/etag.md")
    assert confirmed.json()["content"] == "v2"
    assert confirmed.headers["etag"] == new_etag


async def test_put_with_nonmatching_if_match_returns_412(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, _ = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/etag.md", json={"content": "v1"})
    first = client.get("/api/acme/docs/content/etag.md")
    current_etag = first.headers["etag"]

    resp = client.put(
        "/api/acme/docs/content/etag.md",
        json={"content": "v2"},
        headers={"If-Match": '"stale-etag"'},
    )
    assert resp.status_code == 412
    # The response carries the current ETag so the client can retry.
    assert resp.headers.get("etag") == current_etag
    # And the file content was NOT changed.
    confirmed = client.get("/api/acme/docs/content/etag.md")
    assert confirmed.json()["content"] == "v1"


async def test_put_without_if_match_writes_unconditionally(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, _ = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    client.post("/api/acme/docs/content/etag.md", json={"content": "v1"})
    resp = client.put(
        "/api/acme/docs/content/etag.md", json={"content": "v2"}
    )
    assert resp.status_code == 200
    confirmed = client.get("/api/acme/docs/content/etag.md")
    assert confirmed.json()["content"] == "v2"


async def test_health_works_without_tenant_or_auth(
    auth_db, content_dir: Path, two_stores
):
    tenant_a, _ = two_stores
    registry = StoreRegistry()
    principal = _principal([tenant_a.id])
    app = _build_app(registry, principal)
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
