"""``/admin/*`` HTTP handlers.

All endpoints gated by :func:`require_admin`. Audit events for state-
changing actions are written in the same DB transaction as the change so
the audit log can't drift from the table state.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.principal import Principal
from ..db.models import (
    ApiToken,
    AuditEvent,
    Membership,
    Store,
    Tenant,
    User,
)
from ..db.session import get_session
from ..errors import (
    ConfirmationRequired,
    MembershipExists,
    MembershipNotFound,
    TenantAlreadyExists,
    TenantHasStores,
    TenantNotFound,
    UserNotFound,
    ValidationError,
)
from ..stores import admin_ops
from ..stores.admin_ops import StoreCreate as StoreCreateBody
from .dependencies import require_admin

logger = logging.getLogger(__name__)


# --- request/response models -----------------------------------------------


class TenantCreate(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    display_name: str = Field(..., min_length=1, max_length=255)


class TenantUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)


class TenantInfo(BaseModel):
    id: UUID
    slug: str
    display_name: str
    created_at: datetime


class StoreInfo(BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    display_name: str
    git_remote_url: str | None
    git_branch: str
    created_at: datetime


class UserInfo(BaseModel):
    id: UUID
    oidc_sub: str
    email: str
    display_name: str
    created_at: datetime
    last_login_at: datetime | None


class MembershipCreate(BaseModel):
    user_id: UUID
    tenant_id: UUID
    role: str = Field(..., pattern=r"^(admin|member)$")


class MembershipInfo(BaseModel):
    id: UUID
    user_id: UUID
    tenant_id: UUID
    role: str
    source: str
    created_at: datetime


def _tenant_to_info(t: Tenant) -> TenantInfo:
    return TenantInfo(
        id=t.id,
        slug=t.slug,
        display_name=t.display_name,
        created_at=t.created_at,
    )


def _store_to_info(s: Store) -> StoreInfo:
    return StoreInfo(
        id=s.id,
        tenant_id=s.tenant_id,
        slug=s.slug,
        display_name=s.display_name,
        git_remote_url=s.git_remote_url,
        git_branch=s.git_branch,
        created_at=s.created_at,
    )


def _user_to_info(u: User) -> UserInfo:
    return UserInfo(
        id=u.id,
        oidc_sub=u.oidc_sub,
        email=u.email,
        display_name=u.display_name,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


def _membership_to_info(m: Membership) -> MembershipInfo:
    return MembershipInfo(
        id=m.id,
        user_id=m.user_id,
        tenant_id=m.tenant_id,
        role=m.role,
        source=m.source,
        created_at=m.created_at,
    )


def _audit(
    session: AsyncSession,
    *,
    actor: Principal,
    action: str,
    target_kind: str,
    target_id: str,
    tenant_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            actor_kind="user",
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            tenant_id=tenant_id,
            detail=json.dumps(detail) if detail else None,
        )
    )


async def _get_tenant_or_404(
    session: AsyncSession, tenant_id: UUID
) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant {tenant_id} not found")
    return tenant


# --- router -----------------------------------------------------------------


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# Tenants -------------------------------------------------------------------


@router.post("/tenants", response_model=TenantInfo, status_code=201)
async def create_tenant(
    body: TenantCreate,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TenantInfo:
    existing = (
        await session.execute(select(Tenant).where(Tenant.slug == body.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise TenantAlreadyExists(f"tenant slug {body.slug!r} already in use")
    tenant = Tenant(slug=body.slug, display_name=body.display_name)
    session.add(tenant)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise TenantAlreadyExists(
            f"tenant slug {body.slug!r} already in use"
        ) from exc
    _audit(
        session,
        actor=actor,
        action="tenant.created",
        target_kind="tenant",
        target_id=str(tenant.id),
        tenant_id=tenant.id,
        detail={"slug": tenant.slug, "display_name": tenant.display_name},
    )
    await session.commit()
    await session.refresh(tenant)
    return _tenant_to_info(tenant)


@router.get("/tenants", response_model=list[TenantInfo])
async def list_tenants(
    session: AsyncSession = Depends(get_session),
) -> list[TenantInfo]:
    rows = (
        (await session.execute(select(Tenant).order_by(Tenant.slug)))
        .scalars()
        .all()
    )
    return [_tenant_to_info(t) for t in rows]


@router.get("/tenants/{tenant_id}", response_model=TenantInfo)
async def get_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TenantInfo:
    return _tenant_to_info(await _get_tenant_or_404(session, tenant_id))


@router.patch("/tenants/{tenant_id}", response_model=TenantInfo)
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TenantInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)
    tenant.display_name = body.display_name
    _audit(
        session,
        actor=actor,
        action="tenant.renamed",
        target_kind="tenant",
        target_id=str(tenant.id),
        tenant_id=tenant.id,
        detail={"display_name": tenant.display_name},
    )
    await session.commit()
    await session.refresh(tenant)
    return _tenant_to_info(tenant)


@router.delete("/tenants/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: UUID,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    tenant = await _get_tenant_or_404(session, tenant_id)
    store_count = (
        await session.execute(
            select(func.count())
            .select_from(Store)
            .where(Store.tenant_id == tenant_id)
        )
    ).scalar_one()
    if store_count:
        raise TenantHasStores(
            f"tenant {tenant.slug!r} owns {store_count} store(s); "
            "delete the stores first"
        )
    _audit(
        session,
        actor=actor,
        action="tenant.deleted",
        target_kind="tenant",
        target_id=str(tenant.id),
        tenant_id=tenant.id,
        detail={"slug": tenant.slug},
    )
    await session.delete(tenant)
    await session.commit()


# Stores --------------------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/stores",
    response_model=StoreInfo,
    status_code=201,
)
async def create_store(
    tenant_id: UUID,
    body: StoreCreateBody,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> StoreInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)
    store = await admin_ops.provision_store(
        session, actor=actor, tenant=tenant, body=body
    )
    return _store_to_info(store)


@router.get(
    "/tenants/{tenant_id}/stores", response_model=list[StoreInfo]
)
async def list_stores(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[StoreInfo]:
    await _get_tenant_or_404(session, tenant_id)
    rows = (
        (
            await session.execute(
                select(Store)
                .where(Store.tenant_id == tenant_id)
                .order_by(Store.slug)
            )
        )
        .scalars()
        .all()
    )
    return [_store_to_info(s) for s in rows]


@router.delete(
    "/tenants/{tenant_id}/stores/{slug}", status_code=204
)
async def delete_store(
    tenant_id: UUID,
    slug: str,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    confirm: bool = Query(default=False),
) -> None:
    tenant = await _get_tenant_or_404(session, tenant_id)
    if not confirm:
        raise ConfirmationRequired(
            "store deletion removes the on-disk repo recursively — "
            "retry with ?confirm=true to proceed"
        )
    await admin_ops.deprovision_store(
        session, actor=actor, tenant=tenant, slug=slug
    )


# Users ---------------------------------------------------------------------


@router.get("/users", response_model=list[UserInfo])
async def list_users(
    session: AsyncSession = Depends(get_session),
) -> list[UserInfo]:
    rows = (
        (await session.execute(select(User).order_by(User.email)))
        .scalars()
        .all()
    )
    return [_user_to_info(u) for u in rows]


@router.get("/users/{user_id}", response_model=UserInfo)
async def get_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> UserInfo:
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFound(f"user {user_id} not found")
    return _user_to_info(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFound(f"user {user_id} not found")

    # Memberships cascade via FK; API tokens cascade too, but the spec
    # asks us to also write a revocation timestamp on still-live tokens
    # so any audit row tracing this user's tokens reads sanely.
    now = datetime.now(UTC)
    live_tokens = (
        (
            await session.execute(
                select(ApiToken).where(
                    ApiToken.user_id == user.id,
                    ApiToken.revoked_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for t in live_tokens:
        t.revoked_at = now

    _audit(
        session,
        actor=actor,
        action="user.deleted",
        target_kind="user",
        target_id=str(user.id),
        detail={"email": user.email, "oidc_sub": user.oidc_sub},
    )
    await session.delete(user)
    await session.commit()


# Memberships ---------------------------------------------------------------


@router.post(
    "/memberships", response_model=MembershipInfo, status_code=201
)
async def grant_membership(
    body: MembershipCreate,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> MembershipInfo:
    user = await session.get(User, body.user_id)
    if user is None:
        raise UserNotFound(f"user {body.user_id} not found")
    tenant = await session.get(Tenant, body.tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant {body.tenant_id} not found")

    existing = (
        await session.execute(
            select(Membership).where(
                Membership.user_id == body.user_id,
                Membership.tenant_id == body.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise MembershipExists(
            f"user {user.email} already has a membership on tenant {tenant.slug!r} "
            f"(source={existing.source!r}, role={existing.role!r})"
        )

    membership = Membership(
        user_id=body.user_id,
        tenant_id=body.tenant_id,
        role=body.role,
        source="manual",
    )
    session.add(membership)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ValidationError(f"failed to grant membership: {exc}") from exc

    _audit(
        session,
        actor=actor,
        action="membership.granted",
        target_kind="membership",
        target_id=str(membership.id),
        tenant_id=tenant.id,
        detail={
            "user_id": str(user.id),
            "user_email": user.email,
            "role": body.role,
            "source": "manual",
        },
    )
    await session.commit()
    await session.refresh(membership)
    return _membership_to_info(membership)


@router.delete("/memberships/{membership_id}", status_code=204)
async def revoke_membership(
    membership_id: UUID,
    actor: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    membership = await session.get(Membership, membership_id)
    if membership is None:
        raise MembershipNotFound(f"membership {membership_id} not found")
    if membership.source != "manual":
        raise ValidationError(
            "only source='manual' memberships can be revoked via this endpoint"
        )

    _audit(
        session,
        actor=actor,
        action="membership.revoked",
        target_kind="membership",
        target_id=str(membership.id),
        tenant_id=membership.tenant_id,
        detail={
            "user_id": str(membership.user_id),
            "role": membership.role,
            "source": membership.source,
        },
    )
    await session.delete(membership)
    await session.commit()


__all__ = ["router"]
