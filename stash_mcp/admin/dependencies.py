"""FastAPI dependencies for admin surfaces.

Two dependencies live here:

- :func:`require_admin` gates the global-admin surface (``/admin/*``).
  Checks for ``admin`` role on the default tenant.
- :func:`require_tenant_admin` gates the per-tenant admin surface
  (``/tenants/{tenant_id}/*``). Checks for ``admin`` role on the
  specific tenant named in the URL.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from ..auth.context import current_principal
from ..auth.principal import Principal
from ..db.models import Tenant
from ..db.session import get_session
from ..errors import Forbidden, TenantNotFound, Unauthenticated

_DEFAULT_TENANT_SLUG = "default"


async def require_tenant_admin(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Reject the request unless the caller is admin on *this* tenant.

    FastAPI binds ``tenant_id`` from the path the same way the existing
    tenant-store handlers do; we look up the tenant and check the
    principal's role on it.
    """
    principal = current_principal()
    if principal is None:
        raise Unauthenticated("tenant-admin endpoints require authentication")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant {tenant_id} not found")
    if not principal.has_role_on(tenant.id, "admin"):
        raise Forbidden("admin role required on this tenant")
    return principal


async def require_admin(
    request: Request,  # noqa: ARG001 — kept for signature symmetry
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Reject the request unless the caller is an admin on ``default``."""
    principal = current_principal()
    if principal is None:
        raise Unauthenticated("admin endpoints require authentication")

    tenant = (
        await session.execute(
            select(Tenant).where(Tenant.slug == _DEFAULT_TENANT_SLUG)
        )
    ).scalar_one_or_none()
    if tenant is None:
        raise TenantNotFound(
            f"default tenant ({_DEFAULT_TENANT_SLUG!r}) is missing"
        )

    if not principal.has_role_on(tenant.id, "admin"):
        raise Forbidden("admin role required on the default tenant")
    return principal


__all__ = ["require_admin", "require_tenant_admin"]
