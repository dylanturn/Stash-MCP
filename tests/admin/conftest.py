"""Shared fixtures for the admin/auth-route test suites."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from stash_mcp.admin.routes import router as admin_router
from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.auth.principal import Principal
from stash_mcp.auth.routes import router as auth_router
from stash_mcp.config import Config
from stash_mcp.db import engine as engine_mod
from stash_mcp.db import session as session_mod
from stash_mcp.db.models import Base, Tenant
from stash_mcp.errors import install_problem_handlers
from stash_mcp.stores import registry as registry_mod


def _enable_sqlite_fks(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
async def auth_db(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[
    async_sessionmaker[AsyncSession]
]:
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    _enable_sqlite_fks(test_engine)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    test_sm = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )
    monkeypatch.setattr(engine_mod, "_engine", test_engine, raising=False)
    monkeypatch.setattr(session_mod, "_sessionmaker", test_sm, raising=False)
    try:
        yield test_sm
    finally:
        await test_engine.dispose()
        monkeypatch.setattr(engine_mod, "_engine", None, raising=False)
        monkeypatch.setattr(session_mod, "_sessionmaker", None, raising=False)


@pytest.fixture
def content_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "content"
    root.mkdir()
    monkeypatch.setattr(Config, "CONTENT_DIR", root, raising=False)
    monkeypatch.setattr(Config, "READ_ONLY", False, raising=False)
    return root


@pytest.fixture(autouse=True)
def _reset_registry_singleton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(registry_mod, "_registry", None, raising=False)
    yield
    monkeypatch.setattr(registry_mod, "_registry", None, raising=False)


@pytest.fixture(autouse=True)
def _auth_config_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        Config, "AUTH_TOKEN_HMAC_KEYS", ["test-key-0"], raising=False
    )
    monkeypatch.setattr(Config, "SESSION_SECRET", "test-secret", raising=False)
    monkeypatch.setattr(
        Config, "SESSION_MAX_AGE_SECONDS", 3600, raising=False
    )
    monkeypatch.setattr(Config, "OIDC_GROUPS_CLAIM", "groups", raising=False)
    monkeypatch.setattr(
        Config, "OIDC_ADMIN_GROUP", "stash-admins", raising=False
    )
    yield


async def _ensure_default_tenant(
    sm: async_sessionmaker[AsyncSession],
) -> Tenant:
    async with sm() as session:
        from sqlalchemy import select

        existing = (
            await session.execute(
                select(Tenant).where(Tenant.slug == "default")
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        tenant = Tenant(slug="default", display_name="Default tenant")
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        return tenant


def _principal(
    *,
    tenant_roles: dict[UUID, str],
    auth_method: str = "session",
    user_id: UUID | None = None,
    claims: dict | None = None,
) -> Principal:
    return Principal(
        user_id=user_id or uuid4(),
        oidc_sub="test-sub",
        email="test@example.com",
        display_name="Test",
        auth_method=auth_method,  # type: ignore[arg-type]
        tenant_roles=tenant_roles,  # type: ignore[arg-type]
        claims=claims or {},
    )


class _PrincipalInjector:
    """ASGI middleware that pins a principal for every request."""

    def __init__(self, app, principal: Principal | None):
        self.app = app
        self.principal = principal

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.principal is None:
            await self.app(scope, receive, send)
            return
        token = set_current_principal(self.principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_principal(token)


def make_admin_app(principal: Principal | None):
    """Build a minimal FastAPI app with the /auth and /admin routers and
    the given fixed principal."""
    from fastapi import FastAPI

    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(auth_router)
    app.include_router(admin_router)
    asgi = _PrincipalInjector(app, principal)
    return asgi


def make_client(principal: Principal | None) -> TestClient:
    return TestClient(make_admin_app(principal))


__all__ = [
    "auth_db",
    "content_dir",
    "make_admin_app",
    "make_client",
    "_PrincipalInjector",
    "_principal",
    "_ensure_default_tenant",
]
