"""Auth value objects and provider protocol.

This package holds the typed surface for authentication — the `Principal`
value object, the `AuthProvider` Protocol, and HMAC-SHA256 helpers for
API token hashing. Concrete providers (OIDC, API token, session cookie)
and the ASGI middleware live alongside in later auth specs; this module
is import-safe and does not touch the network or the database.
"""

from .principal import AuthMethod, Principal, Role
from .provider import AuthError, AuthProvider
from .tokens import (
    TOKEN_PREFIX,
    generate_token,
    hash_token,
    hash_with_active_key,
    looks_like_stash_token,
    verify_token,
)

__all__ = [
    "AuthError",
    "AuthMethod",
    "AuthProvider",
    "Principal",
    "Role",
    "TOKEN_PREFIX",
    "generate_token",
    "hash_token",
    "hash_with_active_key",
    "looks_like_stash_token",
    "verify_token",
]
