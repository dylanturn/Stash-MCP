"""Tests for scoping API tokens to an MCP-server config (spec 03)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.testclient import TestClient

from stash_mcp.auth.principal import Principal
from stash_mcp.auth.routes import router as auth_router
from stash_mcp.db.models import AuditEvent, McpServer, User
from stash_mcp.errors import install_problem_handlers
from stash_mcp.tenant_admin import router as tenant_admin_router

from tests.admin.conftest import (  # noqa: F401
    _PrincipalInjector,
    _auth_config_defaults,
    _ensure_default_tenant,
    _principal,
    _reset_registry_singleton,
    auth_db,
    content_dir,
)


def _make_client(principal: Principal | None) -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(auth_router)
    app.include_router(tenant_admin_router)
    return TestClient(_PrincipalInjector(app, principal))


async def _make_user(auth_db, *, email: str) -> User:
    async with auth_db() as session:
        u = User(oidc_sub=email, email=email, display_name=email)
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


async def _seed_user_with_tenant(auth_db, role: str = "admin"):
    from stash_mcp.db.models import Tenant

    async with auth_db() as session:
        tenant = Tenant(slug="acme", display_name="Acme")
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
    user = await _make_user(auth_db, email=f"{role}@x")
    return tenant, user, _principal(
        tenant_roles={tenant.id: role}, user_id=user.id
    )


async def _create_server(client, tenant_id, slug, enabled=True):
    resp = client.post(
        f"/tenants/{tenant_id}/mcp-servers",
        json={"slug": slug, "name": slug, "enabled": enabled},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_token_unscoped(auth_db, content_dir: Path):
    tenant, user, principal = await _seed_user_with_tenant(auth_db)
    client = _make_client(principal)
    resp = client.post(
        "/auth/tokens", json={"name": "legacy", "scopes": ["read"]}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["mcp_server"] is None


async def test_create_token_with_valid_mcp_server(
    auth_db: async_sessionmaker, content_dir: Path
):
    tenant, user, principal = await _seed_user_with_tenant(auth_db)
    client = _make_client(principal)
    server = await _create_server(client, tenant.id, "eng")
    resp = client.post(
        "/auth/tokens",
        json={
            "name": "scoped",
            "scopes": ["read"],
            "mcp_server_id": server["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mcp_server"] is not None
    assert body["mcp_server"]["slug"] == "eng"
    assert body["mcp_server"]["tenant_slug"] == "acme"


async def test_create_token_cross_tenant_forbidden(
    auth_db: async_sessionmaker, content_dir: Path
):
    """A member of acme cannot mint a token scoped to a beta config."""
    from stash_mcp.db.models import Tenant

    async with auth_db() as session:
        beta = Tenant(slug="beta", display_name="Beta")
        session.add(beta)
        await session.commit()
        await session.refresh(beta)

    # Provision a config in beta as a beta admin.
    beta_user = await _make_user(auth_db, email="beta-admin@x")
    beta_admin = _principal(
        tenant_roles={beta.id: "admin"}, user_id=beta_user.id
    )
    beta_client = _make_client(beta_admin)
    beta_server = await _create_server(beta_client, beta.id, "beta-config")

    # acme user tries to bind to it.
    tenant, user, principal = await _seed_user_with_tenant(auth_db)
    client = _make_client(principal)
    resp = client.post(
        "/auth/tokens",
        json={
            "name": "x",
            "scopes": ["read"],
            "mcp_server_id": beta_server["id"],
        },
    )
    assert resp.status_code == 403
    assert resp.json()["type"] == "/problems/mcp-server/forbidden"


async def test_create_token_nonexistent_config_404s(
    auth_db, content_dir: Path
):
    tenant, user, principal = await _seed_user_with_tenant(auth_db)
    client = _make_client(principal)
    resp = client.post(
        "/auth/tokens",
        json={
            "name": "x",
            "scopes": ["read"],
            "mcp_server_id": str(uuid4()),
        },
    )
    assert resp.status_code == 404
    assert resp.json()["type"] == "/problems/mcp-server/not-found"


async def test_create_token_disabled_config_allowed(
    auth_db, content_dir: Path
):
    """Binding to a disabled config succeeds — runtime (04) refuses
    to serve it, but the binding itself is fine."""
    tenant, user, principal = await _seed_user_with_tenant(auth_db)
    client = _make_client(principal)
    server = await _create_server(client, tenant.id, "off", enabled=False)
    resp = client.post(
        "/auth/tokens",
        json={
            "name": "scoped",
            "scopes": ["read"],
            "mcp_server_id": server["id"],
        },
    )
    assert resp.status_code == 201


async def test_list_tokens_populates_mcp_server(
    auth_db, content_dir: Path
):
    tenant, user, principal = await _seed_user_with_tenant(auth_db)
    client = _make_client(principal)
    server = await _create_server(client, tenant.id, "eng")
    client.post(
        "/auth/tokens",
        json={
            "name": "scoped",
            "scopes": ["read"],
            "mcp_server_id": server["id"],
        },
    )
    client.post(
        "/auth/tokens",
        json={"name": "unscoped", "scopes": ["read"]},
    )

    resp = client.get("/auth/tokens")
    assert resp.status_code == 200
    by_name = {t["name"]: t for t in resp.json()}
    assert by_name["scoped"]["mcp_server"]["slug"] == "eng"
    assert by_name["unscoped"]["mcp_server"] is None


async def test_visible_mcp_servers_empty_for_no_memberships(
    auth_db, content_dir: Path
):
    user = await _make_user(auth_db, email="lonely@x")
    principal = _principal(tenant_roles={}, user_id=user.id)
    client = _make_client(principal)
    resp = client.get("/auth/visible-mcp-servers")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_visible_mcp_servers_groups_by_tenant(
    auth_db: async_sessionmaker, content_dir: Path
):
    from stash_mcp.db.models import Tenant

    async with auth_db() as session:
        acme = Tenant(slug="acme", display_name="Acme")
        beta = Tenant(slug="beta", display_name="Beta")
        session.add_all([acme, beta])
        await session.commit()
        await session.refresh(acme)
        await session.refresh(beta)

    # Provision configs in both tenants as their respective admins.
    a_user = await _make_user(auth_db, email="aa@x")
    a_admin = _principal(
        tenant_roles={acme.id: "admin"}, user_id=a_user.id
    )
    await _create_server(_make_client(a_admin), acme.id, "ace-cfg-z")
    await _create_server(_make_client(a_admin), acme.id, "ace-cfg-a")
    await _create_server(
        _make_client(a_admin), acme.id, "ace-cfg-off", enabled=False
    )

    b_user = await _make_user(auth_db, email="bb@x")
    b_admin = _principal(
        tenant_roles={beta.id: "admin"}, user_id=b_user.id
    )
    await _create_server(_make_client(b_admin), beta.id, "beta-x")

    # User who is member of both.
    multi = await _make_user(auth_db, email="multi@x")
    multi_principal = _principal(
        tenant_roles={acme.id: "member", beta.id: "member"},
        user_id=multi.id,
    )
    resp = _make_client(multi_principal).get("/auth/visible-mcp-servers")
    assert resp.status_code == 200
    rows = resp.json()
    # Disabled config filtered out; sorted by (tenant_slug, server.slug).
    assert [(r["tenant_slug"], r["slug"]) for r in rows] == [
        ("acme", "ace-cfg-a"),
        ("acme", "ace-cfg-z"),
        ("beta", "beta-x"),
    ]


async def test_audit_records_mcp_server_id(
    auth_db: async_sessionmaker, content_dir: Path
):
    tenant, user, principal = await _seed_user_with_tenant(auth_db)
    client = _make_client(principal)
    server = await _create_server(client, tenant.id, "eng")
    client.post(
        "/auth/tokens",
        json={
            "name": "scoped",
            "scopes": ["read"],
            "mcp_server_id": server["id"],
        },
    )
    async with auth_db() as session:
        rows = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "token.issued"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    detail = json.loads(rows[0].detail)
    assert detail["mcp_server_id"] == server["id"]


async def test_legacy_unscoped_token_does_not_carry_mcp_server_id_claim(
    auth_db, content_dir: Path, monkeypatch
):
    """Pre-03 ApiTokenAuthProvider behaviour: unscoped tokens stay
    that way; the new claim is absent from Principal.claims when the
    column is NULL."""
    from sqlalchemy import select

    from stash_mcp.auth.api_token_provider import ApiTokenAuthProvider
    from stash_mcp.auth.tokens import generate_token, hash_with_active_key
    from stash_mcp.config import Config
    from stash_mcp.db.models import ApiToken

    tenant, user, _ = await _seed_user_with_tenant(auth_db)
    plaintext = generate_token()
    keys = Config.AUTH_TOKEN_HMAC_KEYS
    token_hash, key_version = hash_with_active_key(plaintext, keys=keys)
    async with auth_db() as session:
        session.add(
            ApiToken(
                user_id=user.id,
                token_hash=token_hash,
                key_version=key_version,
                name="legacy",
                scopes="read",
            )
        )
        await session.commit()

    # Hand-build a Starlette Request stub with the bearer header.
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [
            (
                b"authorization",
                f"Bearer {plaintext}".encode("ascii"),
            )
        ],
    }
    request = Request(scope)
    provider = ApiTokenAuthProvider()
    principal = await provider.authenticate(request)
    assert principal is not None
    assert "mcp_server_id" not in principal.claims
