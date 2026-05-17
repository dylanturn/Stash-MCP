"""Fixtures for the tenant-admin route tests.

Builds the same in-memory app the admin/conftest builds, but also
includes the new ``/tenants/{id}/*`` router so the tests can exercise
both surfaces. Re-uses the existing fixtures by importing the module.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.testclient import TestClient

from stash_mcp.admin.routes import router as admin_router
from stash_mcp.auth.principal import Principal
from stash_mcp.auth.routes import router as auth_router
from stash_mcp.db.models import Tenant, User
from stash_mcp.errors import install_problem_handlers
from stash_mcp.tenant_admin import router as tenant_admin_router

# Re-export shared fixtures (these are pytest fixtures defined by name
# resolution in tests/admin/conftest.py — pytest sees them via the test
# directory's conftest, not via import, so re-define here.)
from tests.admin.conftest import (  # noqa: F401
    _PrincipalInjector,
    _auth_config_defaults,
    _ensure_default_tenant,
    _principal,
    _reset_registry_singleton,
    auth_db,
    content_dir,
)


def make_full_app(principal: Principal | None):
    """Mount /auth, /admin, AND /tenants on one app with the principal pinned."""
    from fastapi import FastAPI

    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(tenant_admin_router)
    return _PrincipalInjector(app, principal)


def make_full_client(principal: Principal | None) -> TestClient:
    return TestClient(make_full_app(principal))


async def _make_user(auth_db, *, email: str) -> User:
    async with auth_db() as session:
        user = User(oidc_sub=email, email=email, display_name=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_tenant(auth_db, *, slug: str) -> Tenant:
    async with auth_db() as session:
        t = Tenant(slug=slug, display_name=slug.upper())
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest.fixture
async def default_tenant(auth_db: async_sessionmaker):
    return await _ensure_default_tenant(auth_db)


@pytest.fixture
async def acme_tenant(auth_db: async_sessionmaker):
    return await _make_tenant(auth_db, slug="acme")


@pytest.fixture
async def beta_tenant(auth_db: async_sessionmaker):
    return await _make_tenant(auth_db, slug="beta")


@pytest.fixture
async def acme_admin_principal(auth_db, acme_tenant):
    user = await _make_user(auth_db, email="acme-admin@x")
    return _principal(
        tenant_roles={acme_tenant.id: "admin"}, user_id=user.id
    )


@pytest.fixture
async def acme_member_principal(auth_db, acme_tenant):
    user = await _make_user(auth_db, email="acme-member@x")
    return _principal(
        tenant_roles={acme_tenant.id: "member"}, user_id=user.id
    )


@pytest.fixture
async def global_admin_principal(auth_db, default_tenant):
    """Admin on the default tenant but NOT on acme."""
    user = await _make_user(auth_db, email="global-admin@x")
    return _principal(
        tenant_roles={default_tenant.id: "admin"}, user_id=user.id
    )


__all__ = [
    "auth_db",
    "content_dir",
    "make_full_app",
    "make_full_client",
    "default_tenant",
    "acme_tenant",
    "beta_tenant",
    "acme_admin_principal",
    "acme_member_principal",
    "global_admin_principal",
    "_make_user",
    "_make_tenant",
    "_principal",
]
