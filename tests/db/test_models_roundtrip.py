"""Round-trip tests for the auth schema using an in-memory SQLite DB.

A StaticPool is required so all connections share the same in-memory
database; without it each new connection gets its own DB and the test
silently sees empty state.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from alembic import command
from stash_mcp.db.models import (
    ApiToken,
    AuditEvent,
    Base,
    Membership,
    Store,
    Tenant,
    User,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _enable_sqlite_fks(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
async def engine() -> AsyncEngine:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        future=True,
    )
    _enable_sqlite_fks(eng)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)


def test_alembic_upgrade_head_against_fresh_sqlite_file(tmp_path: Path):
    """Spec acceptance: ``alembic upgrade head`` against a fresh sqlite file
    produces all six tables.

    Synchronous on purpose: alembic env.py calls asyncio.run(), which can't
    be nested inside pytest-asyncio's running loop."""
    import sqlite3

    db_path = tmp_path / "stash-auth.db"
    cfg = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(cfg, "head")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    names = {r[0] for r in rows}
    expected = {
        "tenants",
        "users",
        "memberships",
        "stores",
        "api_tokens",
        "audit_events",
    }
    assert expected.issubset(names), f"missing tables: {expected - names}"


async def test_insert_and_read_back_full_object_graph(sessionmaker):
    async with sessionmaker() as session:
        tenant = Tenant(slug="acme", display_name="Acme Inc")
        user = User(oidc_sub="oidc|1", email="a@x", display_name="A")
        session.add_all([tenant, user])
        await session.flush()

        membership = Membership(
            user_id=user.id, tenant_id=tenant.id, role="admin", source="oidc_group"
        )
        store = Store(
            tenant_id=tenant.id, slug="docs", display_name="Docs", git_branch="main"
        )
        token = ApiToken(
            user_id=user.id,
            token_hash="h" * 64,
            key_version=0,
            name="laptop",
            scopes="read,write",
        )
        audit = AuditEvent(
            actor_user_id=user.id,
            actor_kind="user",
            action="token.issued",
            target_kind="token",
            target_id=str(token.id),
            tenant_id=tenant.id,
            detail='{"name": "laptop"}',
        )
        session.add_all([membership, store, token, audit])
        await session.commit()

    async with sessionmaker() as session:
        loaded = (
            await session.execute(select(Tenant).where(Tenant.slug == "acme"))
        ).scalar_one()
        assert loaded.display_name == "Acme Inc"
        assert loaded.created_at is not None


async def test_orphan_membership_rejected(sessionmaker):
    bad_user = uuid.uuid4()
    bad_tenant = uuid.uuid4()
    async with sessionmaker() as session:
        session.add(
            Membership(
                user_id=bad_user,
                tenant_id=bad_tenant,
                role="member",
                source="manual",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_unique_tenant_slug_on_stores(sessionmaker):
    async with sessionmaker() as session:
        tenant = Tenant(slug="t1", display_name="T1")
        session.add(tenant)
        await session.flush()
        session.add(Store(tenant_id=tenant.id, slug="docs", display_name="Docs"))
        await session.commit()

    async with sessionmaker() as session:
        tenant_id = (
            await session.execute(select(Tenant.id).where(Tenant.slug == "t1"))
        ).scalar_one()
        session.add(
            Store(tenant_id=tenant_id, slug="docs", display_name="Other Docs")
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_api_token_key_version_round_trips_as_smallint(sessionmaker):
    async with sessionmaker() as session:
        user = User(oidc_sub="oidc|kv", email="k@x", display_name="K")
        session.add(user)
        await session.flush()
        session.add(
            ApiToken(
                user_id=user.id,
                token_hash="kvhash",
                key_version=2,
                name="rotated",
                scopes="read",
            )
        )
        await session.commit()

    async with sessionmaker() as session:
        kv = (
            await session.execute(
                select(ApiToken.key_version).where(ApiToken.token_hash == "kvhash")
            )
        ).scalar_one()
        assert kv == 2
        assert isinstance(kv, int)


async def test_audit_events_system_actor_and_on_delete_set_null(sessionmaker):
    async with sessionmaker() as session:
        session.add(
            AuditEvent(
                actor_user_id=None,
                actor_kind="system",
                action="membership.synced",
            )
        )
        user = User(oidc_sub="oidc|audit", email="u@x", display_name="U")
        session.add(user)
        await session.flush()
        session.add(
            AuditEvent(
                actor_user_id=user.id,
                actor_kind="user",
                action="token.issued",
            )
        )
        await session.commit()
        user_id = user.id

    async with sessionmaker() as session:
        rows = (
            await session.execute(select(AuditEvent).order_by(AuditEvent.action))
        ).scalars().all()
        assert len(rows) == 2
        actions = {r.action for r in rows}
        assert actions == {"membership.synced", "token.issued"}

    async with sessionmaker() as session:
        target = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        await session.delete(target)
        await session.commit()

    async with sessionmaker() as session:
        remaining = (
            await session.execute(select(AuditEvent.actor_user_id))
        ).scalars().all()
        assert all(actor is None for actor in remaining)
