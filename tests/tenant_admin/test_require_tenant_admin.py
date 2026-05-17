"""Tests for ``require_tenant_admin``."""

from __future__ import annotations

from pathlib import Path

from stash_mcp.errors import PROBLEM_MEDIA_TYPE

from .conftest import (
    _make_user,
    _principal,
    make_full_client,
)


async def test_unauthenticated_returns_401(
    auth_db, content_dir: Path, acme_tenant
):
    client = make_full_client(None)
    resp = client.get(f"/tenants/{acme_tenant.id}/stores")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Bearer")
    assert resp.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert resp.json()["type"] == "/problems/auth/unauthenticated"


async def test_non_member_returns_403(
    auth_db, content_dir: Path, acme_tenant
):
    user = await _make_user(auth_db, email="orphan@x")
    principal = _principal(tenant_roles={}, user_id=user.id)
    client = make_full_client(principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/stores")
    assert resp.status_code == 403


async def test_member_but_not_admin_returns_403(
    auth_db, content_dir: Path, acme_tenant, acme_member_principal
):
    client = make_full_client(acme_member_principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/stores")
    assert resp.status_code == 403
    assert resp.json()["type"] == "/problems/auth/forbidden"


async def test_admin_on_different_tenant_returns_403(
    auth_db, content_dir: Path, acme_tenant, beta_tenant
):
    user = await _make_user(auth_db, email="beta-admin@x")
    principal = _principal(
        tenant_roles={beta_tenant.id: "admin"}, user_id=user.id
    )
    client = make_full_client(principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/stores")
    assert resp.status_code == 403


async def test_admin_on_tenant_passes_through(
    auth_db, content_dir: Path, acme_tenant, acme_admin_principal
):
    client = make_full_client(acme_admin_principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/stores")
    assert resp.status_code == 200


async def test_global_admin_on_default_is_not_tenant_admin_on_other(
    auth_db, content_dir: Path, acme_tenant, global_admin_principal
):
    """Surprising case: a global admin (admin on `default`) is NOT a
    tenant admin on `acme` unless they also have an admin membership
    there. They must use ``/admin/*``, not ``/tenants/*``."""
    client = make_full_client(global_admin_principal)
    resp = client.get(f"/tenants/{acme_tenant.id}/stores")
    assert resp.status_code == 403


async def test_unknown_tenant_returns_404(
    auth_db, content_dir: Path, acme_admin_principal
):
    from uuid import uuid4

    client = make_full_client(acme_admin_principal)
    resp = client.get(f"/tenants/{uuid4()}/stores")
    assert resp.status_code == 404
    assert resp.json()["type"] == "/problems/tenant/not-found"
