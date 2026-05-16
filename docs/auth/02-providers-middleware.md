# 02 — Auth providers, middleware, dev IdP

## Goal

Make `Principal` actually populated on every request. This chunk wires three
`AuthProvider` implementations behind a single ASGI middleware, exposes a
`current_principal()` contextvar that downstream code reads, and ships a
`docker-compose.dev-idp.yml` so contributors can run the whole flow offline.

After this lands, every request that hits the FastAPI app either has a valid
`Principal` attached or is rejected with 401 — but no behavior actually
*uses* the principal yet. That wiring happens in 04 (routing) and 05
(authorization on tool calls).

## Out of scope

- Per-store routing and `current_store()` contextvar — that's 04.
- `/auth/login`, `/auth/callback`, `/auth/tokens` endpoints — those land
  in 05.
- Tenant/store CRUD in admin endpoints — also 05.
- Tool-level scope enforcement (read/write/admin checks inside MCP tool
  calls) — 05.
- The `CONTENT_DIR` shape invariant — 03.

## Files added

```
stash_mcp/auth/middleware.py        # ASGI auth middleware
stash_mcp/auth/context.py           # current_principal contextvar + helpers
stash_mcp/auth/oidc_provider.py     # OIDCAuthProvider (JWT bearer via JWKS)
stash_mcp/auth/api_token_provider.py # ApiTokenAuthProvider (stash_pat_*)
stash_mcp/auth/session_provider.py  # SessionCookieAuthProvider (cookie -> session row)
stash_mcp/auth/sessions.py          # Session cookie signing / verification helpers
docker-compose.dev-idp.yml          # dex with preseeded user
.dev/dex-config.yaml                # dex static config + connector
tests/auth/test_middleware.py
tests/auth/test_oidc_provider.py
tests/auth/test_api_token_provider.py
tests/auth/test_session_provider.py
tests/auth/_fake_idp.py             # fake JWT signer (RS256) for tests
```

## Files modified

```
stash_mcp/config.py                 # add OIDC + AUTH_ENABLED + cookie config
stash_mcp/main.py                   # mount middleware before /mcp and /api
pyproject.toml                      # add itsdangerous (cookie signing)
README.md                           # add a small "Running with auth" pointer
```

`itsdangerous` is preferred over rolling cookie signing by hand. `authlib`
already brings most of what JWT validation needs.

## Design

### Config additions (`stash_mcp/config.py`)

```python
# Auth toggle. When False, the middleware does nothing and existing behavior
# is preserved. When True, the middleware enforces auth on every request and
# the AUTH_TOKEN_HMAC_KEY + OIDC_* and SESSION_SECRET vars must be set.
AUTH_ENABLED: bool = os.getenv("STASH_AUTH_ENABLED", "false").lower() == "true"

# OIDC config.  Discovery URL is the only required entry — everything else
# (authorize/token/jwks/userinfo URLs) is read from the well-known doc.
OIDC_DISCOVERY_URL: str | None = os.getenv("STASH_OIDC_DISCOVERY_URL")
OIDC_CLIENT_ID: str | None = os.getenv("STASH_OIDC_CLIENT_ID")
OIDC_CLIENT_SECRET: str | None = os.getenv("STASH_OIDC_CLIENT_SECRET")
OIDC_AUDIENCE: str | None = os.getenv("STASH_OIDC_AUDIENCE")  # optional; defaults to CLIENT_ID
OIDC_SCOPES: str = os.getenv("STASH_OIDC_SCOPES", "openid profile email groups")

# Group claim mapping (locked in design doc).
OIDC_GROUPS_CLAIM: str = os.getenv("STASH_OIDC_GROUPS_CLAIM", "groups")
OIDC_ADMIN_GROUP: str | None = os.getenv("STASH_OIDC_ADMIN_GROUP")

# Session cookies (browser UI). The secret signs cookies; rotating it
# invalidates every active session. Cookie is httpOnly, Secure, SameSite=Lax.
SESSION_SECRET: str | None = os.getenv("STASH_SESSION_SECRET")
SESSION_COOKIE_NAME: str = os.getenv("STASH_SESSION_COOKIE_NAME", "stash_session")
SESSION_MAX_AGE_SECONDS: int = int(os.getenv("STASH_SESSION_MAX_AGE", "43200"))  # 12h
```

Add a `validate_auth_config()` classmethod that runs only when
`AUTH_ENABLED` is True. It raises `SystemExit(1)` with a clear message if
any of `DATABASE_URL`, `AUTH_TOKEN_HMAC_KEY`, `OIDC_DISCOVERY_URL`,
`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `SESSION_SECRET`, or
`OIDC_ADMIN_GROUP` is unset. Call it from `main.create_app()` after env is
loaded.

### `stash_mcp/auth/context.py`

```python
from contextvars import ContextVar, Token
from .principal import Principal

_current_principal: ContextVar[Principal | None] = ContextVar(
    "stash_principal", default=None
)

def set_current_principal(p: Principal | None) -> Token:
    """Set the contextvar and return a Token. Caller MUST pass that Token to
    reset_current_principal() in a finally block — using .reset() (not .set(None))
    properly restores the prior value, which matters for nested contexts and
    asyncio task groups."""
    return _current_principal.set(p)

def reset_current_principal(token: Token) -> None:
    _current_principal.reset(token)

def current_principal() -> Principal | None:
    """Return the principal for the in-flight request, or None if
    AUTH_ENABLED=False (in which case no checks should be performed)."""
    return _current_principal.get()

def require_principal() -> Principal:
    """Raise AuthError if no principal — for code that should never run
    without auth (e.g. authenticated tool handlers)."""
    p = _current_principal.get()
    if p is None:
        from .provider import AuthError
        raise AuthError("authentication required")
    return p
```

### `stash_mcp/auth/middleware.py`

A Starlette ASGI middleware (not a FastAPI `@app.middleware("http")`
decorator) because it sits in front of both the `/api` FastAPI app and the
`/mcp` FastMCP subapp, which are mounted at the root. Wire it via
`app.add_middleware(StashAuthMiddleware, ...)` in `main.create_app()`.

```python
from collections.abc import Awaitable, Callable
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import Config
from .context import set_current_principal
from .principal import Principal
from .provider import AuthError, AuthProvider

# Paths that are always public (no auth attempt, no rejection).
# Health is open so liveness probes work without credentials. The auth
# endpoints themselves don't require an existing session.
_PUBLIC_PATHS = (
    "/api/health",
    "/auth/login",
    "/auth/callback",
    "/static/",
)

# Paths that are always public for GET (UI assets, login page). The UI
# itself is gated, but the static assets it loads are not.
class StashAuthMiddleware:
    def __init__(self, app: ASGIApp, providers: list[AuthProvider]):
        self.app = app
        self.providers = providers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not Config.AUTH_ENABLED:
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if any(path == p or path.startswith(p) for p in _PUBLIC_PATHS):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        principal: Principal | None = None
        last_err: AuthError | None = None
        for provider in self.providers:
            try:
                principal = await provider.authenticate(request)
            except AuthError as exc:
                last_err = exc
                break  # active rejection — don't try further providers
            if principal is not None:
                break

        if principal is None:
            # Browser path: send them to the login page if they're a GET on /ui
            if scope["method"] == "GET" and path.startswith("/ui"):
                from urllib.parse import quote
                redirect = f"/auth/login?next={quote(path)}"
                resp = Response(status_code=302, headers={"Location": redirect})
                await resp(scope, receive, send)
                return
            # API/MCP path: 401 with WWW-Authenticate
            www_auth = (
                last_err.www_authenticate
                if (last_err and last_err.www_authenticate)
                else 'Bearer realm="stash"'
            )
            resp = JSONResponse(
                {"error": "unauthenticated"},
                status_code=401,
                headers={"WWW-Authenticate": www_auth},
            )
            await resp(scope, receive, send)
            return

        token = set_current_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_principal(token)
```

Provider order matters: `[SessionCookieAuthProvider, ApiTokenAuthProvider,
OIDCAuthProvider]`. Cookies are cheapest to check; API tokens are next;
JWT validation is the most expensive (JWKS fetch + crypto). The middleware
short-circuits on the first success.

### `stash_mcp/auth/oidc_provider.py`

Uses `authlib.jose.JsonWebToken` for JWT decoding and `authlib.jose.JsonWebKey`
for JWKS. The discovery doc is fetched once at startup and cached; JWKS keys
are fetched on demand and cached by `kid`, with a refresh on unknown `kid`
(handles key rotation).

Key responsibilities:

- Read `Authorization: Bearer <token>` header. If absent, return None.
- If the token starts with `stash_pat_`, return None (let ApiTokenAuthProvider
  handle it).
- Decode the JWT header to get `kid`. Look up the public key from JWKS cache;
  refetch JWKS if `kid` unknown.
- Validate signature, `iss` (matches discovery `issuer`), `aud` (matches
  `OIDC_AUDIENCE` or `OIDC_CLIENT_ID`), `exp`, `nbf`, `iat`.
- Extract claims. Read `sub`, `email`, `name` (or `preferred_username` as
  fallback). Read the configured `OIDC_GROUPS_CLAIM` from claims.
- Upsert `users` row by `oidc_sub`. Update `last_login_at`.
- Refresh `memberships` for this user from the groups claim:
  - If `OIDC_ADMIN_GROUP` is in the user's groups, upsert a
    `memberships(user_id, tenant_id=<default tenant>, role='admin',
    source='oidc_group')` row.
  - For groups not matching, delete any `memberships(source='oidc_group')`
    rows that no longer apply. Don't touch `source='manual'` rows.
  - v1 only mints admin memberships from groups. Non-admin tenant
    memberships come via the admin API in 05.
- Build and return `Principal`.

A "default tenant" is auto-created if it doesn't exist — slug `default`,
display_name `Default tenant`. This is the tenant that admin memberships
land on by default. Operators can rename it via the admin API but its slug
stays `default` (referenced from code).

Cache the JWKS in-process. Use `httpx.AsyncClient` (already a transitive
dep via authlib). 60-second negative cache for failed JWKS fetches to avoid
hammering the IdP under failure.

### `stash_mcp/auth/api_token_provider.py`

```python
from .principal import Principal
from .provider import AuthError, AuthProvider
from .tokens import hash_token, looks_like_stash_token

class ApiTokenAuthProvider:
    name = "api_token"

    async def authenticate(self, request) -> Principal | None:
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        if not looks_like_stash_token(token):
            return None  # let OIDC provider try

        # Look up by HMAC hash. Reject if expired or revoked. Update last_used_at.
        # On success, load the user and their memberships, build Principal with
        # auth_method='api_token'. claims dict carries token name + scopes.
        ...
```

Implementation reads `Config.AUTH_TOKEN_HMAC_KEY` (validated non-None when
auth is on). Open a short-lived AsyncSession from `db.session.get_sessionmaker()`
inside the provider — don't depend on FastAPI's `Depends` since the
middleware runs outside the FastAPI request lifecycle.

### `stash_mcp/auth/sessions.py`

Session cookie payload format: `itsdangerous.URLSafeTimedSerializer` with
`SESSION_SECRET`. Payload is a small JSON dict: `{"uid": "<user_id>",
"sub": "<oidc_sub>"}`. Max age enforced by serializer.

```python
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from ..config import Config

def _serializer() -> URLSafeTimedSerializer:
    if Config.SESSION_SECRET is None:
        raise RuntimeError("SESSION_SECRET unset — validate_auth_config should have caught this")
    return URLSafeTimedSerializer(Config.SESSION_SECRET, salt="stash-session-v1")

def issue_session(user_id: str, oidc_sub: str) -> str:
    return _serializer().dumps({"uid": user_id, "sub": oidc_sub})

def verify_session(cookie: str) -> dict | None:
    try:
        return _serializer().loads(cookie, max_age=Config.SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
```

Salt is versioned (`stash-session-v1`) so we can rotate cookie format later
by bumping it without changing the env-var name.

### `stash_mcp/auth/session_provider.py`

```python
class SessionCookieAuthProvider:
    name = "session_cookie"

    async def authenticate(self, request):
        cookie = request.cookies.get(Config.SESSION_COOKIE_NAME)
        if not cookie:
            return None
        payload = verify_session(cookie)
        if payload is None:
            return None  # expired/tampered — middleware will continue to next provider
        # Load user by uid, build Principal with auth_method='session'. The
        # split between 'session' (cookie path) and 'oidc' (bearer JWT) matters
        # for /auth/tokens — only cookie-session callers can mint API tokens.
        # Bearer-JWT callers shouldn't, even though both prove OIDC identity.
        ...
```

### `docker-compose.dev-idp.yml` and `.dev/dex-config.yaml`

dex pinned to `ghcr.io/dexidp/dex:v2.41.1` (or latest stable at impl time).
One static client `stash-mcp` with secret `dev-secret-do-not-use-in-prod`,
redirect URIs `http://localhost:8000/auth/callback`. Static-password
connector with one user, `alice@example.test` / `password`, member of group
`stash-admins`.

Compose file binds dex on `:5556` and `:5557` (web + gRPC). README and 06
will document running `docker compose -f docker-compose.dev-idp.yml up` and
the corresponding `STASH_OIDC_DISCOVERY_URL=http://localhost:5556/dex/.well-known/openid-configuration`.

### Wiring in `main.py`

```python
from .auth.middleware import StashAuthMiddleware
from .auth.oidc_provider import OIDCAuthProvider
from .auth.api_token_provider import ApiTokenAuthProvider
from .auth.session_provider import SessionCookieAuthProvider

def create_app():
    if Config.AUTH_ENABLED:
        Config.validate_auth_config()

    # ... existing setup ...

    if Config.AUTH_ENABLED:
        providers = [
            SessionCookieAuthProvider(),
            ApiTokenAuthProvider(),
            OIDCAuthProvider(),  # init kicks off JWKS prefetch
        ]
        app.add_middleware(StashAuthMiddleware, providers=providers)
```

`add_middleware` adds the middleware to FastAPI's stack, which wraps around
mounted subapps. The order is intentional — auth runs before the existing
`/mcp` slash-normalizer and before the CORS middleware (which is fine; CORS
preflight requests on OPTIONS are handled by Starlette before middleware
sees them).

## Test plan

- `tests/auth/_fake_idp.py`: generates an RSA keypair, exposes a `sign(claims)`
  helper and a JWKS dict, plus a `discovery_doc` dict that points at an
  in-process URL.
- `tests/auth/test_oidc_provider.py`
  - Valid JWT → Principal with right user_id, sub, email, tenant_roles.
  - User in admin group → `tenant_roles[default]=='admin'`.
  - User not in admin group → `tenant_roles` empty (no memberships).
  - Tampered signature → AuthError.
  - Expired token → AuthError.
  - Wrong audience → AuthError.
  - Unknown `kid` triggers JWKS refresh; second call succeeds.
  - Membership refresh: pre-existing `oidc_group` membership for a removed
    group is deleted; `manual` membership for the same tenant is preserved.
- `tests/auth/test_api_token_provider.py`
  - Valid token → Principal with `auth_method='api_token'`.
  - Revoked token → AuthError.
  - Expired token → AuthError.
  - Wrong HMAC key (simulating key rotation gone wrong) → returns None.
  - Non-stash prefix → returns None (no AuthError).
- `tests/auth/test_session_provider.py`
  - Cookie roundtrip → same user.
  - Tampered cookie → None.
  - Expired cookie → None.
- `tests/auth/test_middleware.py`
  - AUTH_ENABLED=false → middleware no-ops, no Principal set.
  - No credentials, /api → 401.
  - No credentials, GET /ui → 302 to /auth/login.
  - Valid token on /api → 200, principal set in contextvar.
  - Public path /api/health → 200 without auth.
  - First provider returns None, second succeeds → second's Principal wins.
  - First provider raises AuthError → 401 with that provider's
    WWW-Authenticate, no further providers tried.

## Acceptance

- `STASH_AUTH_ENABLED=true` with proper env vars: unauthenticated requests
  to `/api/*` get 401, GETs to `/ui` get 302 → `/auth/login`. (The
  `/auth/login` endpoint itself returns 404 in this chunk — that's 05's
  job.)
- `STASH_AUTH_ENABLED=false`: behavior unchanged. All existing tests pass.
- `docker compose -f docker-compose.dev-idp.yml up` brings up a healthy dex.
- `uv run pytest tests/auth` passes.

## Open questions

None blocking. One forward-looking decision: do we want a "service account"
concept for non-human callers (CI, cron jobs)? Easy to add later as a flag
on `users` or as a separate `service_accounts` table. Not in v1.

## Notes for the Claude Code session

- Don't refactor the existing `_metrics_middleware`. Auth middleware sits in
  front of it; metrics still record every request whether authenticated or
  not.
- `SessionCookieAuthProvider` sets `auth_method='session'`,
  `OIDCAuthProvider` (bearer JWT) sets `auth_method='oidc'`,
  `ApiTokenAuthProvider` sets `auth_method='api_token'`. The discrimination
  matters in spec 05's `require_session` — only cookie-authed callers can
  mint new API tokens.
- The default tenant is created lazily on the first OIDC login that grants
  admin. Don't add a migration that pre-seeds it — it's auto-provisioned in
  the OIDC provider code.
- Don't add `/auth/*` route handlers in this chunk. The middleware allowlists
  those paths so they don't 401, but the routes themselves come in 05.
