"""End-to-end tests for ``/tenants/{tenant_id}/mcp-servers/*``."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from stash_mcp.db.models import (
    AuditEvent,
    McpServer,
    McpServerMount,
)

from .conftest import (
    _make_user,
    _principal,
    make_full_client,
)


async def _create_store(client, tenant_id, slug, display_name=None) -> dict:
    resp = client.post(
        f"/tenants/{tenant_id}/stores",
        json={"slug": slug, "display_name": display_name or slug},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_minimal_config(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    resp = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={"slug": "min", "name": "Minimal"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "min"
    assert body["name"] == "Minimal"
    assert body["tools"] == []
    assert body["content_roots"] == []
    assert body["enabled"] is True
    assert body["tenant_slug"] == "acme"


async def test_create_with_simple_root(
    auth_db,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    await _create_store(client, acme_tenant.id, "docs")

    resp = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "engineering-docs",
            "name": "Engineering docs",
            "tools": ["read_content", "list_content"],
            "content_roots": [
                {
                    "name": "engineering",
                    "kind": "simple",
                    "mounts": [
                        {
                            "store_slug": "docs",
                            "subpath": "engineering",
                        }
                    ],
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert sorted(body["tools"]) == ["list_content", "read_content"]
    roots = body["content_roots"]
    assert len(roots) == 1
    assert roots[0]["kind"] == "simple"
    assert len(roots[0]["mounts"]) == 1
    assert roots[0]["mounts"][0]["store_slug"] == "docs"
    assert roots[0]["mounts"][0]["subpath"] == "engineering"


async def test_overlapping_virtual_prefixes_400s(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    await _create_store(client, acme_tenant.id, "docs")
    resp = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "bad",
            "name": "Bad",
            "content_roots": [
                {
                    "name": "v",
                    "kind": "virtual",
                    "mounts": [
                        {"store_slug": "docs", "virtual_prefix": "docs"},
                        {
                            "store_slug": "docs",
                            "virtual_prefix": "docs/team-a",
                        },
                    ],
                }
            ],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/mount/conflict"


async def test_cross_tenant_mount_400s(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    beta_tenant,
    acme_admin_principal,
):
    # Provision a store under beta as global admin (simulate: directly
    # via the global-admin route by promoting acme_admin to also be
    # admin on beta? Simpler: use a beta-admin client.)
    beta_user = await _make_user(auth_db, email="beta-admin@x")
    beta_admin = _principal(
        tenant_roles={beta_tenant.id: "admin"}, user_id=beta_user.id
    )
    beta_client = make_full_client(beta_admin)
    await _create_store(beta_client, beta_tenant.id, "ops")

    acme_client = make_full_client(acme_admin_principal)
    resp = acme_client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "bad",
            "name": "Bad",
            "content_roots": [
                {
                    "name": "cr",
                    "kind": "simple",
                    "mounts": [{"store_slug": "ops"}],
                }
            ],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/mount/cross-tenant"


async def test_same_slug_in_two_tenants_resolves_to_own_tenant(
    auth_db,
    content_dir: Path,
    acme_tenant,
    beta_tenant,
    acme_admin_principal,
):
    """If acme and beta both have a `docs` store, mounting `docs` in an
    acme config must pick acme's `docs` — never beta's. Regression
    guard for a slug-only Store query."""
    beta_user = await _make_user(auth_db, email="beta-admin@x")
    beta_admin = _principal(
        tenant_roles={beta_tenant.id: "admin"}, user_id=beta_user.id
    )
    await _create_store(make_full_client(beta_admin), beta_tenant.id, "docs")

    acme_client = make_full_client(acme_admin_principal)
    await _create_store(acme_client, acme_tenant.id, "docs")

    resp = acme_client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "ok",
            "name": "Ok",
            "content_roots": [
                {
                    "name": "cr",
                    "kind": "simple",
                    "mounts": [{"store_slug": "docs"}],
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # The mounted store must belong to acme, not beta.
    from uuid import UUID

    mount_store_id = UUID(body["content_roots"][0]["mounts"][0]["store_id"])

    from sqlalchemy import select

    from stash_mcp.db.models import Store

    async with auth_db() as session:
        row = (
            await session.execute(
                select(Store).where(Store.id == mount_store_id)
            )
        ).scalar_one()
    assert row.tenant_id == acme_tenant.id


async def test_unknown_tool_name_400s(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    resp = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "bad",
            "name": "Bad",
            "tools": ["read_content", "not_a_real_tool"],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/tool-name/invalid"


async def test_simple_root_must_have_exactly_one_mount(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    await _create_store(client, acme_tenant.id, "docs")
    # Zero mounts → caught by pydantic min_length=1
    resp = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "bad",
            "name": "Bad",
            "content_roots": [
                {"name": "x", "kind": "simple", "mounts": []}
            ],
        },
    )
    assert resp.status_code == 422  # pydantic validation
    # Two mounts → 400 from our validator
    resp = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "bad",
            "name": "Bad",
            "content_roots": [
                {
                    "name": "x",
                    "kind": "simple",
                    "mounts": [
                        {"store_slug": "docs"},
                        {"store_slug": "docs", "virtual_prefix": "alt"},
                    ],
                }
            ],
        },
    )
    assert resp.status_code == 400


async def test_duplicate_slug_409s(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    r1 = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={"slug": "x", "name": "X"},
    )
    assert r1.status_code == 201
    r2 = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={"slug": "x", "name": "X2"},
    )
    assert r2.status_code == 409
    assert r2.json()["type"] == "/problems/mcp-server/already-exists"


async def test_patch_replaces_tools(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={"slug": "x", "name": "X", "tools": ["read_content"]},
    )
    resp = client.patch(
        f"/tenants/{acme_tenant.id}/mcp-servers/x",
        json={"tools": ["list_content", "search_content"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert sorted(body["tools"]) == ["list_content", "search_content"]

    async with auth_db() as session:
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "mcp_server.updated"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1
    detail = json.loads(events[0].detail)
    assert "tools" in detail["changed_fields"]


async def test_patch_replaces_content_roots_cleanly(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    await _create_store(client, acme_tenant.id, "docs")
    await _create_store(client, acme_tenant.id, "ops")

    client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "x",
            "name": "X",
            "content_roots": [
                {
                    "name": "r1",
                    "kind": "simple",
                    "mounts": [{"store_slug": "docs"}],
                }
            ],
        },
    )
    resp = client.patch(
        f"/tenants/{acme_tenant.id}/mcp-servers/x",
        json={
            "content_roots": [
                {
                    "name": "r2",
                    "kind": "simple",
                    "mounts": [{"store_slug": "ops"}],
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["content_roots"]) == 1
    assert body["content_roots"][0]["name"] == "r2"
    assert body["content_roots"][0]["mounts"][0]["store_slug"] == "ops"

    # Old mounts and roots should be gone, not orphaned.
    async with auth_db() as session:
        rows = (await session.execute(select(McpServerMount))).scalars().all()
    assert len(rows) == 1


async def test_delete_without_confirm_400s(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={"slug": "x", "name": "X"},
    )
    resp = client.delete(f"/tenants/{acme_tenant.id}/mcp-servers/x")
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/confirmation-required"


async def test_delete_with_confirm_cascades(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    await _create_store(client, acme_tenant.id, "docs")
    client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "x",
            "name": "X",
            "tools": ["read_content"],
            "content_roots": [
                {
                    "name": "r",
                    "kind": "simple",
                    "mounts": [{"store_slug": "docs"}],
                }
            ],
        },
    )
    resp = client.delete(
        f"/tenants/{acme_tenant.id}/mcp-servers/x?confirm=true"
    )
    assert resp.status_code == 204

    async with auth_db() as session:
        servers = (
            (await session.execute(select(McpServer))).scalars().all()
        )
        mounts = (
            (await session.execute(select(McpServerMount))).scalars().all()
        )
    assert servers == []
    assert mounts == []


async def test_store_in_use_by_config_blocks_store_delete(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    await _create_store(client, acme_tenant.id, "docs")
    client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "uses-docs",
            "name": "X",
            "content_roots": [
                {
                    "name": "r",
                    "kind": "simple",
                    "mounts": [{"store_slug": "docs"}],
                }
            ],
        },
    )
    resp = client.delete(
        f"/tenants/{acme_tenant.id}/stores/docs?confirm=true"
    )
    assert resp.status_code == 409
    assert resp.json()["type"] == "/problems/store/in-use"

    # After dropping the config, the store delete succeeds.
    client.delete(
        f"/tenants/{acme_tenant.id}/mcp-servers/uses-docs?confirm=true"
    )
    resp = client.delete(
        f"/tenants/{acme_tenant.id}/stores/docs?confirm=true"
    )
    assert resp.status_code == 204


async def test_member_blocked(
    auth_db, content_dir: Path, acme_tenant, acme_member_principal
):
    client = make_full_client(acme_member_principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/mcp-servers")
    assert resp.status_code == 403


async def test_cross_tenant_admin_blocked(
    auth_db, content_dir: Path, acme_tenant, beta_tenant
):
    user = await _make_user(auth_db, email="beta-admin@x")
    principal = _principal(
        tenant_roles={beta_tenant.id: "admin"}, user_id=user.id
    )
    client = make_full_client(principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/mcp-servers")
    assert resp.status_code == 403


async def test_multi_store_with_git_tool_400s(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    await _create_store(client, acme_tenant.id, "docs")
    await _create_store(client, acme_tenant.id, "ops")
    resp = client.post(
        f"/tenants/{acme_tenant.id}/mcp-servers",
        json={
            "slug": "bad-multi",
            "name": "Bad",
            "tools": ["read_content", "log_content"],
            "content_roots": [
                {
                    "name": "r",
                    "kind": "virtual",
                    "mounts": [
                        {
                            "store_slug": "docs",
                            "virtual_prefix": "engineering",
                        },
                        {
                            "store_slug": "ops",
                            "virtual_prefix": "ops",
                        },
                    ],
                }
            ],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/mcp-server/multi-store-git-forbidden"
