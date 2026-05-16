"""Per-tool scope enforcement (spec 05).

Direct invocation of MCP tool functions with principals of varying
auth_method/scope, asserting that the wrapper raises ``AuthError`` for
insufficient scope and lets the call through otherwise.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
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

from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.auth.principal import Principal
from stash_mcp.config import Config
from stash_mcp.db import engine as engine_mod
from stash_mcp.db import session as session_mod
from stash_mcp.db.models import Base, Store, Tenant
from stash_mcp.mcp_server import USE_CURRENT_STORE, create_mcp_server
from stash_mcp.routing.context import reset_current_store, set_current_store
from stash_mcp.stores import registry as registry_mod
from stash_mcp.stores.registry import StoreRegistry


def _enable_sqlite_fks(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
async def auth_db(monkeypatch: pytest.MonkeyPatch):
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    _enable_sqlite_fks(test_engine)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )
    monkeypatch.setattr(engine_mod, "_engine", test_engine, raising=False)
    monkeypatch.setattr(session_mod, "_sessionmaker", sm, raising=False)
    monkeypatch.setattr(registry_mod, "_registry", None, raising=False)
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "READ_ONLY", False, raising=False)
    try:
        yield sm
    finally:
        await test_engine.dispose()


@pytest.fixture
def content_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "content"
    root.mkdir()
    monkeypatch.setattr(Config, "CONTENT_DIR", root, raising=False)
    return root


@pytest.fixture
def mock_context():
    from fastmcp.server.context import Context, _current_context

    ctx = MagicMock(spec=Context)
    ctx.session = AsyncMock()
    ctx.send_resource_list_changed = AsyncMock()
    token = _current_context.set(ctx)
    yield ctx
    _current_context.reset(token)


async def _make_store(sm: async_sessionmaker, content_dir: Path):
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
    (content_dir / str(tenant.id) / "docs").mkdir(parents=True)
    registry = StoreRegistry()
    loaded = await registry.get("acme", "docs")
    return tenant, loaded


def _principal(
    *,
    tenant_id: UUID,
    role: str | None,
    auth_method: str = "session",
    api_scopes: str | None = None,
) -> Principal:
    tenant_roles = {tenant_id: role} if role is not None else {}
    claims = {"scopes": api_scopes} if api_scopes is not None else {}
    return Principal(
        user_id=uuid4(),
        oidc_sub="t",
        email="t@x",
        display_name="T",
        auth_method=auth_method,  # type: ignore[arg-type]
        tenant_roles=tenant_roles,  # type: ignore[arg-type]
        claims=claims,
    )


async def _call(mcp, name: str, args: dict):
    tool = await mcp.get_tool(name)
    return await tool.run(args)


async def test_member_can_read_and_write(
    auth_db, content_dir, mock_context
):
    tenant, store = await _make_store(auth_db, content_dir)
    mcp = create_mcp_server(USE_CURRENT_STORE)
    p = _principal(tenant_id=tenant.id, role="member")
    p_tok = set_current_principal(p)
    s_tok = set_current_store(store)
    try:
        await _call(mcp, "create_content", {"path": "f.md", "content": "x"})
        result = await _call(mcp, "read_content", {"path": "f.md"})
        assert "x" in str(result.content)
    finally:
        reset_current_store(s_tok)
        reset_current_principal(p_tok)


async def test_no_membership_denies_read(
    auth_db, content_dir, mock_context
):
    tenant, store = await _make_store(auth_db, content_dir)
    mcp = create_mcp_server(USE_CURRENT_STORE)
    p = _principal(tenant_id=tenant.id, role=None)
    p_tok = set_current_principal(p)
    s_tok = set_current_store(store)
    try:
        with pytest.raises(Exception, match="read"):
            await _call(mcp, "list_content", {"path": "", "recursive": False})
    finally:
        reset_current_store(s_tok)
        reset_current_principal(p_tok)


async def test_api_token_read_only_blocked_from_write(
    auth_db, content_dir, mock_context
):
    tenant, store = await _make_store(auth_db, content_dir)
    mcp = create_mcp_server(USE_CURRENT_STORE)
    p = _principal(
        tenant_id=tenant.id,
        role="member",  # role would otherwise grant write
        auth_method="api_token",
        api_scopes="read",  # but the token row scopes win
    )
    p_tok = set_current_principal(p)
    s_tok = set_current_store(store)
    try:
        with pytest.raises(Exception, match="write"):
            await _call(
                mcp,
                "create_content",
                {"path": "x.md", "content": "x"},
            )
        # Read still works.
        await _call(mcp, "list_content", {"path": "", "recursive": False})
    finally:
        reset_current_store(s_tok)
        reset_current_principal(p_tok)


async def test_api_token_with_write_scope_can_write(
    auth_db, content_dir, mock_context
):
    tenant, store = await _make_store(auth_db, content_dir)
    mcp = create_mcp_server(USE_CURRENT_STORE)
    p = _principal(
        tenant_id=tenant.id,
        role=None,  # api_token ignores role entirely
        auth_method="api_token",
        api_scopes="read,write",
    )
    p_tok = set_current_principal(p)
    s_tok = set_current_store(store)
    try:
        await _call(
            mcp,
            "create_content",
            {"path": "x.md", "content": "x"},
        )
    finally:
        reset_current_store(s_tok)
        reset_current_principal(p_tok)


async def test_auth_disabled_skips_scope_check(
    auth_db, content_dir, mock_context, monkeypatch
):
    # Even with no principal, AUTH_ENABLED=False means the wrapper skips
    # scope enforcement entirely (no behaviour change).
    tenant, store = await _make_store(auth_db, content_dir)
    monkeypatch.setattr(Config, "AUTH_ENABLED", False, raising=False)
    mcp = create_mcp_server(USE_CURRENT_STORE)
    s_tok = set_current_store(store)
    try:
        # Should not raise — even with no principal set.
        await _call(mcp, "list_content", {"path": "", "recursive": False})
    finally:
        reset_current_store(s_tok)
