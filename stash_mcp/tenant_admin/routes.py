"""``/tenants/{tenant_id}/stores/*`` HTTP handlers.

Tenant-scoped CRUD for stores. Gated by
:func:`require_tenant_admin` so a tenant admin can manage their own
stores without escalating to global-admin.

All bodies delegate to :mod:`stash_mcp.stores.admin_ops` so the
implementation can't drift from the global-admin surface.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ..admin.dependencies import require_tenant_admin
from ..auth.principal import Principal
from ..db.models import Store, Tenant
from ..db.session import get_session
from ..errors import (
    ConfirmationRequired,
    StoreNotFound,
    TenantNotFound,
)
from ..stores import admin_ops
from ..stores.admin_ops import StoreCreate, StoreUpdate


class StoreInfo(BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    display_name: str
    git_remote_url: str | None
    git_branch: str
    created_at: datetime


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


async def _get_tenant_or_404(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant {tenant_id} not found")
    return tenant


async def _get_store_or_404(
    session: AsyncSession, tenant: Tenant, slug: str
) -> Store:
    store = (
        await session.execute(
            select(Store).where(
                Store.tenant_id == tenant.id, Store.slug == slug
            )
        )
    ).scalar_one_or_none()
    if store is None:
        raise StoreNotFound(f"store {tenant.slug}/{slug} not found")
    return store


router = APIRouter(prefix="/tenants", tags=["tenant-admin"])


@router.get(
    "/{tenant_id}/stores",
    response_model=list[StoreInfo],
)
async def list_stores(
    tenant_id: UUID,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> list[StoreInfo]:
    tenant = await _get_tenant_or_404(session, tenant_id)
    rows = (
        (
            await session.execute(
                select(Store)
                .where(Store.tenant_id == tenant.id)
                .order_by(Store.slug)
            )
        )
        .scalars()
        .all()
    )
    return [_store_to_info(s) for s in rows]


@router.post(
    "/{tenant_id}/stores",
    response_model=StoreInfo,
    status_code=201,
)
async def create_store(
    tenant_id: UUID,
    body: StoreCreate,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> StoreInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)
    store = await admin_ops.provision_store(
        session, actor=actor, tenant=tenant, body=body
    )
    return _store_to_info(store)


@router.get(
    "/{tenant_id}/stores/{slug}",
    response_model=StoreInfo,
)
async def get_store(
    tenant_id: UUID,
    slug: str,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> StoreInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)
    store = await _get_store_or_404(session, tenant, slug)
    return _store_to_info(store)


@router.patch(
    "/{tenant_id}/stores/{slug}",
    response_model=StoreInfo,
)
async def update_store(
    tenant_id: UUID,
    slug: str,
    body: StoreUpdate,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> StoreInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)
    store = await _get_store_or_404(session, tenant, slug)
    updated = await admin_ops.rename_store(
        session, actor=actor, tenant=tenant, store=store, body=body
    )
    return _store_to_info(updated)


@router.delete(
    "/{tenant_id}/stores/{slug}",
    status_code=204,
)
async def delete_store(
    tenant_id: UUID,
    slug: str,
    actor: Principal = Depends(require_tenant_admin),
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


__all__ = ["router", "StoreInfo"]
