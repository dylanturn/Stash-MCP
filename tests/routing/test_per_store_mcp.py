"""Per-store MCP tool tests — call tools with current_store set to each
store and confirm isolation."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.auth.principal import Principal
from stash_mcp.db.models import Store, Tenant
from stash_mcp.git_backend import GitBackend
from stash_mcp.mcp_server import USE_CURRENT_STORE, create_mcp_server
from stash_mcp.routing.context import reset_current_store, set_current_store
from stash_mcp.stores.registry import LoadedStore, StoreRegistry


def _admin_principal(tenant_id: UUID) -> Principal:
    return Principal(
        user_id=uuid4(),
        oidc_sub="test-sub",
        email="t@example.com",
        display_name="Test",
        auth_method="session",
        tenant_roles={tenant_id: "admin"},
    )


@contextmanager
def _scoped_store(store: LoadedStore):
    """Set both the principal and store contextvars for the duration of a
    direct tool call. Per-tool scope enforcement (added in spec 05) reads
    both."""
    p_token = set_current_principal(_admin_principal(store.tenant_id))
    s_token = set_current_store(store)
    try:
        yield
    finally:
        reset_current_store(s_token)
        reset_current_principal(p_token)


@pytest.fixture
def mock_context():
    from fastmcp.server.context import Context, _current_context

    ctx = MagicMock(spec=Context)
    ctx.session = AsyncMock()
    ctx.send_resource_list_changed = AsyncMock()
    token = _current_context.set(ctx)
    yield ctx
    _current_context.reset(token)


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


async def test_create_and_read_via_current_store(
    auth_db, content_dir: Path, mock_context, monkeypatch: pytest.MonkeyPatch
):
    # Two provisioned stores.
    tenant_a, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    tenant_b, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="other", store_slug="docs"
    )
    # No git so writes don't need a transaction.
    (content_dir / str(tenant_a.id) / "docs").mkdir(parents=True)
    (content_dir / str(tenant_b.id) / "docs").mkdir(parents=True)

    registry = StoreRegistry()
    store_a = await registry.get("acme", "docs")
    store_b = await registry.get("other", "docs")

    mcp = create_mcp_server(USE_CURRENT_STORE)
    create = await mcp.get_tool("create_content")
    read = await mcp.get_tool("read_content")
    list_tool = await mcp.get_tool("list_content")

    # Write into store A
    with _scoped_store(store_a):
        await create.run({"path": "a-only.md", "content": "from A"})

    # Read back from store A
    with _scoped_store(store_a):
        result = await read.run({"path": "a-only.md"})
    assert "from A" in str(result.content)

    # Same path does not exist in store B
    with _scoped_store(store_b):
        with pytest.raises(Exception):
            await read.run({"path": "a-only.md"})

    # list_content reflects each store's contents
    with _scoped_store(store_a):
        a_listing = await list_tool.run({"path": "", "recursive": True})
    assert "a-only.md" in str(a_listing.content)

    with _scoped_store(store_b):
        b_listing = await list_tool.run({"path": "", "recursive": True})
    assert "a-only.md" not in str(b_listing.content)


async def test_tool_call_without_store_raises(
    auth_db, content_dir: Path, mock_context
):
    """Tools resolve the store via ``require_store`` — calling them
    without setting the contextvar is a programmer error."""
    mcp = create_mcp_server(USE_CURRENT_STORE)
    list_tool = await mcp.get_tool("list_content")
    # Set a principal so the spec-05 scope check passes; the missing-store
    # check is what we're asserting on.
    p_token = set_current_principal(_admin_principal(uuid4()))
    try:
        with pytest.raises(Exception, match="no store"):
            await list_tool.run({"path": "", "recursive": False})
    finally:
        reset_current_principal(p_token)


async def test_git_tools_registered_in_auth_mode(
    auth_db, content_dir: Path
):
    """Git tools are registered unconditionally in auth mode so that
    multi-store servers expose them regardless of the active store."""
    mcp = create_mcp_server(USE_CURRENT_STORE)
    tools = await mcp.get_tools()
    assert "log_content" in tools
    assert "diff_content" in tools
    assert "blame_content" in tools


async def test_git_tools_raise_when_store_has_no_git(
    auth_db, content_dir: Path, mock_context
):
    tenant, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    (content_dir / str(tenant.id) / "docs").mkdir(parents=True)

    registry = StoreRegistry()
    store = await registry.get("acme", "docs")
    assert store.git_backend is None

    mcp = create_mcp_server(USE_CURRENT_STORE)
    log_tool = await mcp.get_tool("log_content")

    with _scoped_store(store):
        with pytest.raises(Exception, match="Git tracking is not enabled"):
            await log_tool.run({"path": "anything", "max_count": 1})


async def test_transaction_tools_raise_when_store_has_no_git(
    auth_db, content_dir: Path, mock_context
):
    """Transaction tools are registered in auth mode but only succeed for
    stores that have git tracking."""
    tenant, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    (content_dir / str(tenant.id) / "docs").mkdir(parents=True)

    registry = StoreRegistry()
    store = await registry.get("acme", "docs")
    assert store.transaction_manager is None

    mcp = create_mcp_server(USE_CURRENT_STORE)
    start = await mcp.get_tool("start_content_transaction")

    with _scoped_store(store):
        with pytest.raises(Exception, match="Transactions are not available"):
            await start.run({})


async def test_git_tool_uses_per_store_backend(
    auth_db, content_dir: Path, mock_context
):
    tenant_a, _ = await _make_tenant_and_store(
        auth_db, tenant_slug="acme", store_slug="docs"
    )
    repo = content_dir / str(tenant_a.id) / "docs"
    GitBackend.init(repo, author_default="test <t@x>")

    # registry.get() runs GitBackend.validate() which sets local user
    # config from author_default — needed before our commit below.
    registry = StoreRegistry()
    store_a = await registry.get("acme", "docs")

    # Commit a file so log_content has something to return.
    (repo / "file.md").write_text("hello")
    import subprocess

    subprocess.run(
        ["git", "add", "file.md"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    assert store_a.git_backend is not None

    mcp = create_mcp_server(USE_CURRENT_STORE)
    log_tool = await mcp.get_tool("log_content")

    with _scoped_store(store_a):
        result = await log_tool.run({"path": "file.md", "max_count": 5})
    text = str(result.content)
    assert "init" in text
