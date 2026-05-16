# 05 — Admin endpoints, CLI, OIDC callback, UI bridge

## Goal

Make Stash actually usable end-to-end with auth on. Add the OIDC login
flow (`/auth/login`, `/auth/callback`), an API-token mint/revoke flow
(`/auth/tokens`), the admin CRUD endpoints (`/admin/*`), the CLI
subcommands for tenant/store provisioning, and the minimal `stash_mcp/ui.py`
change that bounces unauthenticated browser users to the login page.

After this lands, you can: spin up dex, point Stash at it, log in via a
browser, create a tenant and store via CLI, mint an API token, and use it
from an MCP client. All without touching the SPA — that's 06.

## Out of scope

- SPA changes — 06.
- Tool-level scope enforcement (e.g. `read_content` requires `read` scope).
  Add a lightweight version here as part of admin route protection, but
  per-tool MCP enforcement gets its own pass at the very end of this spec.

## Files added

```
stash_mcp/auth/routes.py             # /auth/login, /auth/callback, /auth/tokens
stash_mcp/admin/__init__.py
stash_mcp/admin/routes.py            # /admin/tenants, /admin/stores, /admin/users, /admin/memberships
stash_mcp/admin/dependencies.py      # require_admin() FastAPI dependency
stash_mcp/cli/__init__.py
stash_mcp/cli/__main__.py            # entry: python -m stash_mcp.cli ...
stash_mcp/cli/commands.py            # tenant create, store create, token issue, etc.
stash_mcp/errors.py                  # Problem Details helper, exception registry, FastAPI handlers
tests/admin/__init__.py
tests/admin/test_admin_routes.py
tests/admin/test_oidc_routes.py
tests/admin/test_token_routes.py
tests/admin/test_problem_details.py  # exhaustive coverage of error responses
tests/cli/__init__.py
tests/cli/test_cli_commands.py
```

## Files modified

```
stash_mcp/main.py                    # mount /auth and /admin routers
stash_mcp/ui.py                      # 302 to /auth/login on unauth GET
stash_mcp/mcp_server.py              # add per-tool scope decorator (small)
pyproject.toml                       # add stash-mcp-cli entry point
```

## Design

### Error responses: RFC 7807 Problem Details

All 4xx/5xx responses from the **new** endpoints — `/auth/*`, `/admin/*`,
and the per-store `/api/<tenant>/<store>/*` paths added in 04 — use RFC 7807
Problem Details. Legacy `/api/*` paths (used only in auth-disabled
mode) keep their current `{"detail": "..."}` shape so existing
deployments don't break.

Response shape:

```json
{
  "type": "/problems/content/etag-mismatch",
  "title": "ETag mismatch on conditional write",
  "status": 412,
  "detail": "The file has been modified since you last read it.",
  "instance": "/api/default/content/notes.md",
  "current_etag": "\"a1b2c3...\""
}
```

`Content-Type: application/problem+json`. The `type` is a path-style
identifier (not a real URL) — it identifies the error class. The
`instance` is the request path. Extra fields like `current_etag` are
type-specific.

#### `stash_mcp/errors.py`

```python
from dataclasses import dataclass
from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

@dataclass
class Problem:
    type: str
    title: str
    status: int
    detail: str | None = None
    extras: dict[str, Any] | None = None

class StashError(Exception):
    """Base class for errors that should render as Problem Details.
    Subclasses set a class-level `problem` attribute."""
    problem: Problem

    def __init__(self, detail: str | None = None, **extras: Any):
        self.detail = detail
        self.extras = extras
        super().__init__(detail or self.problem.title)


# --- Registry of standard problems --------------------------------------------

class Unauthenticated(StashError):
    problem = Problem("/problems/auth/unauthenticated", "Authentication required", 401)

class Forbidden(StashError):
    problem = Problem("/problems/auth/forbidden", "Forbidden", 403)

class ScopeRequired(StashError):
    problem = Problem("/problems/auth/scope-required", "Insufficient scope", 403)
    # extras: {"required_scope": "write"}

class ContentNotFound(StashError):
    problem = Problem("/problems/content/not-found", "Content not found", 404)

class ETagMismatch(StashError):
    problem = Problem("/problems/content/etag-mismatch", "ETag mismatch on conditional write", 412)
    # extras: {"current_etag": "\"...\""}

class StoreNotFound(StashError):
    problem = Problem("/problems/store/not-found", "Store not found", 404)

class StoreAlreadyExists(StashError):
    problem = Problem("/problems/store/already-exists", "Store already exists", 409)

class StoreNotProvisioned(StashError):
    problem = Problem("/problems/store/not-provisioned", "Store has DB row but no on-disk repo", 500)

class TenantNotFound(StashError):
    problem = Problem("/problems/tenant/not-found", "Tenant not found", 404)

class ValidationError(StashError):
    problem = Problem("/problems/validation", "Validation failed", 400)
    # extras: {"errors": [...]}


def _to_response(req: Request, err: StashError) -> JSONResponse:
    p = err.problem
    body = {
        "type": p.type,
        "title": p.title,
        "status": p.status,
        "instance": req.url.path,
    }
    if err.detail or p.detail:
        body["detail"] = err.detail or p.detail
    if err.extras:
        body.update(err.extras)
    headers = {}
    if p.status == 401:
        headers["WWW-Authenticate"] = 'Bearer realm="stash"'
    return JSONResponse(body, status_code=p.status, headers=headers,
                        media_type="application/problem+json")


def install_problem_handlers(app: FastAPI) -> None:
    """Register exception handlers on a FastAPI app so any StashError
    raised inside a handler becomes a Problem Details response."""

    @app.exception_handler(StashError)
    async def _stash_error_handler(request: Request, exc: StashError):
        return _to_response(request, exc)
```

`install_problem_handlers(app)` is called in `main.create_app()` after the
app is constructed.

#### Adopting it in handlers

Existing handlers raise `HTTPException(404, "...")` in places — those stay
in legacy mode. New handlers (per-store, auth, admin) raise the typed
errors:

```python
# In a per-store content GET handler
try:
    content = await fs.read_file(path)
except FileNotFoundError:
    raise ContentNotFound(detail=f"No content at {path!r}")
```

The auth middleware in 02 also gets updated to use this: instead of
returning a hand-built `JSONResponse`, it raises `Unauthenticated(...)`
and a top-level Starlette exception handler converts it. (The middleware
runs outside FastAPI's exception-handler stack, so 02's middleware
construction stays — it just imports the Problem helper and uses
`_to_response` directly to render its 401.)

#### Test plan additions

`tests/admin/test_problem_details.py`:
- Every error subclass renders with the right `type`, `title`, `status`,
  `instance`, and Content-Type.
- `extras` flow through to the response body.
- `WWW-Authenticate` header is present on 401s.
- A `StashError` raised inside any `/admin/*` handler becomes Problem
  Details (smoke test by hitting one endpoint).

### `/auth/login` and `/auth/callback`

Uses `authlib.integrations.starlette_client.OAuth` for the redirect dance.
`authlib` handles state+nonce generation and verification, so we don't
reimplement it.

```python
# stash_mcp/auth/routes.py
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request, HTTPException
from starlette.responses import RedirectResponse

from ..config import Config

oauth = OAuth()
oauth.register(
    name="idp",
    server_metadata_url=Config.OIDC_DISCOVERY_URL,
    client_id=Config.OIDC_CLIENT_ID,
    client_secret=Config.OIDC_CLIENT_SECRET,
    client_kwargs={"scope": Config.OIDC_SCOPES},
)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/login")
async def login(request: Request, next: str = "/ui"):
    redirect_uri = str(request.url_for("oidc_callback"))
    request.session["next"] = next
    return await oauth.idp.authorize_redirect(request, redirect_uri)

@router.get("/callback", name="oidc_callback")
async def callback(request: Request):
    token = await oauth.idp.authorize_access_token(request)
    # The id_token is already parsed by authlib into `token['userinfo']`.
    # Pass through the same OIDCAuthProvider machinery: build/refresh user
    # row, refresh memberships from groups claim, issue session cookie.
    claims = token["userinfo"]
    user_id, _ = await upsert_user_and_memberships(claims)  # in oidc_provider
    cookie = issue_session(user_id=str(user_id), oidc_sub=claims["sub"])
    next_path = request.session.pop("next", "/ui")
    resp = RedirectResponse(url=next_path, status_code=302)
    resp.set_cookie(
        Config.SESSION_COOKIE_NAME,
        cookie,
        max_age=Config.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=not _is_local_dev(),
        samesite="lax",
    )
    return resp

@router.post("/logout")
async def logout(request: Request):
    resp = RedirectResponse(url="/ui", status_code=302)
    resp.delete_cookie(Config.SESSION_COOKIE_NAME)
    return resp
```

`request.session` requires Starlette's `SessionMiddleware`. Add it to the
app stack with the same `SESSION_SECRET`. It only carries the `next` URL
between login and callback — actual auth state lives in our signed
cookie.

`upsert_user_and_memberships(claims)` is a helper extracted from
`OIDCAuthProvider` so the bearer-JWT path and the cookie-issuance path
share it. Move it into `stash_mcp/auth/oidc_provider.py` (or a small new
`stash_mcp/auth/users.py`) so both 02's provider and this route call it.

### `/auth/tokens` — API token management

```python
@router.get("/tokens", dependencies=[Depends(require_session)])
async def list_tokens(...): ...

@router.post("/tokens", dependencies=[Depends(require_session)])
async def create_token(name: str, scopes: list[str] = ["read", "write"], expires_in_days: int | None = 90):
    # Generate token via tokens.generate_token(), hash, store, return ONCE
    # in plaintext to the caller. After this response, the secret is gone.
    ...

@router.delete("/tokens/{token_id}", dependencies=[Depends(require_session)])
async def revoke_token(token_id: UUID): ...
```

`require_session` is a FastAPI dependency that asserts
`current_principal()` is set and `auth_method == 'session'` — i.e. the
caller proved identity via the cookie set by `/auth/callback`. Bearer JWT
callers (`auth_method='oidc'`) and API token callers (`auth_method='api_token'`)
both get 403 on token-mint endpoints. This is why spec 02 splits the
auth method enum into three values rather than two: the discrimination is
load-bearing here.

Returned token format on POST:
```json
{"id": "...", "name": "...", "token": "stash_pat_AbC123...", "expires_at": "..."}
```
The `token` field appears ONLY in the POST response. Subsequent GETs
return `{"id": ..., "name": ..., "last_used_at": ...}` without the
secret.

Every successful mint writes `audit_events(action='token.issued',
actor_user_id=<minter>, actor_kind='user', target_kind='token',
target_id=<new token id>, detail={"name": ..., "scopes": [...],
"expires_at": ...})`. Revoke writes `action='token.revoked'`. The
audit row is committed in the same transaction as the token-row
change, so the audit log can't drift from the table state.

### `/admin/*` endpoints

All under `Depends(require_admin)` which checks `principal.has_role_on(<default tenant>, "admin")`. In v1 admin is global (granted on the
default tenant only), so cross-tenant admin checks aren't needed yet.

```
POST   /admin/tenants                  -> create tenant
GET    /admin/tenants                  -> list tenants
GET    /admin/tenants/{id}             -> get tenant
PATCH  /admin/tenants/{id}             -> rename
DELETE /admin/tenants/{id}             -> delete (only if no stores)

POST   /admin/tenants/{id}/stores      -> create store (calls StoreRegistry.provision)
GET    /admin/tenants/{id}/stores      -> list stores
DELETE /admin/tenants/{id}/stores/{slug} -> remove store row + on-disk repo

GET    /admin/users                    -> list users
GET    /admin/users/{id}               -> get user
DELETE /admin/users/{id}               -> delete (cascades memberships, revokes tokens)

POST   /admin/memberships              -> manual grant (source='manual')
DELETE /admin/memberships/{id}         -> revoke manual grant
```

Manual memberships from `/admin/memberships` are the escape hatch for
"this person isn't in the IdP admin group but I want to grant them
tenant access anyway." OIDC-group-derived memberships are managed by the
OIDC login flow and can't be modified through this API (they'd just be
overwritten on the user's next login).

DELETE on a store calls `StoreRegistry.invalidate()` and then removes the
on-disk directory. The on-disk delete is recursive and final — there's
no soft-delete. Document this in the response with a confirmation flag:
`DELETE /admin/tenants/{id}/stores/{slug}?confirm=true`. Without
`confirm=true`, returns 400.

**Audit writes for `/admin/*`:**
| Action | Endpoint |
|---|---|
| `tenant.created` | `POST /admin/tenants` |
| `tenant.deleted` | `DELETE /admin/tenants/{id}` |
| `store.provisioned` | `POST /admin/tenants/{id}/stores` |
| `store.deleted` | `DELETE /admin/tenants/{id}/stores/{slug}` (the row that survives the cascade) |
| `membership.granted` | `POST /admin/memberships` |
| `membership.revoked` | `DELETE /admin/memberships/{id}` |
| `user.deleted` | `DELETE /admin/users/{id}` |

All audit rows carry `actor_user_id=<admin>`, `actor_kind='user'`, and
the `tenant_id` of the affected scope where applicable. Same
"committed in the same transaction" rule as token mint.

### CLI

`pyproject.toml`:
```
[project.scripts]
stash-mcp-cli = "stash_mcp.cli.__main__:main"
```

Commands:
```
stash-mcp-cli tenant create --slug acme --name "Acme Inc"
stash-mcp-cli tenant list
stash-mcp-cli store create --tenant acme --slug docs --remote https://...  # optional remote
stash-mcp-cli store list --tenant acme
stash-mcp-cli user list
stash-mcp-cli membership grant --user-email alice@example.com --tenant acme --role member
```

Uses `click` or `argparse` — either is fine. Reads `STASH_DATABASE_URL`
from env (or `--database-url` flag). All commands run synchronously
against the DB; they're admin tooling, not part of the request path.

The CLI is **not** an alternative way to mint API tokens — those only
come from the `/auth/tokens` endpoint after an OIDC login. The CLI
exists for "the IdP is misconfigured and I need to fix something" and
for tenant/store provisioning automation.

### Minimal `stash_mcp/ui.py` change

The UI middleware (from 02) already redirects unauthenticated GETs to
`/ui` toward `/auth/login`. In 02 that was a no-op because `/auth/login`
didn't exist. Now it does. **No code change to `ui.py` is required for
that path** — it just works once 05 lands.

What `ui.py` *does* need:

1. A "Sign out" link in the header. Single anchor `<a href="/auth/logout">Sign out</a>`.
2. The header shows the logged-in user's display name. Read it from
   `current_principal()` at the top of each handler.
3. If `AUTH_ENABLED` is True and the principal has no store access
   (membership but zero stores in their tenant), render an empty-state
   page that says "No stores yet. Ask an admin to create one." instead
   of 500-ing.

That's the entire `ui.py` change. Total diff probably <50 lines.

### Per-tool scope enforcement (the small one)

In `mcp_server.py`, extend the `_instrumented_tool` decorator to accept a
`required_scope` kwarg. Read tools get `"read"`, write tools get
`"write"`. The decorator checks the principal's effective scopes on the
current store. For an `oidc`-authed principal, scopes derive from the
membership role (`admin`/`member` both grant `read`+`write`; admins
additionally get `admin` scope). For an `api_token` principal, scopes
are the explicit list stored on the token row.

```python
def _instrumented_tool(*deco_args, required_scope: str = "read", **deco_kwargs):
    orig_decorator = _original_mcp_tool(*deco_args, **deco_kwargs)

    def patching_decorator(fn):
        @functools.wraps(fn)
        async def _tracked(*args, **kwargs):
            if Config.AUTH_ENABLED:
                principal = require_principal()
                store = require_store()
                if not _principal_has_scope(principal, store, required_scope):
                    raise AuthError(f"scope '{required_scope}' required")
            # ... existing metrics wrapper ...
        return orig_decorator(_tracked)
    return patching_decorator
```

Existing tool registrations stay the same; default `required_scope='read'`
for read tools, explicit `required_scope='write'` on write ones. Update
the 6–10 write tool registrations to set the right value.

In auth-disabled mode this entire block is skipped, so no behavior
change.

## Test plan

- `tests/admin/test_oidc_routes.py`
  - `/auth/login` → 302 to IdP authorize URL with right params.
  - `/auth/callback` with valid code → 302 to next_path, session cookie
    set. Use a fake IdP fixture from `tests/auth/_fake_idp.py`.
  - User created on first login; memberships refreshed on subsequent login.
- `tests/admin/test_token_routes.py`
  - Cookie-session caller mints a token; secret returned exactly once.
  - API-token caller can't mint a token (403).
  - List tokens excludes the secret.
  - Revoke endpoint clears it and subsequent requests with that token
    are 401.
- `tests/admin/test_admin_routes.py`
  - Non-admin principal → 403 on all `/admin/*`.
  - Tenant CRUD round-trip.
  - Store provisioning calls `StoreRegistry.provision` and creates the
    on-disk repo.
  - Store deletion without `confirm=true` → 400.
  - Manual membership grant → row with `source='manual'`; subsequent
    OIDC login of the same user doesn't remove it.
- `tests/cli/test_cli_commands.py`
  - `tenant create`, `store create`, `membership grant` round-trips
    against an in-memory SQLite.
- Tool scope tests in `tests/auth/test_middleware.py` (extended) or a new
  `tests/test_tool_scopes.py`:
  - `member` role can call read+write tools.
  - `member` role cannot call admin-scoped tools.
  - API token with only `read` scope can't call write tools.

## Acceptance

- End-to-end manual flow works:
  1. Bring up dex via `docker-compose.dev-idp.yml`.
  2. Start Stash with `STASH_AUTH_ENABLED=true` and the dex env profile.
  3. `stash-mcp-cli tenant create --slug default --name Default` (or rely
     on the default tenant auto-create from 02).
  4. `stash-mcp-cli store create --tenant default --slug docs`.
  5. Visit `/ui` in a browser → redirected to dex → log in as alice → land
     on `/ui` with a session cookie.
  6. Mint an API token via the UI's tokens page (or via a curl POST to
     `/auth/tokens` with the session cookie).
  7. Configure an MCP client with `Authorization: Bearer stash_pat_...` and
     `https://host/mcp/<tenant>/<store>/` (e.g. `/mcp/default/docs/`) — tools work.
- `uv run pytest` clean.
- `ruff check stash_mcp` clean.

## Open questions

**Multi-admin-tenant.** Right now `require_admin` checks for admin role on
the default tenant only. If we ever want tenant-scoped admins (e.g.
"admin for tenant acme but not for tenant beta"), we'd add a
`require_admin_on(tenant_id)` dependency variant. v1 just has global
admins on the default tenant, which is sufficient for the dogfood case.

**Logout behavior with IdP.** Our `/auth/logout` clears the cookie but
doesn't sign the user out of the IdP (RP-initiated logout). For dex in
dev that's fine. For real IdPs operators may want it. Easy to add later.

## Notes for the Claude Code session

- `request.session` (used by authlib) needs Starlette's `SessionMiddleware`
  added to the app. Use a separate cookie name from the Stash session
  cookie (e.g. `stash_oauth_state`). This is the well-known authlib +
  FastAPI pattern.
- API-token-scope-check on tool calls reuses the contextvar from 02
  (`current_principal`) and 04 (`current_store`). If either is missing,
  the call fails closed (treat as unauthenticated).
- The CLI is intentionally narrow. Don't add `password set`, `reset
  password`, or anything that implies basic auth — there are no passwords.
- The DELETE-store path is destructive. Make sure the implementation
  actually requires `confirm=true` and that the test exercises both
  paths.
