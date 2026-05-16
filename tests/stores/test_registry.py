"""Tests for ``stash_mcp.stores.registry.StoreRegistry``.

Uses the shared ``auth_db`` fixture (in-memory SQLite) so the registry
can read ``stores`` rows via the real ``get_sessionmaker``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from stash_mcp.config import Config
from stash_mcp.db import engine as engine_mod
from stash_mcp.db import session as session_mod
from stash_mcp.db.models import Base, Store, Tenant
from stash_mcp.git_backend import GitBackend
from stash_mcp.stores import registry as registry_mod
from stash_mcp.stores.registry import (
    StoreAlreadyProvisionedError,
    StoreNotProvisionedError,
    StoreRegistry,
)
from stash_mcp.transactions import TransactionManager


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

    test_sessionmaker = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )
    monkeypatch.setattr(engine_mod, "_engine", test_engine, raising=False)
    monkeypatch.setattr(session_mod, "_sessionmaker", test_sessionmaker, raising=False)
    try:
        yield test_sessionmaker
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


async def _make_tenant_and_store(
    sm: async_sessionmaker[AsyncSession], *, tenant_slug: str = "acme", store_slug: str = "docs"
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


async def test_get_loads_store_with_on_disk_repo(
    auth_db, content_dir: Path
):
    tenant, _store = await _make_tenant_and_store(auth_db)
    repo_root = content_dir / str(tenant.id) / "docs"
    GitBackend.init(repo_root, author_default="test <t@x>")

    reg = StoreRegistry()
    loaded = await reg.get("acme", "docs")
    assert loaded.tenant_slug == "acme"
    assert loaded.store_slug == "docs"
    assert loaded.filesystem.content_dir == repo_root.resolve()
    assert loaded.git_backend is not None
    assert loaded.transaction_manager is not None
    assert isinstance(loaded.transaction_manager, TransactionManager)
    assert loaded.fs_for_mcp is loaded.transaction_manager


async def test_get_caches_loaded_store(auth_db, content_dir: Path):
    tenant, _ = await _make_tenant_and_store(auth_db)
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    reg = StoreRegistry()
    a = await reg.get("acme", "docs")
    b = await reg.get("acme", "docs")
    assert a is b


async def test_invalidate_triggers_reload(auth_db, content_dir: Path):
    tenant, _ = await _make_tenant_and_store(auth_db)
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    reg = StoreRegistry()
    first = await reg.get("acme", "docs")
    reg.invalidate("acme", "docs")
    second = await reg.get("acme", "docs")
    assert first is not second


async def test_provision_creates_init_repo(auth_db, content_dir: Path):
    tenant, _ = await _make_tenant_and_store(auth_db)
    repo_root = content_dir / str(tenant.id) / "docs"
    assert not repo_root.exists()

    reg = StoreRegistry()
    loaded = await reg.provision(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        store_slug="docs",
        git_remote_url=None,
    )
    assert (repo_root / ".git").is_dir()
    assert loaded.git_backend is not None
    assert loaded.transaction_manager is not None


async def test_provision_raises_when_dir_already_populated(
    auth_db, content_dir: Path
):
    tenant, _ = await _make_tenant_and_store(auth_db)
    repo_root = content_dir / str(tenant.id) / "docs"
    repo_root.mkdir(parents=True)
    (repo_root / "stray.txt").write_text("hello")

    reg = StoreRegistry()
    with pytest.raises(StoreAlreadyProvisionedError):
        await reg.provision(
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            store_slug="docs",
            git_remote_url=None,
        )


async def test_get_unknown_store_raises_key_error(auth_db, content_dir: Path):
    reg = StoreRegistry()
    with pytest.raises(KeyError):
        await reg.get("ghost", "docs")


async def test_get_with_missing_on_disk_repo_raises(auth_db, content_dir: Path):
    await _make_tenant_and_store(auth_db)
    # Do NOT create the directory.

    reg = StoreRegistry()
    with pytest.raises(StoreNotProvisionedError):
        await reg.get("acme", "docs")


async def test_concurrent_gets_load_once(
    auth_db, content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    tenant, _ = await _make_tenant_and_store(auth_db)
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    reg = StoreRegistry()
    call_count = 0
    real_load = reg._load

    async def slow_load(tenant_slug: str, store_slug: str):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return await real_load(tenant_slug, store_slug)

    monkeypatch.setattr(reg, "_load", slow_load)

    results = await asyncio.gather(
        reg.get("acme", "docs"),
        reg.get("acme", "docs"),
        reg.get("acme", "docs"),
    )
    assert call_count == 1
    assert results[0] is results[1] is results[2]


async def test_read_only_skips_transaction_manager(
    auth_db, content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(Config, "READ_ONLY", True, raising=False)
    tenant, _ = await _make_tenant_and_store(auth_db)
    GitBackend.init(content_dir / str(tenant.id) / "docs")

    reg = StoreRegistry()
    loaded = await reg.get("acme", "docs")
    assert loaded.git_backend is not None
    assert loaded.transaction_manager is None
    assert loaded.fs_for_mcp is loaded.filesystem


async def test_no_git_dir_means_no_backend(auth_db, content_dir: Path):
    tenant, _ = await _make_tenant_and_store(auth_db)
    # Create the store dir but DON'T git-init it.
    (content_dir / str(tenant.id) / "docs").mkdir(parents=True)

    reg = StoreRegistry()
    loaded = await reg.get("acme", "docs")
    assert loaded.git_backend is None
    assert loaded.transaction_manager is None
    assert loaded.fs_for_mcp is loaded.filesystem
