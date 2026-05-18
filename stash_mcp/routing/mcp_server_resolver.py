"""``McpServerResolverMiddleware`` — resolves a scoped token's MCP
server config and binds a composite store for the request.

Runs after :class:`StashAuthMiddleware` and before
:class:`StoreResolverMiddleware`. Only affects ``/mcp/*`` and ``/api/*``
requests. If the in-flight principal carries an ``mcp_server_id`` claim
(populated by :class:`ApiTokenAuthProvider`), the middleware:

1. Loads the config + tools + mounts from the DB.
2. Builds a :class:`CompositeFileSystem` and wraps it in a
   :class:`CompositeLoadedStore`.
3. Sets ``current_store`` (so the downstream
   :class:`StoreResolverMiddleware` short-circuits) and
   ``current_mcp_server``.

If the claim is absent — or :data:`Config.MCP_CONFIGS_ENABLED` is False
— the middleware no-ops and the request flows through the legacy
URL-based resolver.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.types import ASGIApp, Receive, Scope, Send

from ..auth.context import current_principal
from ..config import Config
from ..db.models import (
    McpServer,
    Store,
    Tenant,
)
from ..db.session import get_sessionmaker
from ..errors import (
    McpServerConfigDisabled,
    McpServerNotFound,
    StashError,
    problem_response,
)
from ..stores.composite_filesystem import (
    CompositeFileSystem,
    CompositeMount,
)
from ..stores.composite_store import CompositeLoadedStore
from ..stores.registry import StoreRegistry, get_store_registry
from .context import reset_current_store, set_current_store

logger = logging.getLogger(__name__)


_current_mcp_server: ContextVar[McpServer | None] = ContextVar(
    "stash_current_mcp_server", default=None
)


def set_current_mcp_server(server: McpServer | None) -> Token:
    return _current_mcp_server.set(server)


def reset_current_mcp_server(token: Token) -> None:
    _current_mcp_server.reset(token)


def current_mcp_server() -> McpServer | None:
    """Return the resolved MCP-server config for the in-flight
    request, or ``None`` if the request is unscoped or
    :data:`Config.MCP_CONFIGS_ENABLED` is False."""
    return _current_mcp_server.get()


async def _build_composite(
    config: McpServer, registry: StoreRegistry
) -> CompositeLoadedStore:
    """Walk a config's mounts and assemble the composite store.

    For single-store composites, the composite's ``git_backend`` and
    ``transaction_manager`` are forwarded from the underlying store's
    ``LoadedStore`` so git and transaction tools Just Work.
    """
    # Collect distinct underlying store IDs and resolve them via the
    # registry (which caches LoadedStores per process). Also pick up
    # the config's own tenant_slug in the same session so the composite
    # can be constructed fully-initialised.
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        store_rows = (
            (
                await session.execute(
                    select(Store, Tenant)
                    .join(Tenant, Tenant.id == Store.tenant_id)
                    .where(
                        Store.id.in_(
                            {m.store_id for m in config.mounts} or {None}
                        )
                    )
                )
            )
            .all()
        )
        config_tenant = await session.get(Tenant, config.tenant_id)
    by_id = {s.id: (s, t) for s, t in store_rows}
    loaded_stores = {}
    for store_id, (store, tenant) in by_id.items():
        loaded_stores[store_id] = await registry.get(tenant.slug, store.slug)

    is_single = len({m.store_id for m in config.mounts}) == 1

    # Build mounts in the order they appear (sort_order is already
    # applied by the relationship `order_by`).
    mounts: list[CompositeMount] = []
    for m in config.mounts:
        loaded = loaded_stores[m.store_id]
        # For single-store configs we want the transaction-wrapped FS so
        # write tools go through the transaction layer.
        fs = loaded.fs_for_mcp if is_single else loaded.filesystem
        mounts.append(
            CompositeMount(
                fs=fs,
                subpath=m.subpath,
                virtual_prefix=m.virtual_prefix,
            )
        )

    # If the config has zero mounts the composite has nothing to mount
    # — refuse with a clear error so the tool handler doesn't later get
    # a misleading "path not in any mount" message.
    if not mounts:
        raise McpServerConfigDisabled(
            f"mcp-server {config.slug!r} has no mounts configured"
        )

    composite_fs = CompositeFileSystem(mounts)

    git_backend = None
    transaction_manager = None
    if is_single:
        sole = next(iter(loaded_stores.values()))
        git_backend = sole.git_backend
        transaction_manager = sole.transaction_manager

    underlying = frozenset(loaded_stores.keys())
    return CompositeLoadedStore(
        tenant_id=config.tenant_id,
        tenant_slug=config_tenant.slug if config_tenant else "",
        store_id=config.id,
        store_slug=config.slug,
        filesystem=composite_fs,
        git_backend=git_backend,
        transaction_manager=transaction_manager,
        underlying_store_ids=underlying,
        mcp_server_id=config.id,
        display_name=config.name,
    )


class McpServerResolverMiddleware:
    """ASGI middleware: load the MCP-server config from the principal
    and bind a composite store to the request's contextvars."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        registry: StoreRegistry | None = None,
        prefixes: tuple[str, ...] = ("/mcp", "/api"),
    ) -> None:
        self.app = app
        self._registry = registry
        self.prefixes = prefixes

    @property
    def registry(self) -> StoreRegistry:
        return self._registry or get_store_registry()

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if (
            scope["type"] != "http"
            or not Config.AUTH_ENABLED
            or not Config.MCP_CONFIGS_ENABLED
        ):
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if not any(path == p or path.startswith(p) for p in self.prefixes):
            await self.app(scope, receive, send)
            return

        principal = current_principal()
        mcp_server_id = (
            principal.claims.get("mcp_server_id") if principal else None
        )
        if not mcp_server_id:
            await self.app(scope, receive, send)
            return

        try:
            config = await self._load_config(mcp_server_id)
            if config is None:
                raise McpServerNotFound(
                    f"mcp-server {mcp_server_id} not found"
                )
            if not config.enabled:
                raise McpServerConfigDisabled(
                    f"mcp-server {config.slug!r} is disabled"
                )
        except StashError as exc:
            # Middleware sits outside the FastAPI exception handler, so
            # render Problem Details ourselves.
            response = problem_response(request=None, err=exc)
            await response(scope, receive, send)
            return

        try:
            composite = await _build_composite(config, self.registry)
        except StashError as exc:
            response = problem_response(request=None, err=exc)
            await response(scope, receive, send)
            return

        cfg_token = set_current_mcp_server(config)
        store_token = set_current_store(composite)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_store(store_token)
            reset_current_mcp_server(cfg_token)

    async def _load_config(self, server_id_str: str) -> McpServer | None:
        import uuid

        try:
            server_uuid = uuid.UUID(str(server_id_str))
        except (TypeError, ValueError):
            return None
        async with get_sessionmaker()() as session:
            return (
                await session.execute(
                    select(McpServer)
                    .options(
                        selectinload(McpServer.tools),
                        selectinload(McpServer.mounts),
                    )
                    .where(McpServer.id == server_uuid)
                )
            ).scalar_one_or_none()


__all__ = [
    "McpServerResolverMiddleware",
    "current_mcp_server",
    "set_current_mcp_server",
    "reset_current_mcp_server",
]
