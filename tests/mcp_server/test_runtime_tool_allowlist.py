"""Tests for the per-config tool allowlist + multi-store git/tx safety
net inside ``_instrumented_tool`` (spec 04)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.auth.principal import Principal
from stash_mcp.db.models import (
    McpServer,
    McpServerContentRoot,
    McpServerMount,
    McpServerTool,
    Store,
    Tenant,
)
from stash_mcp.errors import (
    McpServerMultiStoreGitForbidden,
    McpServerToolNotAllowed,
)
from stash_mcp.mcp_server import USE_CURRENT_STORE, create_mcp_server
from stash_mcp.routing.context import reset_current_store, set_current_store
from stash_mcp.routing.mcp_server_resolver import (
    reset_current_mcp_server,
    set_current_mcp_server,
)
from stash_mcp.stores.composite_filesystem import (
    CompositeFileSystem,
    CompositeMount,
)
from stash_mcp.stores.composite_store import CompositeLoadedStore
from stash_mcp.stores.registry import StoreRegistry


def _principal(tenant_id: UUID, scopes: str = "read,write") -> Principal:
    return Principal(
        user_id=uuid4(),
        oidc_sub="sub",
        email="e@x",
        display_name="X",
        auth_method="api_token",
        tenant_roles={tenant_id: "member"},
        claims={"scopes": scopes},
    )


@contextmanager
def _scoped(
    store: CompositeLoadedStore, config: McpServer, principal: Principal
):
    p_tok = set_current_principal(principal)
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(store)
    try:
        yield
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)


async def _seed_single_store(sm, content_dir, allowed_tools: list[str]):
    async with sm() as session:
        tenant = Tenant(slug="acme", display_name="A")
        session.add(tenant)
        await session.flush()
        store = Store(
            tenant_id=tenant.id,
            slug="docs",
            display_name="Docs",
            git_branch="main",
        )
        session.add(store)
        await session.flush()
        config = McpServer(
            tenant_id=tenant.id, slug="eng", name="E", enabled=True
        )
        session.add(config)
        await session.flush()
        for t in allowed_tools:
            session.add(
                McpServerTool(mcp_server_id=config.id, tool_name=t)
            )
        cr = McpServerContentRoot(
            mcp_server_id=config.id, name="r", kind="simple", sort_order=0
        )
        session.add(cr)
        await session.flush()
        session.add(
            McpServerMount(
                content_root_id=cr.id,
                store_id=store.id,
                subpath="",
                virtual_prefix="",
                sort_order=0,
            )
        )
        await session.commit()
        await session.refresh(tenant)
        await session.refresh(store)
        await session.refresh(config)
        # Eager-load tools/content_roots/mounts.
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        fresh = (
            await session.execute(
                select(McpServer)
                .options(
                    selectinload(McpServer.tools),
                    selectinload(McpServer.content_roots).selectinload(
                        McpServerContentRoot.mounts
                    ),
                )
                .where(McpServer.id == config.id)
            )
        ).scalar_one()
    # Build the composite store from the registry.
    on_disk = content_dir / str(tenant.id) / "docs"
    on_disk.mkdir(parents=True)
    (on_disk / "hello.md").write_text("hello world")

    registry = StoreRegistry()
    loaded = await registry.get(tenant.slug, store.slug)
    composite = CompositeLoadedStore(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        store_id=config.id,
        store_slug=config.slug,
        filesystem=CompositeFileSystem(
            [
                CompositeMount(
                    fs=loaded.fs_for_mcp, subpath="", virtual_prefix=""
                )
            ]
        ),
        git_backend=loaded.git_backend,
        transaction_manager=loaded.transaction_manager,
        underlying_store_ids=frozenset({store.id}),
        mcp_server_id=config.id,
        display_name=config.name,
    )
    return tenant, store, fresh, composite


async def _seed_multi_store(sm, content_dir, allowed_tools: list[str]):
    async with sm() as session:
        tenant = Tenant(slug="acme", display_name="A")
        session.add(tenant)
        await session.flush()
        s1 = Store(
            tenant_id=tenant.id,
            slug="docs",
            display_name="D",
            git_branch="main",
        )
        s2 = Store(
            tenant_id=tenant.id,
            slug="ops",
            display_name="O",
            git_branch="main",
        )
        session.add_all([s1, s2])
        await session.flush()
        config = McpServer(
            tenant_id=tenant.id, slug="multi", name="M", enabled=True
        )
        session.add(config)
        await session.flush()
        for t in allowed_tools:
            session.add(
                McpServerTool(mcp_server_id=config.id, tool_name=t)
            )
        cr = McpServerContentRoot(
            mcp_server_id=config.id, name="r", kind="virtual", sort_order=0
        )
        session.add(cr)
        await session.flush()
        session.add_all([
            McpServerMount(
                content_root_id=cr.id,
                store_id=s1.id,
                subpath="",
                virtual_prefix="engineering",
                sort_order=0,
            ),
            McpServerMount(
                content_root_id=cr.id,
                store_id=s2.id,
                subpath="",
                virtual_prefix="ops",
                sort_order=1,
            ),
        ])
        await session.commit()
        await session.refresh(tenant)

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        fresh = (
            await session.execute(
                select(McpServer)
                .options(
                    selectinload(McpServer.tools),
                    selectinload(McpServer.content_roots).selectinload(
                        McpServerContentRoot.mounts
                    ),
                )
                .where(McpServer.id == config.id)
            )
        ).scalar_one()

    (content_dir / str(tenant.id) / "docs").mkdir(parents=True)
    (content_dir / str(tenant.id) / "ops").mkdir(parents=True)
    (content_dir / str(tenant.id) / "docs" / "engineering.md").write_text("eng")
    (content_dir / str(tenant.id) / "ops" / "runbook.md").write_text("rb")

    registry = StoreRegistry()
    loaded1 = await registry.get(tenant.slug, "docs")
    loaded2 = await registry.get(tenant.slug, "ops")
    composite = CompositeLoadedStore(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        store_id=config.id,
        store_slug=config.slug,
        filesystem=CompositeFileSystem(
            [
                CompositeMount(
                    fs=loaded1.filesystem,
                    subpath="",
                    virtual_prefix="engineering",
                ),
                CompositeMount(
                    fs=loaded2.filesystem,
                    subpath="",
                    virtual_prefix="ops",
                ),
            ]
        ),
        git_backend=None,  # multi-store
        transaction_manager=None,
        underlying_store_ids=frozenset({s1.id, s2.id}),
        mcp_server_id=config.id,
        display_name=config.name,
    )
    return tenant, fresh, composite


async def test_allowlisted_tool_succeeds(
    auth_db: async_sessionmaker, content_dir: Path, mock_context
):
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content", "list_content"]
    )

    mcp = create_mcp_server(USE_CURRENT_STORE)
    read = await mcp.get_tool("read_content")
    with _scoped(composite, config, _principal(tenant.id)):
        result = await read.run({"path": "hello.md"})
    assert "hello world" in str(result.content)


async def test_non_allowlisted_tool_rejected(
    auth_db, content_dir: Path, mock_context
):
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    create = await mcp.get_tool("create_content")
    with _scoped(composite, config, _principal(tenant.id)):
        with pytest.raises(McpServerToolNotAllowed):
            await create.run({"path": "new.md", "content": "x"})


async def test_multi_store_git_tool_rejected(
    auth_db, content_dir: Path, mock_context
):
    tenant, config, composite = await _seed_multi_store(
        auth_db, content_dir, ["read_content", "log_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    log_tool = await mcp.get_tool("log_content")
    with _scoped(composite, config, _principal(tenant.id)):
        with pytest.raises(McpServerMultiStoreGitForbidden):
            await log_tool.run({"path": "engineering/engineering.md"})


async def test_multi_store_read_works(
    auth_db, content_dir: Path, mock_context
):
    tenant, config, composite = await _seed_multi_store(
        auth_db, content_dir, ["read_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    read = await mcp.get_tool("read_content")
    with _scoped(composite, config, _principal(tenant.id)):
        result = await read.run({"path": "engineering/engineering.md"})
    assert "eng" in str(result.content)
    with _scoped(composite, config, _principal(tenant.id)):
        result = await read.run({"path": "ops/runbook.md"})
    assert "rb" in str(result.content)


async def test_unscoped_request_keeps_full_catalog(
    auth_db, content_dir: Path, mock_context
):
    """An unscoped request (no McpServer in scope) sees no per-config
    gating — the legacy URL-based flow is unchanged."""
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    create = await mcp.get_tool("create_content")
    # No set_current_mcp_server → unscoped.
    p_tok = set_current_principal(_principal(tenant.id))
    s_tok = set_current_store(composite)
    try:
        # No tool-allowlist error; create succeeds.
        await create.run({"path": "ad-hoc.md", "content": "added"})
    finally:
        reset_current_store(s_tok)
        reset_current_principal(p_tok)
