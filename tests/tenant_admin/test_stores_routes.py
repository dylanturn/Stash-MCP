"""End-to-end tests for ``/tenants/{tenant_id}/stores/*``."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from stash_mcp.db.models import AuditEvent, Store

from .conftest import make_full_client


async def test_create_store_creates_row_and_on_disk_repo(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    resp = client.post(
        f"/tenants/{acme_tenant.id}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "docs"
    assert body["tenant_id"] == str(acme_tenant.id)

    on_disk = content_dir / str(acme_tenant.id) / "docs"
    assert on_disk.exists()
    assert (on_disk / ".git").exists()

    async with auth_db() as session:
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "store.provisioned"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1
    assert events[0].tenant_id == acme_tenant.id


async def test_create_duplicate_slug_409s(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    r1 = client.post(
        f"/tenants/{acme_tenant.id}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    assert r1.status_code == 201
    r2 = client.post(
        f"/tenants/{acme_tenant.id}/stores",
        json={"slug": "docs", "display_name": "Docs 2"},
    )
    assert r2.status_code == 409
    assert r2.json()["type"] == "/problems/store/already-exists"


async def test_patch_display_name_only(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    client.post(
        f"/tenants/{acme_tenant.id}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    resp = client.patch(
        f"/tenants/{acme_tenant.id}/stores/docs",
        json={"display_name": "Docs (renamed)"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Docs (renamed)"

    async with auth_db() as session:
        rename_events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "store.renamed"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rename_events) == 1
    detail = json.loads(rename_events[0].detail)
    assert detail == {
        "display_name": {"old": "Docs", "new": "Docs (renamed)"}
    }


async def test_patch_git_remote_and_branch(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    client.post(
        f"/tenants/{acme_tenant.id}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    resp = client.patch(
        f"/tenants/{acme_tenant.id}/stores/docs",
        json={
            "git_remote_url": "https://example.com/foo.git",
            "git_branch": "develop",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["git_remote_url"] == "https://example.com/foo.git"
    assert body["git_branch"] == "develop"

    async with auth_db() as session:
        rename_events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "store.renamed"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rename_events) == 1
    detail = json.loads(rename_events[0].detail)
    assert detail["git_remote_url"]["new"] == "https://example.com/foo.git"
    assert detail["git_branch"]["new"] == "develop"


async def test_delete_without_confirm_400s(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    client.post(
        f"/tenants/{acme_tenant.id}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    resp = client.delete(f"/tenants/{acme_tenant.id}/stores/docs")
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/confirmation-required"
    assert (content_dir / str(acme_tenant.id) / "docs").exists()


async def test_delete_with_confirm_removes_row_and_disk(
    auth_db: async_sessionmaker,
    content_dir: Path,
    acme_tenant,
    acme_admin_principal,
):
    client = make_full_client(acme_admin_principal)
    client.post(
        f"/tenants/{acme_tenant.id}/stores",
        json={"slug": "docs", "display_name": "Docs"},
    )
    resp = client.delete(
        f"/tenants/{acme_tenant.id}/stores/docs?confirm=true"
    )
    assert resp.status_code == 204
    assert not (content_dir / str(acme_tenant.id) / "docs").exists()

    async with auth_db() as session:
        rows = (
            (
                await session.execute(
                    select(Store).where(Store.tenant_id == acme_tenant.id)
                )
            )
            .scalars()
            .all()
        )
    assert rows == []

    async with auth_db() as session:
        del_events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "store.deleted"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(del_events) == 1


async def test_list_returns_stores_in_slug_order(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    for slug in ("zebra", "alpha", "mango"):
        client.post(
            f"/tenants/{acme_tenant.id}/stores",
            json={"slug": slug, "display_name": slug},
        )
    resp = client.get(f"/tenants/{acme_tenant.id}/stores")
    assert resp.status_code == 200
    slugs = [r["slug"] for r in resp.json()]
    assert slugs == ["alpha", "mango", "zebra"]


async def test_get_missing_returns_404(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/stores/nonesuch")
    assert resp.status_code == 404
    assert resp.json()["type"] == "/problems/store/not-found"
