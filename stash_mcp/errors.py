"""RFC 7807 Problem Details for the auth/admin/per-store HTTP surface.

New endpoints (``/auth/*``, ``/admin/*``, per-store ``/api/<t>/<s>/*``)
raise the typed subclasses below; :func:`install_problem_handlers` wires
a FastAPI exception handler that renders them with the
``application/problem+json`` media type. Legacy auth-disabled ``/api/*``
endpoints keep their existing ``{"detail": "..."}`` shape so older
deployments aren't disturbed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

PROBLEM_MEDIA_TYPE = "application/problem+json"


@dataclass(frozen=True)
class Problem:
    type: str
    title: str
    status: int
    detail: str | None = None


class StashError(Exception):
    """Base class for typed errors that render as Problem Details.

    Subclasses set a class-level ``problem`` attribute. Callers may pass a
    per-instance ``detail`` and any number of ``extras`` keyword args that
    are merged into the response body (used for things like
    ``current_etag`` on 412s or ``required_scope`` on 403s).
    """

    problem: Problem

    def __init__(self, detail: str | None = None, **extras: Any) -> None:
        self.detail = detail
        self.extras = extras
        super().__init__(detail or self.problem.title)


# --- Registry of standard problems -----------------------------------------

class Unauthenticated(StashError):
    problem = Problem(
        "/problems/auth/unauthenticated", "Authentication required", 401
    )


class Forbidden(StashError):
    problem = Problem("/problems/auth/forbidden", "Forbidden", 403)


class ScopeRequired(StashError):
    problem = Problem(
        "/problems/auth/scope-required", "Insufficient scope", 403
    )


class ContentNotFound(StashError):
    problem = Problem(
        "/problems/content/not-found", "Content not found", 404
    )


class ETagMismatch(StashError):
    problem = Problem(
        "/problems/content/etag-mismatch",
        "ETag mismatch on conditional write",
        412,
    )


class StoreNotFound(StashError):
    problem = Problem("/problems/store/not-found", "Store not found", 404)


class StoreAlreadyExists(StashError):
    problem = Problem(
        "/problems/store/already-exists", "Store already exists", 409
    )


class StoreNotProvisioned(StashError):
    problem = Problem(
        "/problems/store/not-provisioned",
        "Store has DB row but no on-disk repo",
        500,
    )


class TenantNotFound(StashError):
    problem = Problem("/problems/tenant/not-found", "Tenant not found", 404)


class TenantAlreadyExists(StashError):
    problem = Problem(
        "/problems/tenant/already-exists", "Tenant already exists", 409
    )


class TenantHasStores(StashError):
    problem = Problem(
        "/problems/tenant/has-stores",
        "Tenant cannot be deleted while it owns stores",
        409,
    )


class UserNotFound(StashError):
    problem = Problem("/problems/user/not-found", "User not found", 404)


class TokenNotFound(StashError):
    problem = Problem("/problems/token/not-found", "Token not found", 404)


class MembershipNotFound(StashError):
    problem = Problem(
        "/problems/membership/not-found", "Membership not found", 404
    )


class MembershipExists(StashError):
    problem = Problem(
        "/problems/membership/exists", "Membership already exists", 409
    )


class ValidationError(StashError):
    problem = Problem("/problems/validation", "Validation failed", 400)


class ConfirmationRequired(StashError):
    problem = Problem(
        "/problems/confirmation-required",
        "Destructive operation requires confirm=true",
        400,
    )


def problem_response(
    *, request: Request | None, err: StashError
) -> JSONResponse:
    """Render a :class:`StashError` as an ``application/problem+json``."""
    p = err.problem
    body: dict[str, Any] = {
        "type": p.type,
        "title": p.title,
        "status": p.status,
    }
    if request is not None:
        body["instance"] = request.url.path
    detail = err.detail or p.detail
    if detail:
        body["detail"] = detail
    if err.extras:
        for k, v in err.extras.items():
            if k not in body:
                body[k] = v
    headers: dict[str, str] = {}
    if p.status == 401:
        headers["WWW-Authenticate"] = 'Bearer realm="stash"'
    return JSONResponse(
        body,
        status_code=p.status,
        headers=headers,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def install_problem_handlers(app: FastAPI) -> None:
    """Register the FastAPI exception handler for :class:`StashError`."""

    @app.exception_handler(StashError)
    async def _stash_error_handler(
        request: Request, exc: StashError
    ) -> JSONResponse:
        return problem_response(request=request, err=exc)


__all__ = [
    "PROBLEM_MEDIA_TYPE",
    "ConfirmationRequired",
    "ContentNotFound",
    "ETagMismatch",
    "Forbidden",
    "MembershipExists",
    "MembershipNotFound",
    "Problem",
    "ScopeRequired",
    "StashError",
    "StoreAlreadyExists",
    "StoreNotFound",
    "StoreNotProvisioned",
    "TenantAlreadyExists",
    "TenantHasStores",
    "TenantNotFound",
    "TokenNotFound",
    "Unauthenticated",
    "UserNotFound",
    "ValidationError",
    "install_problem_handlers",
    "problem_response",
]
