"""Per-tenant admin HTTP surface — ``/tenants/{tenant_id}/*``.

Mirrors the shape of the global-admin store endpoints but is gated by
:func:`require_tenant_admin` (admin role on the path's tenant) instead
of :func:`require_admin` (admin role on the default tenant).
"""

from fastapi import APIRouter

from .mcp_servers import router as mcp_servers_router
from .routes import router as stores_router

router = APIRouter()
router.include_router(stores_router)
router.include_router(mcp_servers_router)

__all__ = ["router"]
