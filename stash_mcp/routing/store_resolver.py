"""ASGI middleware that resolves ``/api/<tenant>/<store>`` and
``/mcp/<tenant>/<store>`` to a :class:`LoadedStore`, sets the
``current_store`` contextvar, and rewrites the path so the mounted
subapp sees the same routes it always has.

Sits *after* :class:`StashAuthMiddleware` in the stack so it can read
``current_principal()``. When ``AUTH_ENABLED=False`` the middleware
no-ops.
"""

from __future__ import annotations

import json
import logging
import re

from starlette.types import ASGIApp, Receive, Scope, Send

from ..auth.context import current_principal
from ..config import Config
from ..stores.registry import StoreNotProvisionedError, StoreRegistry
from .context import reset_current_store, set_current_store

logger = logging.getLogger(__name__)

_SLUG = r"[a-z0-9][a-z0-9-]{0,62}"
_API_RE = re.compile(rf"^/api/(?P<tenant>{_SLUG})/(?P<store>{_SLUG})(?P<rest>/.*)?$")
_MCP_RE = re.compile(rf"^/mcp/(?P<tenant>{_SLUG})/(?P<store>{_SLUG})(?P<rest>/.*)?$")


async def _send_json(send: Send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


class StoreResolverMiddleware:
    """Resolve ``/api/<tenant>/<store>`` and ``/mcp/<tenant>/<store>``.

    Args:
        app: Next ASGI app in the chain.
        registry: Process-wide :class:`StoreRegistry`.
        public_prefixes: Path prefixes that bypass the resolver entirely
            (health, auth, admin, ui, static, openapi).
    """

    def __init__(
        self,
        app: ASGIApp,
        registry: StoreRegistry,
        public_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.registry = registry
        self.public_prefixes = public_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not Config.AUTH_ENABLED:
            await self.app(scope, receive, send)
            return

        # If McpServerResolverMiddleware (spec 04) already bound a
        # composite store for this request from a scoped token, don't
        # override the binding — let the request flow through as-is.
        from .context import current_store as _current_store

        if _current_store() is not None:
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]

        # Pass-through for paths that don't carry a tenant+store.
        if any(path == p or path.startswith(p) for p in self.public_prefixes):
            await self.app(scope, receive, send)
            return

        is_api = path == "/api" or path.startswith("/api/")
        is_mcp = path == "/mcp" or path.startswith("/mcp/")
        if not (is_api or is_mcp):
            await self.app(scope, receive, send)
            return

        m = _API_RE.match(path) or _MCP_RE.match(path)
        if m is None:
            await _send_json(
                send,
                404,
                {
                    "error": "not_found",
                    "detail": (
                        "expected /api/<tenant>/<store>/... or /mcp/<tenant>/<store>/..."
                    ),
                },
            )
            return

        principal = current_principal()
        if principal is None:
            # Defensive — the auth middleware should have rejected first.
            await _send_json(
                send, 401, {"error": "unauthenticated"}
            )
            return

        tenant_slug = m.group("tenant")
        store_slug = m.group("store")
        try:
            loaded = await self.registry.get(tenant_slug, store_slug)
        except KeyError:
            await _send_json(
                send,
                404,
                {
                    "error": "not_found",
                    "detail": f"store {tenant_slug}/{store_slug} not found",
                },
            )
            return
        except StoreNotProvisionedError as exc:
            logger.error("Store %s/%s not provisioned: %s", tenant_slug, store_slug, exc)
            await _send_json(
                send,
                500,
                {
                    "error": "store_not_provisioned",
                    "detail": str(exc),
                },
            )
            return

        if not principal.has_role_on(loaded.tenant_id, "member"):
            # 403 — principal is authenticated but not a member of the
            # URL's tenant. Don't leak whether the store exists.
            await _send_json(
                send,
                403,
                {
                    "error": "forbidden",
                    "detail": f"not a member of tenant {tenant_slug}",
                },
            )
            return

        # Rewrite the path so the subapp sees /api/<rest> or /mcp/<rest>.
        prefix = "/api" if is_api else "/mcp"
        rest = m.group("rest") or "/"
        new_path = prefix + rest
        new_scope = dict(scope)
        new_scope["path"] = new_path
        new_scope["raw_path"] = new_path.encode("utf-8")

        token = set_current_store(loaded)
        try:
            await self.app(new_scope, receive, send)
        finally:
            reset_current_store(token)
