"""FastAPI dependency: ``require_admin``.

In v1 admin is global — granted on the default tenant only — so the
check is "principal has admin role on whatever tenant has slug
``default``". Cross-tenant admins land in a follow-up spec.
"""

from __future__ import annotations

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
        # Without a default tenant we can't authorise anyone as admin —
        # surface that as a 404 on the tenant so operators see the
        # underlying cause rather than a misleading 403.
        raise TenantNotFound(
            f"default tenant ({_DEFAULT_TENANT_SLUG!r}) is missing"
        )

    if not principal.has_role_on(tenant.id, "admin"):
        raise Forbidden("admin role required on the default tenant")
    return principal


__all__ = ["require_admin"]
