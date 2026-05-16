"""``SessionCookieAuthProvider`` — translates a signed session cookie to a
``Principal``.

The cookie itself only carries ``{uid, sub}``; everything else (email,
display name, memberships) is loaded from the DB on each request. Cookie
auth lands ``auth_method='session'`` so spec 05's ``require_session``
gate can distinguish cookie-authed browser callers (allowed to mint API
tokens) from bearer-JWT callers (not allowed).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.requests import Request

from ..config import Config
from ..db.models import User
from ..db.session import get_sessionmaker
from .principal import Principal, Role
from .provider import AuthError, AuthProvider
from .sessions import verify_session


class SessionCookieAuthProvider(AuthProvider):
    """Authenticates browser sessions via the signed session cookie."""

    name = "session_cookie"

    async def authenticate(self, request: Request) -> Principal | None:
        cookie = request.cookies.get(Config.SESSION_COOKIE_NAME)
        if not cookie:
            return None
        payload = verify_session(cookie)
        if payload is None:
            # Expired or tampered — let the middleware fall through to the
            # next provider (so a stale cookie + valid bearer still works)
            # rather than hard-rejecting the request.
            return None

        uid = payload.get("uid")
        if not isinstance(uid, str):
            return None
        try:
            user_uuid = uuid.UUID(uid)
        except ValueError:
            return None

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            user = (
                await session.execute(
                    select(User)
                    .options(selectinload(User.memberships))
                    .where(User.id == user_uuid)
                )
            ).scalar_one_or_none()
            if user is None:
                # Cookie references a user that no longer exists. Treat as
                # "no auth" — caller can re-login.
                return None

            tenant_roles: dict = {
                m.tenant_id: _coerce_role(m.role) for m in user.memberships
            }
            return Principal(
                user_id=user.id,
                oidc_sub=user.oidc_sub,
                email=user.email,
                display_name=user.display_name,
                auth_method="session",
                tenant_roles=tenant_roles,
                claims={"session_sub": payload.get("sub", "")},
            )


def _coerce_role(value: str) -> Role:
    if value not in ("admin", "member"):
        raise AuthError(f"unexpected membership role on session user: {value!r}")
    return value  # type: ignore[return-value]
