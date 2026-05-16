"""End-to-end tests for ``/auth/tokens``."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from stash_mcp.auth.principal import Principal
from stash_mcp.auth.tokens import hash_token
from stash_mcp.db.models import ApiToken, AuditEvent, User

from .conftest import _principal, make_client


async def _make_session_user(
    auth_db: async_sessionmaker, *, email: str = "alice@x"
) -> User:
    async with auth_db() as session:
        user = User(oidc_sub=email, email=email, display_name=email)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def session_principal(auth_db: async_sessionmaker):
    user = await _make_session_user(auth_db)
    return _principal(
        tenant_roles={},
        auth_method="session",
        user_id=user.id,
    )


async def test_unauthenticated_blocked(auth_db, content_dir: Path):
    client = make_client(None)
    resp = client.get("/auth/tokens")
    assert resp.status_code == 401


async def test_token_callers_cannot_mint(
    auth_db, content_dir: Path
):
    user = await _make_session_user(auth_db, email="token-caller@x")
    p = Principal(
        user_id=user.id,
        oidc_sub="token-caller@x",
        email="token-caller@x",
        display_name="t",
        auth_method="api_token",
        tenant_roles={},
        claims={"scopes": "read,write"},
    )
    client = make_client(p)
    resp = client.post("/auth/tokens", json={"name": "x"})
    assert resp.status_code == 403
    assert resp.json()["type"] == "/problems/auth/forbidden"


async def test_jwt_callers_cannot_mint(auth_db, content_dir: Path):
    user = await _make_session_user(auth_db, email="jwt@x")
    p = Principal(
        user_id=user.id,
        oidc_sub="jwt@x",
        email="jwt@x",
        display_name="j",
        auth_method="oidc",
        tenant_roles={},
    )
    client = make_client(p)
    resp = client.post("/auth/tokens", json={"name": "x"})
    assert resp.status_code == 403


async def test_session_caller_mints_token(
    auth_db, content_dir: Path, session_principal
):
    client = make_client(session_principal)
    resp = client.post(
        "/auth/tokens",
        json={"name": "ci", "scopes": ["read", "write"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "ci"
    assert body["scopes"] == ["read", "write"]
    assert body["token"].startswith("stash_pat_")
    plaintext = body["token"]

    # The token row exists with the correct hash.
    async with auth_db() as session:
        rows = (
            (await session.execute(select(ApiToken)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].name == "ci"
    assert rows[0].token_hash == hash_token(plaintext, key="test-key-0")
    assert rows[0].key_version == 0

    # Audit row.
    async with auth_db() as session:
        events = (
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
    assert len(events) == 1


async def test_list_excludes_secret(
    auth_db, content_dir: Path, session_principal
):
    client = make_client(session_principal)
    client.post("/auth/tokens", json={"name": "t1"})
    resp = client.get("/auth/tokens")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert "token" not in body[0]
    assert body[0]["name"] == "t1"


async def test_invalid_scope_rejected(
    auth_db, content_dir: Path, session_principal
):
    client = make_client(session_principal)
    resp = client.post(
        "/auth/tokens",
        json={"name": "t", "scopes": ["read", "exfiltrate"]},
    )
    assert resp.status_code == 400
    assert resp.json()["type"] == "/problems/validation"


async def test_revoke_token(
    auth_db, content_dir: Path, session_principal
):
    client = make_client(session_principal)
    created = client.post("/auth/tokens", json={"name": "t1"}).json()
    revoke = client.delete(f"/auth/tokens/{created['id']}")
    assert revoke.status_code == 204
    # Listing without include_revoked excludes it.
    listed = client.get("/auth/tokens").json()
    assert listed == []
    # With include_revoked it reappears with a revoked_at.
    listed = client.get("/auth/tokens?include_revoked=true").json()
    assert len(listed) == 1
    assert listed[0]["revoked_at"] is not None

    async with auth_db() as session:
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action.in_(("token.issued", "token.revoked"))
                    )
                )
            )
            .scalars()
            .all()
        )
    actions = {e.action for e in events}
    assert actions == {"token.issued", "token.revoked"}


async def test_revoke_unknown_token_404(
    auth_db, content_dir: Path, session_principal
):
    client = make_client(session_principal)
    resp = client.delete(f"/auth/tokens/{uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["type"] == "/problems/token/not-found"


async def test_revoke_other_users_token_404(
    auth_db, content_dir: Path, session_principal
):
    # A second user mints a token. The first user must not be able to
    # revoke it — the lookup is scoped by user_id so they see a 404.
    other = await _make_session_user(auth_db, email="bob@x")
    async with auth_db() as session:
        row = ApiToken(
            user_id=other.id,
            token_hash="h",
            key_version=0,
            name="t",
            scopes="read",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        target_id = row.id

    client = make_client(session_principal)
    resp = client.delete(f"/auth/tokens/{target_id}")
    assert resp.status_code == 404


async def test_revoke_idempotent(
    auth_db, content_dir: Path, session_principal
):
    client = make_client(session_principal)
    created = client.post("/auth/tokens", json={"name": "t1"}).json()
    first = client.delete(f"/auth/tokens/{created['id']}")
    second = client.delete(f"/auth/tokens/{created['id']}")
    assert first.status_code == 204
    assert second.status_code == 204
    # Only one audit row.
    async with auth_db() as session:
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action == "token.revoked"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1
