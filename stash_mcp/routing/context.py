"""ContextVar plumbing for the in-flight ``LoadedStore``.

Mirrors the ``current_principal`` pattern from spec 02. The
:class:`StoreResolverMiddleware` sets the store at the top of the
request and resets it in a ``finally`` block. Downstream code (REST
handlers, MCP tool bodies, the UI) reads it via :func:`current_store` /
:func:`require_store`.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from ..stores.registry import LoadedStore

_current_store: ContextVar[LoadedStore | None] = ContextVar(
    "stash_current_store", default=None
)


def set_current_store(s: LoadedStore | None) -> Token:
    """Set the contextvar and return a ``Token``.

    Caller MUST pass the returned token to :func:`reset_current_store` in
    a ``finally`` block — using ``.reset()`` (not ``.set(None)``) properly
    restores the prior value, which matters for nested contexts and asyncio
    task groups.
    """
    return _current_store.set(s)


def reset_current_store(token: Token) -> None:
    _current_store.reset(token)


def current_store() -> LoadedStore | None:
    """Return the store for the in-flight request, or ``None`` if no
    resolver has run (e.g. ``AUTH_ENABLED=False``)."""
    return _current_store.get()


def require_store() -> LoadedStore:
    """Return the in-flight store or raise ``RuntimeError``.

    Programmer-error sentinel: by the time a handler runs the resolver
    should already have set this. Not a 401/403.
    """
    s = _current_store.get()
    if s is None:
        raise RuntimeError(
            "no store in scope — route was reached without resolver"
        )
    return s
