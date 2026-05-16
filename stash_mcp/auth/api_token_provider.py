"""``ApiTokenAuthProvider`` — verifies Stash-issued opaque API tokens.

A bearer token that starts with the ``stash_pat_`` prefix is hashed with
HMAC-SHA256 under each currently-trusted key, the row is looked up by hash,
and the row's recorded ``key_version`` is re-verified before accepting.
On success the row's ``last_used_at`` is bumped and a ``Principal`` with
``auth_method='api_token'`` is returned.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from starlette.requests import Request

from ..config import Config
from ..db.models import ApiToken, User
from ..db.session import get_sessionmaker
from .principal import Principal, Role
from .provider import AuthError, AuthProvider
from .tokens import hash_token, looks_like_stash_token, verify_token

_INVALID_TOKEN = 'Bearer realm="stash", error="invalid_token"'


class ApiTokenAuthProvider(AuthProvider):
    """Authenticates ``Authorization: Bearer stash_pat_...`` requests."""

    name = "api_token"

    async def authenticate(self, request: Request) -> Principal | None:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        if not looks_like_stash_token(token):
            return None  # let OIDC provider try

        keys = Config.AUTH_TOKEN_HMAC_KEYS
        if not keys:
            # Misconfiguration — validate_auth_config should have refused boot
            # when AUTH_ENABLED. If we got here without keys, fail closed.
            raise AuthError(
                "api token auth not configured",
                www_authenticate=_INVALID_TOKEN,
            )

        # Hash under every currently-trusted key; the matching row will hash
        # equal under exactly one of them. Map hash → key_version so the
        # post-fetch verify can confirm the row's recorded key matches the
        # slot we hashed with.
        candidates: dict[str, int] = {
            hash_token(token, key=k): idx for idx, k in enumerate(keys)
        }

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            result = await session.execute(
                select(ApiToken)
                .options(
                    selectinload(ApiToken.user).selectinload(User.memberships)
                )
                .where(ApiToken.token_hash.in_(candidates.keys()))
            )
            row = result.scalar_one_or_none()
            if row is None:
                # Token shape matches but no row hashes to it — actively reject
                # so the middleware doesn't try further providers.
                raise AuthError("invalid api token", www_authenticate=_INVALID_TOKEN)

            # Defence-in-depth: the row records which key_version hashed it.
            # If that key was rotated out, the row's hash should no longer
            # match anything in `keys` — but if a freshly-introduced key
            # happens to collide with the rotated-out one, we still refuse.
            matched_slot = candidates.get(row.token_hash, -1)
            if matched_slot != row.key_version or not verify_token(
                token, row.token_hash, keys=keys, key_version=row.key_version
            ):
                raise AuthError(
                    "api token signed by a rotated-out key",
                    www_authenticate=_INVALID_TOKEN,
                )

            now = datetime.now(UTC)
            if row.revoked_at is not None:
                raise AuthError(
                    "api token revoked", www_authenticate=_INVALID_TOKEN
                )
            if row.expires_at is not None and _as_utc(row.expires_at) <= now:
                raise AuthError(
                    "api token expired", www_authenticate=_INVALID_TOKEN
                )

            user = row.user
            tenant_roles: dict = {
                m.tenant_id: _coerce_role(m.role) for m in user.memberships
            }
            principal = Principal(
                user_id=user.id,
                oidc_sub=user.oidc_sub,
                email=user.email,
                display_name=user.display_name,
                auth_method="api_token",
                tenant_roles=tenant_roles,
                claims={
                    "token_id": str(row.id),
                    "token_name": row.name,
                    "scopes": row.scopes,
                    "key_version": row.key_version,
                },
            )

            await session.execute(
                update(ApiToken)
                .where(ApiToken.id == row.id)
                .values(last_used_at=now)
            )
            await session.commit()

        return principal


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC. SQLite drops tzinfo on
    ``DateTime(timezone=True)`` columns; Postgres preserves it. Either way
    the comparison must be against a TZ-aware ``now``."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _coerce_role(value: str) -> Role:
    # The DB column is a free-text String(16) constrained by a CheckConstraint
    # to ('admin','member'). Narrow it to the typed Literal for the Principal.
    if value not in ("admin", "member"):
        raise AuthError(f"unexpected membership role on token user: {value!r}")
    return value  # type: ignore[return-value]
