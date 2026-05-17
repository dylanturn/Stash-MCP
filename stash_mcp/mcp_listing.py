"""FastMCP middleware that filters ``tools/list`` and augments
``resources/list`` in auth mode based on the in-flight MCP-server
config and composite store.

The call-time check (``_enforce_mcp_server_allowlist`` in
:mod:`stash_mcp.mcp_server`) already rejects tools not in the config's
allowlist and git/transaction tools on multi-store composites. Without
a list-time filter, those tools still appear in ``tools/list`` — so
clients display them and only learn they can't use them by calling
them. This middleware hides them at list time.

``resources/list`` is augmented to enumerate ``README.md`` files from
the active composite filesystem, which the static enumeration in
:func:`stash_mcp.mcp_server.create_mcp_server` skips in auth mode
(there's no single store to walk at create-time — each request sees a
different composite).
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Sequence

from fastmcp.resources import FunctionResource, Resource
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.tool import Tool
from pydantic import AnyUrl

logger = logging.getLogger(__name__)


# Active MCP sessions, registered on initialize and used by
# :func:`broadcast_catalog_changed` to push tools/list_changed +
# resources/list_changed notifications when an admin edits an
# MCP-server config. WeakSet so closed sessions deregister on GC.
_active_sessions: weakref.WeakSet = weakref.WeakSet()


async def broadcast_catalog_changed() -> None:
    """Notify every connected session that the tool/resource catalog
    has changed.

    Called by admin endpoints after they commit a mutation to an
    ``McpServer`` row (or its tools / content roots / mounts). Each
    client's subsequent ``tools/list`` and ``resources/list`` requests
    flow through :class:`AuthListingMiddleware`, which filters per
    config — so broadcasting to all sessions is safe (clients whose
    config didn't change will re-fetch and see the same list).

    Best-effort: failures to notify a single session (closed transport,
    backpressure) are logged at DEBUG and swallowed so admin requests
    aren't blocked by a stuck MCP client.
    """
    if not _active_sessions:
        return
    for sess in list(_active_sessions):
        try:
            await sess.send_tool_list_changed()
            await sess.send_resource_list_changed()
        except Exception as exc:
            logger.debug(
                "Catalog broadcast skipped for one session: %s", exc
            )


class AuthListingMiddleware(Middleware):
    """List-time filter for ``tools/list`` and ``resources/list``.

    Runs after the HTTP middleware stack has set ``current_principal``,
    ``current_store`` and (when the token is scoped)
    ``current_mcp_server`` via contextvars.

    Also registers each session in :data:`_active_sessions` on
    ``initialize`` so admin-side config edits can fan out
    ``tools/list_changed`` notifications via
    :func:`broadcast_catalog_changed`.
    """

    async def on_initialize(
        self,
        context: MiddlewareContext,
        call_next,
    ):
        result = await call_next(context)
        try:
            session = context.fastmcp_context.session
        except Exception:
            session = None
        if session is not None:
            _active_sessions.add(session)
        return result

    async def on_list_tools(
        self,
        context: MiddlewareContext,
        call_next,
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        # Imported lazily to avoid pulling routing/auth into the
        # mcp_server module at import time (and to keep the legacy
        # ``AUTH_ENABLED=False`` path free of those imports).
        from .mcp_server import _MULTI_STORE_DISALLOWED_TOOLS
        from .routing.context import current_store
        from .routing.mcp_server_resolver import current_mcp_server

        config = current_mcp_server()
        if config is None:
            return tools  # unscoped — leave the catalog untouched

        allowed = {t.tool_name for t in config.tools}
        store = current_store()
        is_multi_store = (
            store is not None
            and getattr(store, "is_single_store", True) is False
        )

        filtered: list[Tool] = []
        for tool in tools:
            if tool.name not in allowed:
                continue
            if is_multi_store and tool.name in _MULTI_STORE_DISALLOWED_TOOLS:
                continue
            filtered.append(tool)
        return filtered

    async def on_list_resources(
        self,
        context: MiddlewareContext,
        call_next,
    ) -> Sequence[Resource]:
        from .mcp_server import (
            _get_description,
            _get_mime_type,
            _is_resource_file,
        )
        from .routing.context import current_store

        static = list(await call_next(context))
        store = current_store()
        if store is None:
            return static

        fs = store.filesystem
        try:
            paths = fs.list_all_files()
        except Exception as exc:
            # Listing failures shouldn't break the protocol — fall back
            # to whatever static resources happen to be registered.
            logger.warning(
                "resources/list enumeration failed: %s", exc, exc_info=True
            )
            return static

        existing_uris = {str(r.uri) for r in static}
        for path in paths:
            if not _is_resource_file(path):
                continue
            uri = f"stash://{path}"
            if uri in existing_uris:
                continue
            try:
                description = _get_description(fs, path)
            except Exception:
                description = f"Content file: {path}"
            # Reads come back through the ``stash://{path}`` resource
            # template (registered in ``create_mcp_server``), so the
            # ``fn`` here is only used if the client happens to read
            # via the registered URI — fall back to the same composite
            # filesystem so it works regardless.
            captured_fs = fs
            captured_path = path
            static.append(
                FunctionResource(
                    uri=AnyUrl(uri),
                    name=path,
                    description=description,
                    mime_type=_get_mime_type(path),
                    fn=lambda _fs=captured_fs, _p=captured_path: _fs.read_file(_p),
                )
            )
        return static


__all__ = ["AuthListingMiddleware"]
