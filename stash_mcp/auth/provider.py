"""AuthProvider Protocol and AuthError exception."""

from typing import Protocol, runtime_checkable

from starlette.requests import Request

from .principal import Principal


@runtime_checkable
class AuthProvider(Protocol):
    """Authenticates a request. Returns None if this provider can't handle it
    (e.g. wrong scheme on the Authorization header) — the middleware will try
    the next provider. Raises AuthError to actively reject (signals 401)."""

    name: str

    async def authenticate(self, request: Request) -> Principal | None: ...


class AuthError(Exception):
    """Raised when a provider claims a request but rejects it.
    Middleware translates this to 401 with a WWW-Authenticate header."""

    def __init__(self, message: str, *, www_authenticate: str | None = None):
        super().__init__(message)
        self.www_authenticate = www_authenticate
