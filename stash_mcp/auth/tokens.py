"""HMAC-SHA256 hashing for Stash-issued API tokens."""

import hashlib
import hmac
import secrets

TOKEN_PREFIX = "stash_pat_"
TOKEN_RANDOM_BYTES = 24


def generate_token() -> str:
    """Generate a new opaque API token. Show this to the user once; never log."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def hash_token(token: str, *, key: str) -> str:
    """HMAC-SHA256 of the token using one deployment HMAC key.
    Returns hex digest. Callers use ``hash_with_active_key`` for new tokens
    and ``verify_token`` for existing rows."""
    return hmac.new(key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_with_active_key(token: str, *, keys: list[str]) -> tuple[str, int]:
    """Hash with keys[0]. Returns (hash, key_version=0). Caller persists both."""
    if not keys:
        raise ValueError("AUTH_TOKEN_HMAC_KEYS is empty")
    return hash_token(token, key=keys[0]), 0


def verify_token(
    token: str,
    expected_hash: str,
    *,
    keys: list[str],
    key_version: int,
) -> bool:
    """Constant-time comparison against the key recorded for this row.
    Fails closed if the recorded key has been rotated out of the list."""
    if key_version < 0 or key_version >= len(keys):
        return False
    return hmac.compare_digest(
        hash_token(token, key=keys[key_version]), expected_hash
    )


def looks_like_stash_token(value: str) -> bool:
    """Cheap prefix check so the ApiTokenAuthProvider can skip JWT-shaped values."""
    return value.startswith(TOKEN_PREFIX)
