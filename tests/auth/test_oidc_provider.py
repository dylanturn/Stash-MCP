"""Tests for ``OIDCAuthProvider``."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from starlette.requests import Request

from stash_mcp.auth.oidc_provider import OIDCAuthProvider
from stash_mcp.auth.provider import AuthError
from stash_mcp.config import Config
from stash_mcp.db.models import AuditEvent, Membership, Tenant, User

from ._fake_idp import FakeIdP


def _request_with_bearer(token: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/whoami",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "query_string": b"",
        "raw_path": b"/api/whoami",
    }
    return Request(scope)


@pytest.fixture
def idp() -> FakeIdP:
    return FakeIdP()


@pytest.fixture(autouse=True)
def _oidc_config(monkeypatch: pytest.MonkeyPatch, idp: FakeIdP):
    monkeypatch.setattr(Config, "OIDC_DISCOVERY_URL", idp.discovery_url, raising=False)
    monkeypatch.setattr(Config, "OIDC_CLIENT_ID", idp.audience, raising=False)
    monkeypatch.setattr(Config, "OIDC_AUDIENCE", idp.audience, raising=False)
    monkeypatch.setattr(Config, "OIDC_ADMIN_GROUP", "stash-admins", raising=False)
    monkeypatch.setattr(Config, "OIDC_GROUPS_CLAIM", "groups", raising=False)
    yield


@pytest.fixture
async def provider(idp: FakeIdP):
    p = OIDCAuthProvider(http_client=idp.build_http_client())
    try:
        yield p
    finally:
        await p.aclose()


async def test_valid_jwt_returns_principal(auth_db, idp, provider):
    token = idp.sign(sub="alice-sub", email="alice@x.test", name="Alice", groups=[])
    principal = await provider.authenticate(_request_with_bearer(token))
    assert principal is not None
    assert principal.auth_method == "oidc"
    assert principal.oidc_sub == "alice-sub"
    assert principal.email == "alice@x.test"
    assert principal.display_name == "Alice"
    assert principal.tenant_roles == {}


async def test_admin_group_creates_default_tenant_membership(auth_db, idp, provider):
    token = idp.sign(groups=["stash-admins"])
    principal = await provider.authenticate(_request_with_bearer(token))
    assert principal is not None

    async with auth_db() as s:
        tenant = (
            await s.execute(select(Tenant).where(Tenant.slug == "default"))
        ).scalar_one()
        m = (
            await s.execute(
                select(Membership).where(
                    Membership.user_id == principal.user_id,
                    Membership.tenant_id == tenant.id,
                )
            )
        ).scalar_one()
        assert m.role == "admin"
        assert m.source == "oidc_group"
        assert principal.tenant_roles == {tenant.id: "admin"}


async def test_tampered_signature_rejected(auth_db, idp, provider):
    token = idp.sign(groups=[])
    head, payload, sig = token.split(".")
    # Flip a byte in the signature.
    tampered = f"{head}.{payload}.{sig[:-2]}AA"
    with pytest.raises(AuthError):
        await provider.authenticate(_request_with_bearer(tampered))


async def test_expired_token_rejected(auth_db, idp, provider):
    token = idp.sign(groups=[], exp_offset=-30)
    with pytest.raises(AuthError):
        await provider.authenticate(_request_with_bearer(token))


async def test_wrong_audience_rejected(auth_db, idp, provider):
    token = idp.sign(groups=[], aud="some-other-app")
    with pytest.raises(AuthError, match="audience"):
        await provider.authenticate(_request_with_bearer(token))


async def test_wrong_issuer_rejected(auth_db, idp, provider):
    token = idp.sign(groups=[], iss="http://evil.local")
    with pytest.raises(AuthError, match="issuer"):
        await provider.authenticate(_request_with_bearer(token))


async def test_unknown_kid_triggers_refresh(auth_db, idp, provider):
    """First sign with the initial kid → succeeds. Rotate IdP keys, sign with
    a new kid → provider's cache is stale, so the second auth must refresh
    JWKS and succeed."""
    token1 = idp.sign(groups=[])
    await provider.authenticate(_request_with_bearer(token1))

    idp.add_key("new-kid-2")
    idp.kid = "new-kid-2"
    token2 = idp.sign(groups=[], sub="bob-sub", email="bob@x.test", name="Bob")
    principal = await provider.authenticate(_request_with_bearer(token2))
    assert principal is not None
    assert principal.oidc_sub == "bob-sub"


async def test_non_stash_bearer_returned_as_jwt(auth_db, idp, provider):
    """The provider treats any non-``stash_pat_`` bearer as a JWT and tries
    to decode. A malformed value is actively rejected (not None)."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/whoami",
        "headers": [(b"authorization", b"Bearer not-a-jwt")],
        "query_string": b"",
        "raw_path": b"/api/whoami",
    }
    with pytest.raises(AuthError):
        await provider.authenticate(Request(scope))


async def test_manual_membership_is_sticky(auth_db, idp, provider):
    """User has source='manual', role='member' on default tenant AND is in
    the admin group. After login: row is unchanged, no oidc_group row is
    created for the same tenant."""
    # Seed manual membership on the default tenant.
    async with auth_db() as s:
        tenant = Tenant(slug="default", display_name="Default tenant")
        user = User(oidc_sub="alice-sub", email="alice@x.test", display_name="Alice")
        s.add_all([tenant, user])
        await s.flush()
        s.add(
            Membership(
                user_id=user.id,
                tenant_id=tenant.id,
                role="member",
                source="manual",
            )
        )
        await s.commit()
        user_id = user.id
        tenant_id = tenant.id

    token = idp.sign(sub="alice-sub", groups=["stash-admins"])
    principal = await provider.authenticate(_request_with_bearer(token))
    assert principal is not None

    async with auth_db() as s:
        rows = (
            await s.execute(
                select(Membership).where(Membership.user_id == user_id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].tenant_id == tenant_id
        assert rows[0].source == "manual"
        assert rows[0].role == "member"
    assert principal.tenant_roles == {tenant_id: "member"}


async def test_group_removal_deletes_oidc_group_row(auth_db, idp, provider):
    # First login: in admin group → row created.
    t1 = idp.sign(sub="alice-sub", groups=["stash-admins"])
    await provider.authenticate(_request_with_bearer(t1))

    # Second login: no admin group → row removed. Fresh jti (default) bypasses
    # the principal cache.
    t2 = idp.sign(sub="alice-sub", groups=[])
    principal = await provider.authenticate(_request_with_bearer(t2))
    assert principal is not None
    assert principal.tenant_roles == {}

    async with auth_db() as s:
        rows = (
            await s.execute(
                select(Membership).where(Membership.user_id == principal.user_id)
            )
        ).scalars().all()
        assert rows == []


async def test_audit_events_on_membership_sync(auth_db, idp, provider):
    """Group-derived role added → one audit row. Removed → another row."""

    t1 = idp.sign(sub="alice-sub", groups=["stash-admins"])
    await provider.authenticate(_request_with_bearer(t1))

    t2 = idp.sign(sub="alice-sub", groups=[])
    await provider.authenticate(_request_with_bearer(t2))

    async with auth_db() as s:
        rows = (
            await s.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "membership.synced")
                .order_by(AuditEvent.occurred_at)
            )
        ).scalars().all()
        assert len(rows) == 2
        d0 = json.loads(rows[0].detail)
        d1 = json.loads(rows[1].detail)
        assert d0 == {"old_role": None, "new_role": "admin"}
        assert d1 == {"old_role": "admin", "new_role": None}
        assert all(r.actor_kind == "system" for r in rows)


async def test_jwt_cache_skips_db(auth_db, idp, provider):
    """Two consecutive auths with the same JWT do exactly one user upsert.

    Use a non-admin login (no membership writes) so the only thing the second
    call could touch is the User row's last_login_at — and the cache should
    skip that too."""
    token = idp.sign(sub="alice-sub", groups=[])
    p1 = await provider.authenticate(_request_with_bearer(token))
    async with auth_db() as s:
        user_before = (
            await s.execute(select(User).where(User.oidc_sub == "alice-sub"))
        ).scalar_one()
        first_login = user_before.last_login_at

    p2 = await provider.authenticate(_request_with_bearer(token))
    assert p1.user_id == p2.user_id

    async with auth_db() as s:
        user_after = (
            await s.execute(select(User).where(User.oidc_sub == "alice-sub"))
        ).scalar_one()
        assert user_after.last_login_at == first_login  # not updated -> cache hit


async def test_jwt_cache_bypassed_for_new_iat(auth_db, idp, provider):
    """Re-issued JWT (different iat) bypasses the cache and re-hits the DB."""

    t1 = idp.sign(sub="alice-sub", groups=[])
    await provider.authenticate(_request_with_bearer(t1))

    t2 = idp.sign(sub="alice-sub", groups=[])
    await provider.authenticate(_request_with_bearer(t2))

    async with auth_db() as s:
        users = (
            await s.execute(select(User).where(User.oidc_sub == "alice-sub"))
        ).scalars().all()
        assert len(users) == 1  # still one user, just re-touched
        assert users[0].last_login_at is not None
