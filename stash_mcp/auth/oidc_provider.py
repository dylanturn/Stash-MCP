"""``OIDCAuthProvider`` — validates bearer JWTs against an OIDC IdP.

Discovery doc is fetched on demand and cached. JWKS keys are cached by
``kid`` and refetched on unknown ``kid`` so key rotation Just Works.

On success the provider upserts the ``users`` row, refreshes
``memberships`` from the ``groups`` claim (with **manual wins**
precedence), writes ``audit_events`` for any group-derived role change,
and returns a ``Principal``.

A small in-process LRU keyed by ``(sub, iat | jti)`` avoids re-hitting the
DB on every MCP tool call when a client hammers with the same JWT.
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from sqlalchemy import select
from starlette.requests import Request

from ..config import Config
from ..db.models import AuditEvent, Membership, Tenant, User
from ..db.session import get_sessionmaker
from .principal import Principal, Role
from .provider import AuthError, AuthProvider
from .tokens import looks_like_stash_token

logger = logging.getLogger(__name__)

_BEARER_REALM = 'Bearer realm="stash"'
_DEFAULT_TENANT_SLUG = "default"
_DEFAULT_TENANT_DISPLAY_NAME = "Default tenant"
_JWKS_NEGATIVE_TTL = 60.0  # seconds
_PRINCIPAL_CACHE_MAX = 256
_PRINCIPAL_CACHE_MAX_TTL = 300.0  # 5 minutes, regardless of JWT lifetime


@dataclass(frozen=True)
class _DiscoveryDoc:
    issuer: str
    jwks_uri: str


class OIDCAuthProvider(AuthProvider):
    """Authenticates ``Authorization: Bearer <jwt>`` requests."""

    name = "oidc"

    def __init__(self, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient(timeout=5.0)
        self._owns_http = http_client is None
        self._jwt = JsonWebToken(["RS256", "RS384", "RS512", "ES256"])
        self._discovery: _DiscoveryDoc | None = None
        self._jwks_by_kid: dict[str, Any] = {}
        self._jwks_negative_cache_until: float = 0.0
        # Principal cache: key=(sub, iat-or-jti), value=(expires_epoch, Principal)
        self._principal_cache: OrderedDict[tuple[str, str], tuple[float, Principal]] = (
            OrderedDict()
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def authenticate(self, request: Request) -> Principal | None:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        if looks_like_stash_token(token):
            return None  # ApiTokenAuthProvider's problem

        # Decode the header without verifying so we can pick the right key.
        try:
            header_b64, payload_b64, _sig = token.split(".", 2)
        except ValueError as exc:
            raise AuthError("malformed jwt", www_authenticate=_BEARER_REALM) from exc

        try:
            header = json.loads(_b64url_decode(header_b64))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError(
                "malformed jwt header", www_authenticate=_BEARER_REALM
            ) from exc

        kid = header.get("kid")
        if not isinstance(kid, str):
            raise AuthError("jwt missing kid", www_authenticate=_BEARER_REALM)

        # Peek at claims for the cache key. Validation happens after.
        try:
            unverified_claims = json.loads(_b64url_decode(payload_b64))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthError(
                "malformed jwt payload", www_authenticate=_BEARER_REALM
            ) from exc

        sub = unverified_claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise AuthError("jwt missing sub", www_authenticate=_BEARER_REALM)
        iat = unverified_claims.get("iat")
        jti = unverified_claims.get("jti")
        cache_key = (sub, str(jti) if jti else str(iat) if iat is not None else "")
        if cache_key[1]:
            cached = self._principal_cache.get(cache_key)
            if cached is not None and cached[0] > time.time():
                # LRU bump
                self._principal_cache.move_to_end(cache_key)
                return cached[1]

        key = await self._get_signing_key(kid)
        try:
            claims = self._jwt.decode(token, key)
            claims.validate()
        except JoseError as exc:
            raise AuthError(
                f"jwt validation failed: {exc}", www_authenticate=_BEARER_REALM
            ) from exc

        # Audience + issuer checks. authlib's decode validates `exp/nbf/iat`
        # via .validate(); aud/iss aren't enforced unless we pass options, so
        # check them explicitly.
        discovery = await self._get_discovery()
        if claims.get("iss") != discovery.issuer:
            raise AuthError(
                "jwt issuer mismatch", www_authenticate=_BEARER_REALM
            )
        expected_aud = Config.OIDC_AUDIENCE or Config.OIDC_CLIENT_ID
        aud_claim = claims.get("aud")
        if isinstance(aud_claim, list):
            aud_ok = expected_aud in aud_claim
        else:
            aud_ok = aud_claim == expected_aud
        if not aud_ok:
            raise AuthError(
                "jwt audience mismatch", www_authenticate=_BEARER_REALM
            )

        principal = await self._materialize_principal(claims)

        # Cache. TTL = min(exp - iat, 5min). exp/iat are seconds-since-epoch.
        exp = claims.get("exp")
        if cache_key[1] and isinstance(exp, (int, float)):
            ttl = min(_PRINCIPAL_CACHE_MAX_TTL, float(exp) - time.time())
            if ttl > 0:
                self._principal_cache[cache_key] = (time.time() + ttl, principal)
                self._principal_cache.move_to_end(cache_key)
                while len(self._principal_cache) > _PRINCIPAL_CACHE_MAX:
                    self._principal_cache.popitem(last=False)

        return principal

    # --- Discovery + JWKS plumbing -----------------------------------------

    async def _get_discovery(self) -> _DiscoveryDoc:
        if self._discovery is not None:
            return self._discovery
        if not Config.OIDC_DISCOVERY_URL:
            raise AuthError(
                "OIDC discovery URL not configured", www_authenticate=_BEARER_REALM
            )
        try:
            resp = await self._http.get(Config.OIDC_DISCOVERY_URL)
            resp.raise_for_status()
            doc = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthError(
                f"OIDC discovery fetch failed: {exc}",
                www_authenticate=_BEARER_REALM,
            ) from exc
        issuer = doc.get("issuer")
        jwks_uri = doc.get("jwks_uri")
        if not isinstance(issuer, str) or not isinstance(jwks_uri, str):
            raise AuthError(
                "OIDC discovery doc missing issuer or jwks_uri",
                www_authenticate=_BEARER_REALM,
            )
        self._discovery = _DiscoveryDoc(issuer=issuer, jwks_uri=jwks_uri)
        return self._discovery

    async def _get_signing_key(self, kid: str) -> Any:
        cached = self._jwks_by_kid.get(kid)
        if cached is not None:
            return cached
        # Refresh JWKS — handles key rotation. Respect a short negative cache
        # so a flaky IdP doesn't get hammered.
        now = time.monotonic()
        if now < self._jwks_negative_cache_until:
            raise AuthError(
                "jwt signing key unknown (JWKS in negative cache)",
                www_authenticate=_BEARER_REALM,
            )
        try:
            await self._refresh_jwks()
        except AuthError:
            self._jwks_negative_cache_until = now + _JWKS_NEGATIVE_TTL
            raise
        cached = self._jwks_by_kid.get(kid)
        if cached is None:
            raise AuthError(
                "jwt signing key not in JWKS", www_authenticate=_BEARER_REALM
            )
        return cached

    async def _refresh_jwks(self) -> None:
        discovery = await self._get_discovery()
        try:
            resp = await self._http.get(discovery.jwks_uri)
            resp.raise_for_status()
            jwks = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthError(
                f"JWKS fetch failed: {exc}", www_authenticate=_BEARER_REALM
            ) from exc

        new_keys: dict[str, Any] = {}
        for key_doc in jwks.get("keys", []):
            kid = key_doc.get("kid")
            if not isinstance(kid, str):
                continue
            try:
                new_keys[kid] = JsonWebKey.import_key(key_doc)
            except Exception as exc:  # noqa: BLE001 — authlib raises bare Exception
                logger.warning("Skipping JWKS key kid=%s: %s", kid, exc)
        self._jwks_by_kid = new_keys

    # --- Principal materialisation -----------------------------------------

    async def _materialize_principal(self, claims: dict) -> Principal:
        sub = claims["sub"]
        email = _first_str(claims, ["email"]) or ""
        display_name = (
            _first_str(claims, ["name", "preferred_username", "email"]) or sub
        )

        groups_raw = claims.get(Config.OIDC_GROUPS_CLAIM, [])
        if not isinstance(groups_raw, list):
            groups_raw = []
        groups: set[str] = {g for g in groups_raw if isinstance(g, str)}

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            # Upsert user.
            user = (
                await session.execute(select(User).where(User.oidc_sub == sub))
            ).scalar_one_or_none()
            now = datetime.now(UTC)
            if user is None:
                user = User(
                    oidc_sub=sub,
                    email=email,
                    display_name=display_name,
                    last_login_at=now,
                )
                session.add(user)
                await session.flush()
            else:
                # Keep profile fields fresh.
                if email and user.email != email:
                    user.email = email
                if display_name and user.display_name != display_name:
                    user.display_name = display_name
                user.last_login_at = now

            # Group → admin membership sync. Manual wins (see README).
            await self._sync_admin_membership(session, user, groups)

            # Load memberships freshly for the Principal.
            await session.refresh(user, attribute_names=["memberships"])
            tenant_roles: dict = {
                m.tenant_id: _coerce_role(m.role) for m in user.memberships
            }

            await session.commit()

            principal = Principal(
                user_id=user.id,
                oidc_sub=user.oidc_sub,
                email=user.email,
                display_name=user.display_name,
                auth_method="oidc",
                tenant_roles=tenant_roles,
                claims=dict(claims),
            )
        return principal

    async def _sync_admin_membership(
        self, session, user: User, groups: set[str]
    ) -> None:
        """Maintain a group-derived admin membership on the default tenant.

        Rules (locked in README.md):

        - For tenants the user has a ``source='manual'`` row on: skip entirely.
        - Otherwise, if ``OIDC_ADMIN_GROUP`` ∈ groups → upsert
          ``source='oidc_group', role='admin'`` on the default tenant.
        - For any existing ``source='oidc_group'`` row whose group no longer
          applies, delete it.
        - Audit every change via ``audit_events``.
        """
        admin_group = Config.OIDC_ADMIN_GROUP
        if not admin_group:
            return  # no admin sync configured

        # Existing memberships, keyed by tenant_id.
        existing = (
            await session.execute(
                select(Membership).where(Membership.user_id == user.id)
            )
        ).scalars().all()
        by_tenant: dict[Any, Membership] = {m.tenant_id: m for m in existing}

        default_tenant = await self._ensure_default_tenant(session)

        # Manual on the default tenant? Manual wins — skip this tenant
        # entirely, and don't create a parallel oidc_group row.
        existing_on_default = by_tenant.get(default_tenant.id)
        manual_on_default = (
            existing_on_default is not None
            and existing_on_default.source == "manual"
        )

        admin_wanted = admin_group in groups
        if admin_wanted and not manual_on_default:
            if existing_on_default is None:
                session.add(
                    Membership(
                        user_id=user.id,
                        tenant_id=default_tenant.id,
                        role="admin",
                        source="oidc_group",
                    )
                )
                _audit(
                    session,
                    user,
                    default_tenant.id,
                    old_role=None,
                    new_role="admin",
                )
            else:
                # Pre-existing oidc_group row. Update role if drifted.
                if existing_on_default.role != "admin":
                    _audit(
                        session,
                        user,
                        default_tenant.id,
                        old_role=existing_on_default.role,
                        new_role="admin",
                    )
                    existing_on_default.role = "admin"
                # No-op if already admin.

        # Remove stale oidc_group rows. Only the default tenant is in scope
        # in v1, so any oidc_group row that ISN'T on default — or that is on
        # default but the user is no longer in the admin group — gets pruned.
        for tenant_id, m in by_tenant.items():
            if m.source != "oidc_group":
                continue
            if tenant_id == default_tenant.id and admin_wanted and not manual_on_default:
                continue  # we just kept/created this one
            _audit(
                session,
                user,
                tenant_id,
                old_role=m.role,
                new_role=None,
            )
            await session.delete(m)

    async def _ensure_default_tenant(self, session) -> Tenant:
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.slug == _DEFAULT_TENANT_SLUG)
            )
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                slug=_DEFAULT_TENANT_SLUG,
                display_name=_DEFAULT_TENANT_DISPLAY_NAME,
            )
            session.add(tenant)
            await session.flush()
        return tenant


def _audit(
    session,
    user: User,
    tenant_id: Any,
    *,
    old_role: str | None,
    new_role: str | None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=user.id,
            actor_kind="system",
            action="membership.synced",
            target_kind="membership",
            target_id=str(user.id),
            tenant_id=tenant_id,
            detail=json.dumps({"old_role": old_role, "new_role": new_role}),
        )
    )


def _first_str(d: dict, keys: list[str]) -> str | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _b64url_decode(value: str) -> bytes:
    import base64

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _coerce_role(value: str) -> Role:
    if value not in ("admin", "member"):
        raise AuthError(f"unexpected membership role: {value!r}")
    return value  # type: ignore[return-value]
