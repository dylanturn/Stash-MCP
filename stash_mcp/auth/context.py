"""ContextVar plumbing for the in-flight ``Principal``.

The middleware sets the principal at the top of the request and resets it in
a ``finally`` block. Downstream code (tool handlers, route handlers) reads it
via :func:`current_principal` / :func:`require_principal`.
"""

from contextvars import ContextVar, Token

from .principal import Principal

_current_principal: ContextVar[Principal | None] = ContextVar(
    "stash_principal", default=None
)


def set_current_principal(p: Principal | None) -> Token:
    """Set the contextvar and return a ``Token``.

    Caller MUST pass the returned token to :func:`reset_current_principal`
    in a ``finally`` block — using ``.reset()`` (not ``.set(None)``) properly
    restores the prior value, which matters for nested contexts and asyncio
    task groups.
    """
    return _current_principal.set(p)


def reset_current_principal(token: Token) -> None:
    _current_principal.reset(token)


def current_principal() -> Principal | None:
    """Return the principal for the in-flight request, or ``None`` if
    ``AUTH_ENABLED=False`` (in which case no checks should be performed)."""
    return _current_principal.get()


def require_principal() -> Principal:
    """Raise ``AuthError`` if no principal — for code that should never run
    without auth (e.g. authenticated tool handlers)."""
    p = _current_principal.get()
    if p is None:
        from .provider import AuthError

        raise AuthError("authentication required")
    return p
