"""Shared helper for upserting users + memberships from OIDC claims.

Both the bearer-JWT path (``OIDCAuthProvider._materialize_principal``) and
the cookie-issuance path (``/auth/callback`` in :mod:`stash_mcp.auth.routes`)
need to materialise a DB user from an OIDC claim set and refresh group-
derived memberships with the "manual wins" precedence locked in the auth
README.

The bearer path historically inlined this; spec 05 factors it out so the
callback can produce the same user_id+memberships state without
duplicating the upsert logic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Config
from ..db.models import AuditEvent, Membership, Tenant, User

_DEFAULT_TENANT_SLUG = "default"
_DEFAULT_TENANT_DISPLAY_NAME = "Default tenant"


def _first_str(d: dict, keys: list[str]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


async def ensure_default_tenant(session: AsyncSession) -> Tenant:
    """Return the default tenant row, creating it if missing."""
    tenant = (
        await session.execute(
            select(Tenant).where(Tenant.slug == _DEFAULT_TENANT_SLUG)
        )
    ).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            slug=_DEFAULT_TENANT_SLUG,
            display_name=_DEFAULT_TENANT_DISPLAY_NAME,
        )
        session.add(tenant)
        await session.flush()
    return tenant


def _audit_membership_change(
    session: AsyncSession,
    user: User,
    tenant_id: UUID,
    *,
    old_role: str | None,
    new_role: str | None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=user.id,
            actor_kind="system",
            action="membership.synced",
            target_kind="membership",
            target_id=str(user.id),
            tenant_id=tenant_id,
            detail=json.dumps({"old_role": old_role, "new_role": new_role}),
        )
    )


async def _sync_admin_membership(
    session: AsyncSession, user: User, groups: set[str]
) -> None:
    """Maintain a group-derived admin membership on the default tenant.

    Mirrors :meth:`OIDCAuthProvider._sync_admin_membership` exactly — see
    its docstring for the rules. Kept here so the callback route shares
    the same code path.
    """
    admin_group = Config.OIDC_ADMIN_GROUP
    if not admin_group:
        return

    existing = (
        (
            await session.execute(
                select(Membership).where(Membership.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    by_tenant: dict[Any, Membership] = {m.tenant_id: m for m in existing}

    default_tenant = await ensure_default_tenant(session)
    existing_on_default = by_tenant.get(default_tenant.id)
    manual_on_default = (
        existing_on_default is not None
        and existing_on_default.source == "manual"
    )

    admin_wanted = admin_group in groups
    if admin_wanted and not manual_on_default:
        if existing_on_default is None:
            session.add(
                Membership(
                    user_id=user.id,
                    tenant_id=default_tenant.id,
                    role="admin",
                    source="oidc_group",
                )
            )
            _audit_membership_change(
                session, user, default_tenant.id, old_role=None, new_role="admin"
            )
        else:
            if existing_on_default.role != "admin":
                _audit_membership_change(
                    session,
                    user,
                    default_tenant.id,
                    old_role=existing_on_default.role,
                    new_role="admin",
                )
                existing_on_default.role = "admin"

    for tenant_id, m in by_tenant.items():
        if m.source != "oidc_group":
            continue
        if (
            tenant_id == default_tenant.id
            and admin_wanted
            and not manual_on_default
        ):
            continue
        _audit_membership_change(
            session, user, tenant_id, old_role=m.role, new_role=None
        )
        await session.delete(m)


async def upsert_user_and_memberships(
    session: AsyncSession, claims: dict
) -> User:
    """Upsert the ``users`` row and refresh group-derived memberships.

    Commits are the caller's responsibility — both callers
    (:class:`OIDCAuthProvider` and the ``/auth/callback`` handler) want to
    commit alongside other state (e.g. a session-cookie issuance audit
    event).
    """
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise ValueError("OIDC claims missing 'sub'")
    email = _first_str(claims, ["email"]) or ""
    display_name = (
        _first_str(claims, ["name", "preferred_username", "email"]) or sub
    )

    groups_raw = claims.get(Config.OIDC_GROUPS_CLAIM, [])
    if not isinstance(groups_raw, list):
        groups_raw = []
    groups: set[str] = {g for g in groups_raw if isinstance(g, str)}

    user = (
        await session.execute(select(User).where(User.oidc_sub == sub))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        user = User(
            oidc_sub=sub,
            email=email,
            display_name=display_name,
            last_login_at=now,
        )
        session.add(user)
        await session.flush()
    else:
        if email and user.email != email:
            user.email = email
        if display_name and user.display_name != display_name:
            user.display_name = display_name
        user.last_login_at = now

    await _sync_admin_membership(session, user, groups)

    # Refresh so callers see the up-to-date memberships collection.
    await session.refresh(user, attribute_names=["memberships"])
    return user


__all__ = [
    "ensure_default_tenant",
    "upsert_user_and_memberships",
]
