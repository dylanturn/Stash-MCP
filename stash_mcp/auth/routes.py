"""``/auth/*`` routes — OIDC login, callback, logout, and API-token CRUD.

``/auth/login`` and ``/auth/callback`` implement the OIDC authorisation
code flow via :mod:`authlib`. On a successful callback we materialise the
DB user via :func:`upsert_user_and_memberships`, sign a Stash session
cookie, and 302 to the originating ``next`` URL.

``/auth/tokens`` lets a cookie-authenticated user mint and revoke their
own Stash API tokens. Bearer-JWT and api-token callers are explicitly
denied — the discrimination is the whole point of the three-valued
``auth_method`` enum on :class:`Principal`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import RedirectResponse

from ..config import Config
from ..db.models import ApiToken, AuditEvent, McpServer, Store, Tenant
from ..db.session import get_session
from ..errors import (
    Forbidden,
    McpServerForbidden,
    McpServerNotFound,
    TokenNotFound,
    Unauthenticated,
    ValidationError,
)
from .context import current_principal
from .principal import Principal
from .sessions import issue_session
from .tokens import generate_token, hash_with_active_key
from .users import upsert_user_and_memberships

logger = logging.getLogger(__name__)

# authlib OAuth instance. Lazily configured the first time we need it so
# importing this module is safe under ``AUTH_ENABLED=False``.
_oauth: OAuth | None = None


def _is_local_dev() -> bool:
    """Heuristic for whether we should drop the ``Secure`` cookie flag."""
    host = (Config.HOST or "").strip()
    return host in ("127.0.0.1", "localhost", "0.0.0.0") or os.getenv(
        "STASH_INSECURE_COOKIES"
    ) == "true"


def get_oauth() -> OAuth:
    """Return the process-wide :class:`OAuth` instance, registering on first use."""
    global _oauth
    if _oauth is None:
        oauth = OAuth()
        oauth.register(
            name="idp",
            server_metadata_url=Config.OIDC_DISCOVERY_URL,
            client_id=Config.OIDC_CLIENT_ID,
            client_secret=Config.OIDC_CLIENT_SECRET,
            client_kwargs={"scope": Config.OIDC_SCOPES},
        )
        _oauth = oauth
    return _oauth


def reset_oauth_for_tests() -> None:
    """Drop the cached OAuth registration. Test-only."""
    global _oauth
    _oauth = None


# --- request/response models -------------------------------------------------


class TokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"])
    expires_in_days: int | None = Field(default=90, ge=1, le=3650)
    # Optional binding to a specific MCP-server config from spec 02. If
    # set, the token's authorisation surface is determined by the
    # config's tool allowlist + content roots at runtime (spec 04). If
    # NULL, the token behaves as it always has — legacy URL-based store
    # routing.
    mcp_server_id: UUID | None = None


class McpServerBinding(BaseModel):
    """The MCP-server config a token is bound to.

    Returned alongside :class:`TokenInfo` on list/create so the UI can
    render the badge without a second roundtrip.
    """

    id: UUID
    tenant_slug: str
    slug: str
    name: str


class TokenIssued(BaseModel):
    id: UUID
    name: str
    scopes: list[str]
    token: str  # plaintext — returned ONCE
    created_at: datetime
    expires_at: datetime | None
    mcp_server: McpServerBinding | None = None


class TokenInfo(BaseModel):
    id: UUID
    name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    mcp_server: McpServerBinding | None = None


class VisibleMcpServer(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_slug: str
    slug: str
    name: str


def _parse_scopes(raw: str) -> list[str]:
    return [s for s in raw.split(",") if s]


def _binding_from(server: McpServer | None, tenant_slug: str | None) -> McpServerBinding | None:
    if server is None or tenant_slug is None:
        return None
    return McpServerBinding(
        id=server.id,
        tenant_slug=tenant_slug,
        slug=server.slug,
        name=server.name,
    )


def _serialize_token(
    row: ApiToken, binding: McpServerBinding | None = None
) -> TokenInfo:
    return TokenInfo(
        id=row.id,
        name=row.name,
        scopes=_parse_scopes(row.scopes),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        mcp_server=binding,
    )


# --- session dependency -----------------------------------------------------


def require_session() -> Principal:
    """FastAPI dependency: principal must be cookie-authenticated.

    Bearer-JWT (``oidc``) and api-token callers get 403 — only browser
    sessions are allowed to mint or revoke API tokens.
    """
    principal = current_principal()
    if principal is None:
        raise Unauthenticated("login required to manage API tokens")
    if principal.auth_method != "session":
        raise Forbidden(
            "API token management requires a browser session cookie"
        )
    return principal


# --- router -----------------------------------------------------------------


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request, next: str = "/ui") -> Any:
    """Kick off the OIDC authorization-code flow.

    Stores the ``next`` path in the Starlette session (signed cookie owned
    by ``SessionMiddleware``) so the callback can land the browser where
    it asked to go.
    """
    redirect_uri = str(request.url_for("oidc_callback"))
    request.session["next"] = next
    return await get_oauth().idp.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="oidc_callback")
async def callback(
    request: Request, session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    """Complete the OIDC dance and issue the Stash session cookie."""
    token = await get_oauth().idp.authorize_access_token(request)
    claims = token.get("userinfo") or {}
    if not claims:
        # authlib usually parses the id_token for us; fall back to the
        # raw id_token claims when the IdP omits userinfo.
        claims = token.get("id_token_claims", {}) or {}
    if "sub" not in claims:
        raise ValidationError("OIDC callback returned no usable claims")

    user = await upsert_user_and_memberships(session, claims)
    await session.commit()

    cookie_value = issue_session(user_id=str(user.id), oidc_sub=user.oidc_sub)
    next_path = request.session.pop("next", "/ui")
    if not isinstance(next_path, str) or not next_path.startswith("/"):
        next_path = "/ui"

    resp = RedirectResponse(url=next_path, status_code=302)
    resp.set_cookie(
        Config.SESSION_COOKIE_NAME,
        cookie_value,
        max_age=Config.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=not _is_local_dev(),
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear the Stash session cookie. Does not call IdP RP-logout."""
    next_path = request.query_params.get("next", "/ui")
    if not next_path.startswith("/"):
        next_path = "/ui"
    resp = RedirectResponse(url=next_path, status_code=302)
    resp.delete_cookie(Config.SESSION_COOKIE_NAME, path="/")
    request.session.pop("next", None)
    return resp


# Allow GET as a convenience for the UI's "Sign out" link.
@router.get("/logout")
async def logout_get(request: Request) -> RedirectResponse:
    return await logout(request)


class TenantMembership(BaseModel):
    id: UUID
    slug: str
    display_name: str
    role: str


class MeResponse(BaseModel):
    user_id: UUID
    oidc_sub: str
    email: str
    display_name: str
    auth_method: str
    tenant_roles: dict[str, str]
    tenants: list[TenantMembership]


class StoreSummary(BaseModel):
    id: UUID
    slug: str
    display_name: str
    tenant_id: UUID
    tenant_slug: str
    tenant_display_name: str
    role: str


@router.get("/me", response_model=MeResponse)
async def me(
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    """Return the current principal as JSON for the SPA to consume.

    Any authenticated method is accepted; the upstream auth middleware
    has already populated the contextvar. A 401 from this endpoint is
    the SPA's cue to bounce the browser through ``/auth/login``.

    Includes a ``tenants`` array with each membership's display name and
    slug so the SPA can render tenant pickers (e.g. "create your first
    store") without a second roundtrip.
    """
    p = current_principal()
    if p is None:
        raise Unauthenticated("login required")
    tenant_ids = list(p.tenant_roles.keys())
    memberships: list[TenantMembership] = []
    if tenant_ids:
        rows = (
            (
                await session.execute(
                    select(Tenant)
                    .where(Tenant.id.in_(tenant_ids))
                    .order_by(Tenant.slug)
                )
            )
            .scalars()
            .all()
        )
        memberships = [
            TenantMembership(
                id=t.id,
                slug=t.slug,
                display_name=t.display_name,
                role=p.tenant_roles[t.id],
            )
            for t in rows
        ]
    return MeResponse(
        user_id=p.user_id,
        oidc_sub=p.oidc_sub,
        email=p.email,
        display_name=p.display_name,
        auth_method=p.auth_method,
        tenant_roles={str(tid): r for tid, r in p.tenant_roles.items()},
        tenants=memberships,
    )


@router.get("/stores", response_model=list[StoreSummary])
async def my_stores(
    session: AsyncSession = Depends(get_session),
) -> list[StoreSummary]:
    """Stores the current principal can access across all their tenant memberships.

    Includes ``tenant_slug`` so the SPA can build ``/ui/<tenant>/<store>/``
    URLs without a second lookup. Empty list when the principal has no
    memberships — the SPA renders ``/no-stores`` for that case.
    """
    p = current_principal()
    if p is None:
        raise Unauthenticated("login required")
    tenant_ids = list(p.tenant_roles.keys())
    if not tenant_ids:
        return []
    stmt = (
        select(Store, Tenant)
        .join(Tenant, Tenant.id == Store.tenant_id)
        .where(Store.tenant_id.in_(tenant_ids))
        .order_by(Tenant.slug, Store.slug)
    )
    rows = (await session.execute(stmt)).all()
    return [
        StoreSummary(
            id=store.id,
            slug=store.slug,
            display_name=store.display_name,
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            tenant_display_name=tenant.display_name,
            role=p.tenant_roles[tenant.id],
        )
        for store, tenant in rows
    ]


async def _bindings_for_tokens(
    session: AsyncSession, rows: list[ApiToken]
) -> dict[UUID, McpServerBinding]:
    """Resolve the McpServerBinding for each token in one query."""
    server_ids = {r.mcp_server_id for r in rows if r.mcp_server_id is not None}
    if not server_ids:
        return {}
    res = (
        await session.execute(
            select(McpServer, Tenant.slug)
            .join(Tenant, Tenant.id == McpServer.tenant_id)
            .where(McpServer.id.in_(server_ids))
        )
    ).all()
    return {
        server.id: McpServerBinding(
            id=server.id,
            tenant_slug=tenant_slug,
            slug=server.slug,
            name=server.name,
        )
        for server, tenant_slug in res
    }


@router.get("/tokens", response_model=list[TokenInfo])
async def list_tokens(
    principal: Principal = Depends(require_session),
    session: AsyncSession = Depends(get_session),
    include_revoked: bool = Query(default=False),
) -> list[TokenInfo]:
    stmt = select(ApiToken).where(ApiToken.user_id == principal.user_id)
    if not include_revoked:
        stmt = stmt.where(ApiToken.revoked_at.is_(None))
    rows = (await session.execute(stmt.order_by(ApiToken.created_at.desc()))).scalars().all()
    bindings = await _bindings_for_tokens(session, rows)
    return [
        _serialize_token(
            r,
            bindings.get(r.mcp_server_id) if r.mcp_server_id else None,
        )
        for r in rows
    ]


@router.post("/tokens", response_model=TokenIssued, status_code=201)
async def create_token(
    body: TokenCreate,
    principal: Principal = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> TokenIssued:
    valid_scopes = {"read", "write", "admin"}
    if not body.scopes:
        raise ValidationError("scopes must not be empty")
    bad = [s for s in body.scopes if s not in valid_scopes]
    if bad:
        raise ValidationError(
            f"unknown scopes: {bad}; valid scopes are {sorted(valid_scopes)}"
        )

    binding: McpServerBinding | None = None
    if body.mcp_server_id is not None:
        server = await session.get(McpServer, body.mcp_server_id)
        if server is None:
            raise McpServerNotFound(
                f"mcp-server {body.mcp_server_id} not found"
            )
        # Any membership role on the config's tenant is sufficient.
        if not principal.has_role_on(server.tenant_id, "member"):
            raise McpServerForbidden(
                "you are not a member of the tenant this MCP server belongs to"
            )
        tenant = await session.get(Tenant, server.tenant_id)
        binding = _binding_from(server, tenant.slug if tenant else None)

    keys = Config.AUTH_TOKEN_HMAC_KEYS
    plaintext = generate_token()
    token_hash, key_version = hash_with_active_key(plaintext, keys=keys)

    expires_at = None
    if body.expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    row = ApiToken(
        user_id=principal.user_id,
        token_hash=token_hash,
        key_version=key_version,
        name=body.name,
        scopes=",".join(sorted(set(body.scopes))),
        expires_at=expires_at,
        mcp_server_id=body.mcp_server_id,
    )
    session.add(row)
    await session.flush()

    audit_detail: dict[str, Any] = {
        "name": row.name,
        "scopes": _parse_scopes(row.scopes),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }
    if row.mcp_server_id is not None:
        audit_detail["mcp_server_id"] = str(row.mcp_server_id)
    session.add(
        AuditEvent(
            actor_user_id=principal.user_id,
            actor_kind="user",
            action="token.issued",
            target_kind="token",
            target_id=str(row.id),
            detail=json.dumps(audit_detail),
        )
    )
    await session.commit()
    await session.refresh(row)

    return TokenIssued(
        id=row.id,
        name=row.name,
        scopes=_parse_scopes(row.scopes),
        token=plaintext,
        created_at=row.created_at,
        expires_at=row.expires_at,
        mcp_server=binding,
    )


@router.get(
    "/visible-mcp-servers", response_model=list[VisibleMcpServer]
)
async def list_visible_mcp_servers(
    principal: Principal = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> list[VisibleMcpServer]:
    """List MCP-server configs visible to the principal.

    Returns one row per enabled config in any tenant the principal is
    a member of. Used by the token-mint UI to populate the server
    picker. Not admin-gated — a member can see config names in their
    tenant.
    """
    tenant_ids = list(principal.tenant_roles.keys())
    if not tenant_ids:
        return []
    rows = (
        await session.execute(
            select(McpServer, Tenant.slug, Tenant.id)
            .join(Tenant, Tenant.id == McpServer.tenant_id)
            .where(McpServer.tenant_id.in_(tenant_ids))
            .where(McpServer.enabled.is_(True))
            .order_by(Tenant.slug, McpServer.slug)
        )
    ).all()
    return [
        VisibleMcpServer(
            id=server.id,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            slug=server.slug,
            name=server.name,
        )
        for server, tenant_slug, tenant_id in rows
    ]


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: UUID,
    principal: Principal = Depends(require_session),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = (
        await session.execute(
            select(ApiToken).where(
                ApiToken.id == token_id,
                ApiToken.user_id == principal.user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise TokenNotFound()
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                actor_user_id=principal.user_id,
                actor_kind="user",
                action="token.revoked",
                target_kind="token",
                target_id=str(row.id),
                detail=json.dumps({"name": row.name}),
            )
        )
    await session.commit()


__all__ = [
    "router",
    "require_session",
    "get_oauth",
    "reset_oauth_for_tests",
    "TokenCreate",
    "TokenIssued",
    "TokenInfo",
    "McpServerBinding",
    "MeResponse",
    "TenantMembership",
    "StoreSummary",
    "VisibleMcpServer",
]
