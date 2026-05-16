"""Tests for ``/auth/me`` and ``/auth/stores`` — the SPA's bootstrap endpoints."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from stash_mcp.db.models import Store, Tenant

from .conftest import _principal, make_client


async def test_me_unauthenticated(auth_db, content_dir: Path):
    client = make_client(None)
    resp = client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_returns_principal_shape(
    auth_db: async_sessionmaker, content_dir: Path
):
    async with auth_db() as session:
        tenant = Tenant(slug="acme", display_name="Acme")
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        tenant_id = tenant.id

    p = _principal(
        tenant_roles={tenant_id: "admin"},
        auth_method="session",
    )
    client = make_client(p)
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(p.user_id)
    assert body["email"] == p.email
    assert body["display_name"] == p.display_name
    assert body["auth_method"] == "session"
    assert body["tenant_roles"] == {str(tenant_id): "admin"}


async def test_stores_unauthenticated(auth_db, content_dir: Path):
    client = make_client(None)
    resp = client.get("/auth/stores")
    assert resp.status_code == 401


async def test_stores_empty_when_no_memberships(
    auth_db, content_dir: Path
):
    p = _principal(tenant_roles={}, auth_method="session")
    client = make_client(p)
    resp = client.get("/auth/stores")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_stores_returns_only_principals_tenants(
    auth_db: async_sessionmaker, content_dir: Path
):
    """Stores under tenants the principal isn't a member of must not leak."""
    async with auth_db() as session:
        t1 = Tenant(slug="acme", display_name="Acme")
        t2 = Tenant(slug="other", display_name="Other")
        session.add_all([t1, t2])
        await session.flush()
        # User has access to t1 only.
        session.add_all(
            [
                Store(tenant_id=t1.id, slug="docs", display_name="Docs"),
                Store(tenant_id=t1.id, slug="kb", display_name="KB"),
                Store(tenant_id=t2.id, slug="secret", display_name="Secret"),
            ]
        )
        await session.commit()
        await session.refresh(t1)
        await session.refresh(t2)
        t1_id = t1.id

    p = _principal(tenant_roles={t1_id: "member"}, auth_method="session")
    client = make_client(p)
    resp = client.get("/auth/stores")
    assert resp.status_code == 200
    body = resp.json()
    slugs = sorted((b["tenant_slug"], b["slug"]) for b in body)
    assert slugs == [("acme", "docs"), ("acme", "kb")]
    assert all(b["tenant_id"] == str(t1_id) for b in body)
    assert all(b["role"] == "member" for b in body)
    # Sanity: shape includes display names.
    assert all(b["display_name"] for b in body)
    assert all(b["tenant_display_name"] == "Acme" for b in body)


async def test_stores_role_reflects_membership(
    auth_db: async_sessionmaker, content_dir: Path
):
    async with auth_db() as session:
        t1 = Tenant(slug="a", display_name="A")
        t2 = Tenant(slug="b", display_name="B")
        session.add_all([t1, t2])
        await session.flush()
        session.add_all(
            [
                Store(tenant_id=t1.id, slug="x", display_name="X"),
                Store(tenant_id=t2.id, slug="y", display_name="Y"),
            ]
        )
        await session.commit()
        await session.refresh(t1)
        await session.refresh(t2)
        t1_id, t2_id = t1.id, t2.id

    p = _principal(
        tenant_roles={t1_id: "admin", t2_id: "member"},
        auth_method="session",
    )
    client = make_client(p)
    resp = client.get("/auth/stores")
    body = resp.json()
    roles_by_tenant = {b["tenant_slug"]: b["role"] for b in body}
    assert roles_by_tenant == {"a": "admin", "b": "member"}
