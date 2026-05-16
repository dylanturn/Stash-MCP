"""Tests for ``ApiTokenAuthProvider``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request

from stash_mcp.auth.api_token_provider import ApiTokenAuthProvider
from stash_mcp.auth.provider import AuthError
from stash_mcp.auth.tokens import generate_token, hash_token, hash_with_active_key
from stash_mcp.config import Config
from stash_mcp.db.models import ApiToken, Membership, Tenant, User


def _request_with_auth(value: str | None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if value is not None:
        headers.append((b"authorization", value.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/whoami",
        "headers": headers,
        "query_string": b"",
        "raw_path": b"/api/whoami",
    }
    return Request(scope)


async def _seed_user(sessionmaker, *, role: str = "member"):
    """Seed one tenant + user + membership and return them."""
    async with sessionmaker() as s:
        tenant = Tenant(slug="default", display_name="Default tenant")
        user = User(oidc_sub="alice-sub", email="alice@example.test", display_name="Alice")
        s.add_all([tenant, user])
        await s.flush()
        membership = Membership(
            user_id=user.id, tenant_id=tenant.id, role=role, source="manual"
        )
        s.add(membership)
        await s.commit()
        return tenant.id, user.id


async def _insert_token(
    sessionmaker,
    user_id: uuid.UUID,
    *,
    keys: list[str],
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> str:
    token = generate_token()
    digest, version = hash_with_active_key(token, keys=keys)
    async with sessionmaker() as s:
        s.add(
            ApiToken(
                user_id=user_id,
                token_hash=digest,
                key_version=version,
                name="ci",
                scopes="read:content,write:content",
                expires_at=expires_at,
                revoked_at=revoked_at,
            )
        )
        await s.commit()
    return token


async def test_returns_none_when_no_authorization_header(auth_db):
    p = await ApiTokenAuthProvider().authenticate(_request_with_auth(None))
    assert p is None


async def test_returns_none_for_non_stash_bearer(auth_db):
    jwt_shape = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.sig"
    p = await ApiTokenAuthProvider().authenticate(
        _request_with_auth(f"Bearer {jwt_shape}")
    )
    assert p is None


async def test_valid_token_returns_principal(auth_db):
    tenant_id, user_id = await _seed_user(auth_db, role="member")
    token = await _insert_token(auth_db, user_id, keys=Config.AUTH_TOKEN_HMAC_KEYS)

    principal = await ApiTokenAuthProvider().authenticate(
        _request_with_auth(f"Bearer {token}")
    )
    assert principal is not None
    assert principal.auth_method == "api_token"
    assert principal.user_id == user_id
    assert principal.tenant_roles == {tenant_id: "member"}
    assert principal.claims["token_name"] == "ci"
    assert principal.claims["scopes"] == "read:content,write:content"


async def test_revoked_token_raises_auth_error(auth_db):
    _, user_id = await _seed_user(auth_db)
    token = await _insert_token(
        auth_db,
        user_id,
        keys=Config.AUTH_TOKEN_HMAC_KEYS,
        revoked_at=datetime.now(UTC),
    )
    with pytest.raises(AuthError, match="revoked"):
        await ApiTokenAuthProvider().authenticate(_request_with_auth(f"Bearer {token}"))


async def test_expired_token_raises_auth_error(auth_db):
    _, user_id = await _seed_user(auth_db)
    token = await _insert_token(
        auth_db,
        user_id,
        keys=Config.AUTH_TOKEN_HMAC_KEYS,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(AuthError, match="expired"):
        await ApiTokenAuthProvider().authenticate(_request_with_auth(f"Bearer {token}"))


async def test_unknown_token_raises_auth_error(auth_db):
    # No row in DB → token "shape" matches but lookup misses.
    token = generate_token()
    with pytest.raises(AuthError, match="invalid api token"):
        await ApiTokenAuthProvider().authenticate(_request_with_auth(f"Bearer {token}"))


async def test_rotated_in_token_verifies_under_old_key(
    auth_db, monkeypatch: pytest.MonkeyPatch
):
    """Token issued under [K1]; operator rotates to [K2, K1]. The row's
    key_version was 0 at issue but is now slot 1 in the new list. The
    provider must locate it via the new index."""
    _, user_id = await _seed_user(auth_db)

    # Issue under K1 directly so we can place the row at key_version=1 to
    # mirror the post-rotation state. (hash_with_active_key uses keys[0].)
    token = generate_token()
    digest = hash_token(token, key="K1")
    async with auth_db() as s:
        s.add(
            ApiToken(
                user_id=user_id,
                token_hash=digest,
                key_version=1,
                name="ci",
                scopes="read:content",
            )
        )
        await s.commit()

    monkeypatch.setattr(Config, "AUTH_TOKEN_HMAC_KEYS", ["K2", "K1"], raising=False)
    principal = await ApiTokenAuthProvider().authenticate(
        _request_with_auth(f"Bearer {token}")
    )
    assert principal is not None
    assert principal.claims["key_version"] == 1


async def test_rotated_out_key_rejects(auth_db, monkeypatch: pytest.MonkeyPatch):
    """Row recorded key_version=0 under old [K1]; operator replaced the list
    with [K2] without keeping K1. The provider must refuse."""
    _, user_id = await _seed_user(auth_db)
    token = generate_token()
    digest = hash_token(token, key="K1")
    async with auth_db() as s:
        s.add(
            ApiToken(
                user_id=user_id,
                token_hash=digest,
                key_version=0,
                name="ci",
                scopes="read:content",
            )
        )
        await s.commit()

    monkeypatch.setattr(Config, "AUTH_TOKEN_HMAC_KEYS", ["K2"], raising=False)
    with pytest.raises(AuthError):
        await ApiTokenAuthProvider().authenticate(_request_with_auth(f"Bearer {token}"))


async def test_last_used_at_is_bumped(auth_db):
    _, user_id = await _seed_user(auth_db)
    token = await _insert_token(auth_db, user_id, keys=Config.AUTH_TOKEN_HMAC_KEYS)
    before = datetime.now(UTC)

    await ApiTokenAuthProvider().authenticate(_request_with_auth(f"Bearer {token}"))

    async with auth_db() as s:
        from sqlalchemy import select

        row = (await s.execute(select(ApiToken))).scalar_one()
        assert row.last_used_at is not None
        last_used = row.last_used_at
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=UTC)
        assert last_used >= before
