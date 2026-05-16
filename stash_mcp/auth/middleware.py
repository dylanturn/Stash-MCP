"""``StashAuthMiddleware`` — ASGI middleware that runs the configured
``AuthProvider`` chain in front of both ``/api`` and ``/mcp``.

When ``AUTH_ENABLED=false`` the middleware no-ops. When enabled, every
request either:

* hits a public-allowlisted path (``/api/health``, ``/auth/*``, ``/static``);
* gets a ``Principal`` from one of the providers (short-circuits on first
  success) and proceeds with that principal in the contextvar; or
* gets rejected — 401 for API/MCP paths (with the rejecting provider's
  ``WWW-Authenticate`` if any), 302 → ``/auth/login`` for GET ``/ui``.
"""

from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import Config
from .context import reset_current_principal, set_current_principal
from .principal import Principal
from .provider import AuthError, AuthProvider

# Paths that are always public (no auth attempt, no rejection). The auth
# endpoints themselves don't require an existing session — they're how you
# get one. Health is open so liveness probes work without credentials.
_PUBLIC_PATHS: tuple[str, ...] = (
    "/api/health",
    "/auth/login",
    "/auth/callback",
    "/static/",
)


class StashAuthMiddleware:
    def __init__(self, app: ASGIApp, providers: list[AuthProvider]):
        self.app = app
        self.providers = providers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not Config.AUTH_ENABLED:
            await self.app(scope, receive, send)
            return

        path: str = scope["path"]
        if any(path == p or path.startswith(p) for p in _PUBLIC_PATHS):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        principal: Principal | None = None
        last_err: AuthError | None = None
        for provider in self.providers:
            try:
                principal = await provider.authenticate(request)
            except AuthError as exc:
                last_err = exc
                principal = None
                break  # active rejection — don't try further providers
            if principal is not None:
                break

        if principal is None:
            method = scope.get("method", "GET")
            if method == "GET" and path.startswith("/ui"):
                redirect = f"/auth/login?next={quote(path)}"
                resp = Response(
                    status_code=302, headers={"Location": redirect}
                )
                await resp(scope, receive, send)
                return
            www_auth = (
                last_err.www_authenticate
                if (last_err is not None and last_err.www_authenticate)
                else 'Bearer realm="stash"'
            )
            body = {"error": "unauthenticated"}
            if last_err is not None:
                body["detail"] = str(last_err)
            resp = JSONResponse(
                body,
                status_code=401,
                headers={"WWW-Authenticate": www_auth},
            )
            await resp(scope, receive, send)
            return

        token = set_current_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_principal(token)
