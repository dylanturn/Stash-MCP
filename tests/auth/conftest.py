"""Shared fixtures for the auth provider/middleware test suite.

The providers all reach for ``db.session.get_sessionmaker()`` at request
time, which in turn calls ``db.engine.get_engine()`` and reads
``Config.DATABASE_URL``. The ``auth_db`` fixture wires up an isolated
in-memory SQLite (with ``StaticPool`` so every connection sees the same
DB) and monkey-patches both module-level singletons so any code that
imports ``get_session(maker)`` gets the test DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

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
    """In-memory SQLite engine wired into the global session factory."""
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

    # Force the lazy module-level singletons to our test instances. Reset on
    # teardown so the next test starts clean.
    monkeypatch.setattr(engine_mod, "_engine", test_engine, raising=False)
    monkeypatch.setattr(session_mod, "_sessionmaker", test_sessionmaker, raising=False)

    try:
        yield test_sessionmaker
    finally:
        await test_engine.dispose()
        monkeypatch.setattr(engine_mod, "_engine", None, raising=False)
        monkeypatch.setattr(session_mod, "_sessionmaker", None, raising=False)


@pytest.fixture(autouse=True)
def _auth_config_defaults(monkeypatch: pytest.MonkeyPatch):
    """Set sane defaults for auth-related Config knobs in tests."""
    monkeypatch.setattr(Config, "AUTH_TOKEN_HMAC_KEYS", ["k0"], raising=False)
    monkeypatch.setattr(Config, "SESSION_SECRET", "test-secret", raising=False)
    monkeypatch.setattr(Config, "SESSION_MAX_AGE_SECONDS", 3600, raising=False)
    monkeypatch.setattr(Config, "OIDC_GROUPS_CLAIM", "groups", raising=False)
    monkeypatch.setattr(Config, "OIDC_ADMIN_GROUP", "stash-admins", raising=False)
    yield
