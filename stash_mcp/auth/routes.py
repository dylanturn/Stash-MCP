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
from ..db.models import ApiToken, AuditEvent
from ..db.session import get_session
from ..errors import (
    Forbidden,
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


class TokenIssued(BaseModel):
    id: UUID
    name: str
    scopes: list[str]
    token: str  # plaintext — returned ONCE
    created_at: datetime
    expires_at: datetime | None


class TokenInfo(BaseModel):
    id: UUID
    name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


def _parse_scopes(raw: str) -> list[str]:
    return [s for s in raw.split(",") if s]


def _serialize_token(row: ApiToken) -> TokenInfo:
    return TokenInfo(
        id=row.id,
        name=row.name,
        scopes=_parse_scopes(row.scopes),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
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
    return [_serialize_token(r) for r in rows]


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
    )
    session.add(row)
    await session.flush()

    session.add(
        AuditEvent(
            actor_user_id=principal.user_id,
            actor_kind="user",
            action="token.issued",
            target_kind="token",
            target_id=str(row.id),
            detail=json.dumps(
                {
                    "name": row.name,
                    "scopes": _parse_scopes(row.scopes),
                    "expires_at": row.expires_at.isoformat()
                    if row.expires_at
                    else None,
                }
            ),
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
    )


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
]
