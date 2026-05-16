"""Fixtures for the routing test suite.

Stands up the same in-memory SQLite + sessionmaker monkey-patching as
``tests/auth/conftest.py`` and ``tests/stores/test_registry.py``, plus a
content_dir under ``tmp_path`` so the registry can find on-disk repos.
"""

from __future__ import annotations

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
from stash_mcp.db.models import Base
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
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    return root


@pytest.fixture(autouse=True)
def _reset_registry_singleton(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(registry_mod, "_registry", None, raising=False)
    yield
    monkeypatch.setattr(registry_mod, "_registry", None, raising=False)
