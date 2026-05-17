"""Per-store routing — middleware + contextvars for the per-request
``LoadedStore``."""

from .context import (
    current_store,
    require_store,
    reset_current_store,
    set_current_store,
)
from .mcp_server_resolver import (
    McpServerResolverMiddleware,
    current_mcp_server,
    reset_current_mcp_server,
    set_current_mcp_server,
)
from .store_resolver import StoreResolverMiddleware

__all__ = [
    "McpServerResolverMiddleware",
    "StoreResolverMiddleware",
    "current_mcp_server",
    "current_store",
    "require_store",
    "reset_current_mcp_server",
    "reset_current_store",
    "set_current_mcp_server",
    "set_current_store",
]
