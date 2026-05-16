"""In-process fake OIDC IdP for unit tests.

Generates one RSA keypair, exposes a ``sign(claims)`` helper, and stitches
together the ``discovery_doc`` + ``jwks`` shapes the provider expects.
Tests inject an :class:`httpx.MockTransport` so the provider's HTTP calls
hit our in-memory router instead of the network.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@dataclass
class FakeIdP:
    issuer: str = "http://fake-idp.local"
    audience: str = "stash-mcp"
    kid: str = "test-key-1"
    # Allow rotating in a fresh kid mid-test.
    keys: dict[str, Any] = field(default_factory=dict)
    public_keys: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.keys:
            self._add_key(self.kid)

    def _add_key(self, kid: str) -> None:
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.keys[kid] = priv_pem
        pub_jwk = JsonWebKey.import_key(pub_pem, {"kty": "RSA"}).as_dict()
        pub_jwk["kid"] = kid
        pub_jwk["alg"] = "RS256"
        pub_jwk["use"] = "sig"
        self.public_keys[kid] = pub_jwk

    def add_key(self, kid: str) -> None:
        self._add_key(kid)

    @property
    def discovery_url(self) -> str:
        return f"{self.issuer}/.well-known/openid-configuration"

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer}/keys"

    def discovery_doc(self) -> dict:
        return {
            "issuer": self.issuer,
            "jwks_uri": self.jwks_url,
            "authorization_endpoint": f"{self.issuer}/auth",
            "token_endpoint": f"{self.issuer}/token",
        }

    def jwks(self) -> dict:
        return {"keys": list(self.public_keys.values())}

    def sign(
        self,
        *,
        sub: str = "alice-sub",
        email: str = "alice@example.test",
        name: str = "Alice",
        groups: list[str] | None = None,
        kid: str | None = None,
        iss: str | None = None,
        aud: str | list[str] | None = None,
        exp_offset: int = 3600,
        nbf_offset: int = 0,
        iat: int | None = None,
        extra_claims: dict | None = None,
    ) -> str:
        kid = kid or self.kid
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": iss if iss is not None else self.issuer,
            "sub": sub,
            "aud": aud if aud is not None else self.audience,
            "exp": now + exp_offset,
            "nbf": now + nbf_offset,
            "iat": iat if iat is not None else now,
            "jti": str(uuid.uuid4()),
            "email": email,
            "name": name,
        }
        if groups is not None:
            claims["groups"] = groups
        if extra_claims:
            claims.update(extra_claims)

        jwt = JsonWebToken(["RS256"])
        token = jwt.encode(
            {"alg": "RS256", "kid": kid}, claims, self.keys[kid]
        )
        return token.decode("ascii") if isinstance(token, bytes) else token

    def build_http_client(self) -> httpx.AsyncClient:
        """Return an ``httpx.AsyncClient`` that routes IdP URLs to this fake."""
        idp = self

        async def _handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == idp.discovery_url:
                return httpx.Response(200, json=idp.discovery_doc())
            if url == idp.jwks_url:
                return httpx.Response(200, json=idp.jwks())
            return httpx.Response(404, content=b"unknown url")

        return httpx.AsyncClient(transport=httpx.MockTransport(_handler))
