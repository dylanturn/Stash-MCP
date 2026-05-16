"""Signed session cookie helpers.

The cookie payload is a small JSON dict ``{"uid": <user_id>, "sub": <oidc_sub>}``
signed with ``itsdangerous.URLSafeTimedSerializer``. The salt is versioned so
we can rotate cookie formats later without changing the env-var name.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import Config

_SALT = "stash-session-v1"


def _serializer() -> URLSafeTimedSerializer:
    if Config.SESSION_SECRET is None:
        raise RuntimeError(
            "SESSION_SECRET unset — validate_auth_config should have caught this"
        )
    return URLSafeTimedSerializer(Config.SESSION_SECRET, salt=_SALT)


def issue_session(user_id: str, oidc_sub: str) -> str:
    """Sign and return a new session cookie value."""
    return _serializer().dumps({"uid": user_id, "sub": oidc_sub})


def verify_session(cookie: str) -> dict | None:
    """Return the payload if the cookie is valid and unexpired, else ``None``."""
    try:
        payload = _serializer().loads(
            cookie, max_age=Config.SESSION_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    return payload
