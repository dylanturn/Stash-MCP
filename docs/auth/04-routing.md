# 04 — Per-store HTTP routing

## Goal

Move `/api/*` to `/api/<tenant>/<store>/*` and `/mcp` to
`/mcp/<tenant>/<store>/` when `AUTH_ENABLED=True`. **Both tenant and store
slugs are on the wire** — inferring tenant from the principal breaks the
moment a user has memberships on more than one tenant (which 05's manual
membership API explicitly allows). A `current_store()` contextvar exposes
the resolved `LoadedStore` to tools and route handlers, mirroring the
`current_principal()` pattern from 02.

After this lands, an authenticated client can call MCP tools and REST
endpoints against a specific store, and the existing `FileSystem`/git
machinery operates on that store's repo. Authz on individual tool calls
(checking `read`/`write`/`admin` scopes) and the `/admin/*` endpoints are
still 05.

## Out of scope

- `/auth/*` endpoints (login, callback, tokens) — 05.
- `/admin/*` endpoints (tenant/store/user CRUD) — 05.
- Tool-level scope enforcement — 05.
- UI redirects to a store-picker page — the UI still works against a
  single default store in this chunk. SPA picker wiring is 06.

## Files added

```
stash_mcp/routing/__init__.py
stash_mcp/routing/store_resolver.py    # middleware that resolves <store>
                                       # from the path and sets contextvar
stash_mcp/routing/context.py           # current_store() contextvar
tests/routing/__init__.py
tests/routing/test_store_resolver.py
tests/routing/test_per_store_api.py
tests/routing/test_per_store_mcp.py
```

## Files modified

```
stash_mcp/main.py            # mount /api/<tenant>/<store> and /mcp/<tenant>/<store>, register resolver
stash_mcp/api.py             # signature changes: factory takes registry, not filesystem;
                             # handlers read FS from current_store(); add ETag + 304/412 paths
stash_mcp/mcp_server.py      # FS access inside tool bodies switches to current_store().fs_for_mcp
stash_mcp/filesystem.py      # add content_hash(path) for non-git stores (SHA-256)
stash_mcp/git_backend.py     # add hash_object(path) for git-tracked stores
stash_mcp/ui.py              # path prefix stays /ui (no per-store URLs in this chunk;
                             # ui picks the principal's first store implicitly)
```

All error responses on `/api/<tenant>/<store>/*` paths use RFC 7807 Problem Details
shape from spec 05. The handler functions don't change their return
types — they raise from a small set of exception types (`ContentNotFound`,
`ETagMismatch`, `Unauthorized`, etc.) that an exception handler in 05
converts to the right Problem Details body.

## Design

### URL shapes

| Surface | AUTH_ENABLED=False | AUTH_ENABLED=True |
|---|---|---|
| REST | `/api/*` | `/api/{tenant}/{store}/*` |
| MCP | `/mcp` | `/mcp/{tenant}/{store}/` |
| UI | `/ui/*` | `/ui/{tenant}/{store}/*` |
| Health | `/api/health` | `/api/health` (no tenant, no auth) |
| Auth | n/a | `/auth/*` (no tenant, public — 05) |
| Admin | n/a | `/admin/*` (no tenant — 05) |

Both slugs are alphanumeric + hyphen, matching the schema constraint in
01. The resolver rejects malformed slugs with 404 before any DB lookup.

**Why tenant in the URL.** Inferring tenant from the principal works for
the v1 single-tenant-per-user case, but breaks the moment a user joins a
second tenant (via the manual-membership API in 05). The
`principal.tenant_roles` dict has no stable "primary" — `next(iter(...))`
gives insertion-order, which depends on the order the OIDC provider
emitted groups and isn't guaranteed across logins. Putting the tenant on
the wire eliminates the ambiguity at the cost of two extra URL segments.

### `stash_mcp/routing/context.py`

```python
from contextvars import ContextVar, Token
from ..stores.registry import LoadedStore

_current_store: ContextVar[LoadedStore | None] = ContextVar(
    "stash_current_store", default=None
)

def set_current_store(s: LoadedStore | None) -> Token:
    """Same Token-reset pattern as set_current_principal — caller MUST pass
    the returned Token to reset_current_store() in a finally block."""
    return _current_store.set(s)

def reset_current_store(token: Token) -> None:
    _current_store.reset(token)

def current_store() -> LoadedStore | None:
    return _current_store.get()

def require_store() -> LoadedStore:
    s = _current_store.get()
    if s is None:
        raise RuntimeError("no store in scope — route was reached without resolver")
    return s
```

`require_store()` is a programmer-error sentinel, not a 401/403 — by the
time a handler runs, the resolver should already have set this.

### Store resolver middleware (`stash_mcp/routing/store_resolver.py`)

Sits *after* `StashAuthMiddleware` in the stack so it can read
`current_principal()`. Responsibilities:

1. Match path against `/api/{tenant}/{store}/` or `/mcp/{tenant}/{store}/`.
   Skip if not one of those.
2. Extract `<tenant>` and `<store>`. Validate both slug shapes (regex
   `^[a-z0-9][a-z0-9-]{0,62}$`) — 404 on malformed.
3. Call `StoreRegistry.get(tenant_slug, store_slug)`. The registry
   resolves the tenant slug → tenant_id internally. On `KeyError` (either
   tenant or store not found) → 404. On `StoreNotProvisionedError` →
   500.
4. Check `principal.has_role_on(loaded.tenant_id, "member")` → 403 if
   the principal isn't a member of the URL's tenant. This is the
   authorization gate — having a row in `memberships` for *some* tenant
   doesn't grant access to *another* tenant.
5. Set `current_store(LoadedStore)`.
6. Rewrite the path: strip `/{tenant}/{store}` from the scope path so the
   mounted `/api` or `/mcp` subapp sees the same routes it always has.
   This keeps `api.py` route definitions untouched — they're still
   `@app.get("/content")` not `@app.get("/{tenant}/{store}/content")`.

The path-rewrite is the same trick `_MCPSlashMiddleware` already uses for
`/mcp` → `/mcp/`. Implementation:

```python
from starlette.types import ASGIApp, Receive, Scope, Send
import re

_SLUG = r"[a-z0-9][a-z0-9-]{0,62}"
_API_RE = re.compile(rf"^/api/(?P<tenant>{_SLUG})/(?P<store>{_SLUG})(?P<rest>/.*)?$")
_MCP_RE = re.compile(rf"^/mcp/(?P<tenant>{_SLUG})/(?P<store>{_SLUG})(?P<rest>/.*)?$")

class StoreResolverMiddleware:
    def __init__(self, app: ASGIApp, registry, public_prefixes: tuple[str, ...]):
        self.app = app
        self.registry = registry
        self.public_prefixes = public_prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        # Pass-through for paths that don't carry a tenant+store
        if any(path.startswith(p) for p in self.public_prefixes):
            await self.app(scope, receive, send)
            return

        m = _API_RE.match(path) or _MCP_RE.match(path)
        if m is None:
            # /api or /mcp without proper tenant+store → 404
            if path.startswith("/api/") or path == "/api" or path.startswith("/mcp/") or path == "/mcp":
                # ...send 404...
                return
            await self.app(scope, receive, send)
            return

        principal = current_principal()
        if principal is None:
            # Defensive 401 — auth middleware should have rejected first
            return

        tenant_slug = m.group("tenant")
        store_slug = m.group("store")
        try:
            loaded = await self.registry.get(tenant_slug, store_slug)
        except KeyError:
            # 404 — tenant or store not found
            return
        if not principal.has_role_on(loaded.tenant_id, "member"):
            # 403 — principal not a member of the URL's tenant.
            # Don't leak whether the store exists; 403 is the right code
            # because the URL is well-formed and resolved to a real store.
            return

        # Rewrite the path so the subapp sees /api/<rest> or /mcp/<rest>
        prefix = "/api" if path.startswith("/api/") else "/mcp"
        rest = m.group("rest") or "/"
        new_scope = dict(scope)
        new_scope["path"] = prefix + rest
        new_scope["raw_path"] = new_scope["path"].encode("utf-8")

        token = set_current_store(loaded)
        try:
            await self.app(new_scope, receive, send)
        finally:
            reset_current_store(token)
```

(Sketched — Claude Code session fills in the 404/401/403 response
constructors, which are JSONResponse for `/api` and the MCP error shape
for `/mcp`.)

### `api.py` signature change

The current factory:

```python
def create_api(filesystem, lifespan=None, search_engine=None, git_backend=None, ...) -> FastAPI:
```

becomes:

```python
def create_api(
    filesystem_or_resolver,    # accepts either a FileSystem (legacy mode) or a callable that
                               # returns the current LoadedStore (auth mode)
    lifespan=None,
    search_engine=None,
    ...
) -> FastAPI:
```

Inside handlers, replace direct `filesystem.read_file(...)` with a small
helper `_fs(request) -> FileSystem` that returns the legacy FS in
auth-disabled mode or `current_store().fs_for_mcp` in auth mode.

The legacy mode keeps passing a `FileSystem`. The auth mode passes a
sentinel (`USE_CURRENT_STORE`) and the helper consults the contextvar.
This keeps the factory backward-compatible and avoids two parallel route
trees.

```python
USE_CURRENT_STORE = object()  # sentinel

def _fs(filesystem_or_resolver):
    if filesystem_or_resolver is USE_CURRENT_STORE:
        from .routing.context import require_store
        return require_store().fs_for_mcp
    return filesystem_or_resolver
```

Each existing handler that closes over `filesystem` from the factory
scope changes to call `_fs(filesystem_or_resolver)` at the top of the
handler instead.

### `mcp_server.py` tool changes

Same pattern. `create_mcp_server(filesystem_or_resolver, ...)`. Inside
each tool body, the call `await filesystem.read_file(path)` becomes
`await _fs(filesystem_or_resolver).read_file(path)`.

The existing `_instrumented_tool` wrapper from lines 211–247 doesn't
need to change. Per-store routing is purely about which FS each call
operates on; the metrics/instrumentation pipeline is unchanged.

### Wiring in `main.create_app()`

```python
def create_app():
    validate_content_layout()
    if Config.AUTH_ENABLED:
        Config.validate_auth_config()

    if Config.AUTH_ENABLED:
        # Auth mode: handlers read FS from current_store() at request time.
        from .api import USE_CURRENT_STORE
        registry = get_store_registry()
        mcp = create_mcp_server(USE_CURRENT_STORE, ...)
        mcp_http_app = mcp.http_app(path="/", stateless_http=Config.READ_ONLY)
        app = create_api(USE_CURRENT_STORE, lifespan=..., search_engine=None)
        # Search is disabled in auth mode for v1 — confirmed in spec 03.
        ui_router = create_ui_router(...)  # ui still uses a single FS; see Notes
        app.include_router(ui_router)
        app.mount("/mcp", mcp_http_app)  # store will be rewritten in by middleware

        app.add_middleware(StoreResolverMiddleware, registry=registry,
                           public_prefixes=("/api/health", "/auth", "/admin",
                                            "/ui", "/static", "/docs", "/openapi.json"))
        app.add_middleware(StashAuthMiddleware, providers=...)
    else:
        # legacy path — unchanged
        ...
```

Middleware order matters: `add_middleware` adds **outermost first** in
FastAPI, so the actual execution order is *last-added-runs-first*. We
want auth → store resolver → app. That means add store resolver first,
then auth.

### Note on the FastMCP mount

FastMCP is mounted at `/mcp` (no store). The store resolver rewrites the
path so the FastMCP subapp sees `/mcp/<rest>` exactly as before. The
slug is consumed by the middleware and goes nowhere near FastMCP. This
means we can keep `mcp.http_app(path="/")` as-is.

### Note on the UI

In this chunk, the UI doesn't render per-store URLs. It implicitly uses
the principal's first accessible store (default tenant's default store
in v1, since there's exactly one until admin endpoints in 05 let people
create more). The UI factory in `ui.py` gets the same
`USE_CURRENT_STORE` sentinel treatment — but it resolves the store at
the top of each handler by reading the principal's tenant + a "default
store" that's whichever store the principal has access to with the
lowest `created_at`. Crude but adequate until the SPA picker lands in 06.

## ETag + conditional requests

The per-store content endpoints get HTTP conditional-request support. This
is a free win for the SPA's read-heavy DocumentsPage (304 means no body)
and gives the editor optimistic concurrency control on writes (412 on
stale `If-Match`).

### Computing the ETag

For a content read at `<store>/<path>`:

- **Git-tracked store:** the ETag is the git blob SHA — already computed,
  free to read. `GitBackend` gains a `hash_object(path: str) -> str` method
  that runs `git hash-object <path>` (or reads it from the index for cached
  paths).
- **Non-git-tracked store:** the ETag is SHA-256 of the file bytes,
  computed on read. `FileSystem` gains a `content_hash(path: str) -> str`
  method.

Format: strong ETag, quoted hex. Example: `ETag: "a1b2c3..."`. No `W/`
prefix.

Tree, list, search, health endpoints — no ETag. The aggregated
representations make ETag-ing them more trouble than the savings.

### Read flow: `GET /api/<tenant>/<store>/content/<path>`

1. Resolve the file via current_store().
2. Compute the ETag.
3. If `If-None-Match` header matches → return `304 Not Modified` with no
   body and the same `ETag` header.
4. Otherwise return `200 OK` with the file bytes/JSON and the `ETag`
   header.

### Write flow: `PUT /api/<tenant>/<store>/content/<path>`

If the request carries `If-Match`:

- File doesn't exist yet → If-Match doesn't match anything → `412
  Precondition Failed`.
- File exists, current ETag matches → proceed with write, return `200 OK`
  with the new ETag.
- File exists, current ETag differs → `412 Precondition Failed` with the
  current ETag in the response (Problem Details body — see 05's error
  section, type `/problems/content/etag-mismatch`).

If the request has no `If-Match` → unconditional write, same as today.

The SPA's editor sends `If-Match: <last-known-etag>` on every save. On
412, it shows a "someone else changed this doc" dialog (06 covers the
UX).

### MCP tools

MCP `read_content` and `update_content` tools don't surface ETag directly
in their schema — exposing it would add a parameter to every tool call
and most MCP clients have no way to round-trip it. Tools continue to
unconditionally read or write. The ETag mechanism is REST-API-only.

### Test additions

Add to `tests/routing/test_per_store_api.py`:

- GET returns an `ETag` header.
- GET with matching `If-None-Match` returns 304 with no body.
- GET with non-matching `If-None-Match` returns 200 with body.
- PUT with matching `If-Match` updates and returns new ETag.
- PUT with non-matching `If-Match` returns 412 with the current ETag.
- PUT with no `If-Match` writes unconditionally.

## Test plan

- `tests/routing/test_store_resolver.py`
  - Valid `/api/<tenant>/<store>/content` → resolver sets contextvar,
    rewrites path to `/api/content`, subapp returns 200.
  - Malformed tenant slug → 404 before DB lookup.
  - Malformed store slug → 404 before DB lookup.
  - `/api/<known-tenant>/<unknown-store>` → 404.
  - `/api/<unknown-tenant>/<any-store>` → 404.
  - `/api/<tenant>/<store>` where principal isn't a member of `<tenant>`
    → 403. **This is B2's regression test** — exercise with a principal
    that has membership on tenant A trying to access a store on tenant B.
  - Multi-tenant principal: requests to either tenant succeed when the
    URL slug matches a membership. The order of `tenant_roles` does not
    affect outcomes (cover this by shuffling insertion order in the test
    fixture).
  - `/api/health` skipped by resolver (no tenant/store needed).
  - `/auth/...`, `/admin/...`, `/ui/...`, `/static/...` skipped.
  - Concurrent requests to different stores don't leak contextvars.
- `tests/routing/test_per_store_api.py`
  - Provision two stores, write content via REST to store A, read from
    store B → 404 (correct isolation).
  - Tree endpoint on store A reflects only store A's files.
  - Delete in store A doesn't affect store B.
- `tests/routing/test_per_store_mcp.py`
  - Same isolation checks via MCP tools (`list_content`, `read_content`,
    `create_content`). Use a stub MCP client (FastMCP exposes one in
    tests).

## Acceptance

- Auth-enabled: requests to `/api/<tenant>/<store>/content` and
  `/mcp/<tenant>/<store>/...` succeed for principals with membership on
  `<tenant>`; 404 for unknown tenant or store; 403 for principals
  without membership on the URL's tenant.
- Multi-tenant principal works correctly: same user accessing tenant A
  and tenant B in successive requests gets the right store each time.
- Auth-disabled: nothing about request paths changes.
- `uv run pytest tests/routing` passes, existing tests still pass.
- A request to `/api/health` works without auth and without a tenant/store.

## Registry API impact

`StoreRegistry.get()` now takes a tenant slug, not a tenant_id:

```python
async def get(self, tenant_slug: str, store_slug: str) -> LoadedStore:
    ...
```

Internally it resolves the slug → tenant_id via a SQL query, then loads
the store as before. The cache key becomes `(tenant_slug, store_slug)`.
`invalidate()` and `provision()` follow the same shape. The change is
local to spec 03's `registry.py`; update spec 03's signatures to match.

## Open questions

**Search in auth mode.** v1 disables search when `AUTH_ENABLED=True`
because a single shared index would leak content across tenants. The
endpoint should 503 with a clear message rather than silently returning
nothing. Confirm this is acceptable for v1.

## Notes for the Claude Code session

- Don't rewrite the existing handlers in `api.py` to take a `request:
  Request` arg if they don't already — just add the `_fs(...)` call inside
  the handler body using the closed-over `filesystem_or_resolver`.
- `set_current_store` and `set_current_principal` return `contextvars.Token`
  objects. Pass them to `reset_current_store` / `reset_current_principal` in
  a `finally` block. **Don't `set(None)`** — that clobbers the prior value
  instead of restoring it. The difference only matters in nested contexts
  and asyncio task groups, but it bites silently when it does.
- The store resolver runs *after* the auth middleware. Both pass through
  when `AUTH_ENABLED=False`. The legacy `/api/*` and `/mcp` routes work
  exactly as today in that mode.
- The path rewrite trick must update `raw_path` too, not just `path` —
  Starlette uses `raw_path` for some routing decisions.
