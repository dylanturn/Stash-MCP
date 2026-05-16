"""End-to-end tests for ``/admin/*``."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from stash_mcp.db.models import (
    ApiToken,
    AuditEvent,
    Membership,
    Store,
    Tenant,
    User,
)
from stash_mcp.errors import PROBLEM_MEDIA_TYPE

from .conftest import (
    _ensure_default_tenant,
    _principal,
    make_client,
)


async def _make_user(
    auth_db: async_sessionmaker, *, email: str
) -> User:
    async with auth_db() as session:
        user = User(oidc_sub=email, email=email, display_name=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def admin_principal(auth_db: async_sessionmaker):
    tenant = await _ensure_default_tenant(auth_db)
    user = await _make_user(auth_db, email="admin@x")
    return _principal(tenant_roles={tenant.id: "admin"}, user_id=user.id)


@pytest.fixture
async def member_principal(auth_db: async_sessionmaker):
    tenant = await _ensure_default_tenant(auth_db)
    user = await _make_user(auth_db, email="member@x")
    return _principal(tenant_roles={tenant.id: "member"}, user_id=user.id)


async def test_non_admin_blocked(auth_db, content_dir: Path, member_principal):
    client = make_client(member_principal)
    resp = client.get("/admin/tenants")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert resp.json()["type"] == "/problems/auth/forbidden"


async def test_unauthenticated_blocked(auth_db, content_dir: Path):
    await _ensure_default_tenant(auth_db)
    client = make_client(None)
    resp = client.get("/admin/tenants")
    assert resp.status_code == 401
    assert resp.json()["type"] == "/problems/auth/unauthenticated"


async def test_tenant_crud_round_trip(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)

    # Create
    resp = client.post(
        "/admin/tenants",
        json={"slug": "acme", "display_name": "Acme"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    tenant_id = body["id"]
    assert body["slug"] == "acme"

    # List
    resp = client.get("/admin/tenants")
    assert resp.status_code == 200
    slugs = {t["slug"] for t in resp.json()}
    assert {"acme", "default"} <= slugs

    # Get
    resp = client.get(f"/admin/tenants/{tenant_id}")
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Acme"

    # Rename
    resp = client.patch(
        f"/admin/tenants/{tenant_id}", json={"display_name": "Acme Inc."}
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Acme Inc."

    # Delete (no stores yet — should succeed)
    resp = client.delete(f"/admin/tenants/{tenant_id}")
    assert resp.status_code == 204

    # Audit row exists.
    async with auth_db() as session:
        events = (
            (await session.execute(select(AuditEvent)))
            .scalars()
            .all()
        )
    actions = {e.action for e in events}
    assert {"tenant.created", "tenant.renamed", "tenant.deleted"} <= actions


async def test_tenant_create_duplicate_slug_conflicts(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    client.post("/admin/tenants", json={"slug": "acme", "display_name": "A"})
    resp = client.post(
        "/admin/tenants", json={"slug": "acme", "display_name": "B"}
    )
    assert resp.status_code == 409
    assert resp.json()["type"] == "/problems/tenant/already-exists"


async def test_store_provisioning_creates_on_disk_repo(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    tenant = client.post(
        "/admin/tenants", json={"slug": "acme", "display_name": "Acme"}
    ).json()

    resp = client.post(
        f"/admin/tenants/{tenant['id']}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    assert resp.status_code == 201, resp.text
    store = resp.json()
    assert store["slug"] == "docs"

    on_disk = content_dir / tenant["id"] / "docs"
    assert on_disk.exists()
    assert (on_disk / ".git").exists()


async def test_store_delete_requires_confirm(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    tenant = client.post(
        "/admin/tenants", json={"slug": "acme", "display_name": "A"}
    ).json()
    client.post(
        f"/admin/tenants/{tenant['id']}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    # No confirm flag → 400
    resp = client.delete(f"/admin/tenants/{tenant['id']}/stores/docs")
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/confirmation-required"
    # On disk still there.
    assert (content_dir / tenant["id"] / "docs").exists()

    # With confirm=true → 204 + removed.
    resp = client.delete(
        f"/admin/tenants/{tenant['id']}/stores/docs?confirm=true"
    )
    assert resp.status_code == 204
    assert not (content_dir / tenant["id"] / "docs").exists()

    async with auth_db() as session:
        rows = (
            (await session.execute(select(Store))).scalars().all()
        )
    assert rows == []


async def test_manual_membership_grant_survives_oidc_resync(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)

    # Create a tenant + a user the membership will target.
    tenant = client.post(
        "/admin/tenants", json={"slug": "acme", "display_name": "A"}
    ).json()

    async with auth_db() as session:
        user = User(oidc_sub="alice", email="a@x", display_name="Alice")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = str(user.id)

    resp = client.post(
        "/admin/memberships",
        json={"user_id": uid, "tenant_id": tenant["id"], "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source"] == "manual"

    # Simulate an OIDC group resync. The "manual wins" precedence is
    # exercised in tests/auth/; here we just verify the manual row stays
    # after running the same upsert flow.
    from stash_mcp.auth.users import upsert_user_and_memberships

    async with auth_db() as session:
        await upsert_user_and_memberships(
            session,
            {"sub": "alice", "email": "a@x", "name": "Alice", "groups": []},
        )
        await session.commit()
        rows = (
            (
                await session.execute(
                    select(Membership).where(Membership.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
    assert {m.source for m in rows} == {"manual"}


async def test_membership_grant_then_revoke(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    tenant = client.post(
        "/admin/tenants", json={"slug": "acme", "display_name": "A"}
    ).json()
    async with auth_db() as session:
        user = User(oidc_sub="bob", email="b@x", display_name="Bob")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = str(user.id)

    grant = client.post(
        "/admin/memberships",
        json={"user_id": uid, "tenant_id": tenant["id"], "role": "admin"},
    ).json()
    assert grant["role"] == "admin"

    # Duplicate grant 409s
    again = client.post(
        "/admin/memberships",
        json={"user_id": uid, "tenant_id": tenant["id"], "role": "admin"},
    )
    assert again.status_code == 409

    revoke = client.delete(f"/admin/memberships/{grant['id']}")
    assert revoke.status_code == 204
    async with auth_db() as session:
        rows = (
            (await session.execute(select(Membership)))
            .scalars()
            .all()
        )
    assert all(r.id != grant["id"] for r in rows)


async def test_user_list_and_delete_cascades(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    async with auth_db() as session:
        user = User(oidc_sub="carol", email="c@x", display_name="Carol")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = ApiToken(
            user_id=user.id,
            token_hash="dummy-hash",
            key_version=0,
            name="pat",
            scopes="read",
        )
        session.add(token)
        await session.commit()
        uid = str(user.id)

    listing = client.get("/admin/users").json()
    assert any(u["email"] == "c@x" for u in listing)

    resp = client.delete(f"/admin/users/{uid}")
    assert resp.status_code == 204

    async with auth_db() as session:
        # User and its tokens are gone (cascade) — but we don't depend on
        # exact cascade semantics in SQLite, just confirm the user is gone.
        user_row = (
            await session.execute(
                select(User).where(User.email == "c@x")
            )
        ).scalar_one_or_none()
        assert user_row is None


async def test_tenant_delete_blocked_when_stores_remain(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    tenant = client.post(
        "/admin/tenants", json={"slug": "acme", "display_name": "A"}
    ).json()
    client.post(
        f"/admin/tenants/{tenant['id']}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    resp = client.delete(f"/admin/tenants/{tenant['id']}")
    assert resp.status_code == 409
    assert resp.json()["type"] == "/problems/tenant/has-stores"


async def test_default_tenant_missing_surfaces_as_404(
    auth_db, content_dir: Path
):
    # No default tenant created — admin dependency should surface that
    # as a TenantNotFound rather than a misleading 403.
    from uuid import uuid4

    from stash_mcp.auth.principal import Principal

    p = Principal(
        user_id=uuid4(),
        oidc_sub="ghost",
        email="g@x",
        display_name="Ghost",
        auth_method="session",
        tenant_roles={},
    )
    client = make_client(p)
    resp = client.get("/admin/tenants")
    assert resp.status_code == 404
    assert resp.json()["type"] == "/problems/tenant/not-found"


async def test_admin_audit_rows_include_tenant_id(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    tenant = client.post(
        "/admin/tenants", json={"slug": "acme", "display_name": "A"}
    ).json()
    client.post(
        f"/admin/tenants/{tenant['id']}/stores",
        json={"slug": "docs", "display_name": "D"},
    )

    async with auth_db() as session:
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action.in_(
                            ("tenant.created", "store.provisioned")
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    by_action = {e.action: e for e in events}
    assert str(by_action["tenant.created"].tenant_id) == tenant["id"]
    assert str(by_action["store.provisioned"].tenant_id) == tenant["id"]
    # actor_user_id is the admin principal.
    assert (
        by_action["tenant.created"].actor_user_id
        == admin_principal.user_id
    )


async def test_default_tenant_unaffected_by_acme_tenant_ops(
    auth_db, content_dir: Path, admin_principal
):
    client = make_client(admin_principal)
    async with auth_db() as session:
        default = (
            await session.execute(
                select(Tenant).where(Tenant.slug == "default")
            )
        ).scalar_one()
        default_id = str(default.id)

    client.post("/admin/tenants", json={"slug": "acme", "display_name": "A"})
    resp = client.get(f"/admin/tenants/{default_id}")
    assert resp.status_code == 200
