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
from typing import Any

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from starlette.requests import Request

from ..config import Config
from ..db.session import get_sessionmaker
from .principal import Principal, Role
from .provider import AuthError, AuthProvider
from .tokens import looks_like_stash_token
from .users import upsert_user_and_memberships

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
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            user = await upsert_user_and_memberships(session, claims)
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


def _b64url_decode(value: str) -> bytes:
    import base64

    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _coerce_role(value: str) -> Role:
    if value not in ("admin", "member"):
        raise AuthError(f"unexpected membership role: {value!r}")
    return value  # type: ignore[return-value]
