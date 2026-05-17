# 04 — Runtime enforcement: resolver, composite filesystem, tool allowlist

## Goal

Make the MCP-server-config metadata from 02 + the scoped tokens from
03 actually shape what an agent sees at runtime. A scoped token, when
presented at `/mcp`, resolves to one config, which determines:

- Which tools are callable on this connection (per-config allowlist).
- Which file paths are visible (union of mounts across the config's
  content roots).
- Which underlying `Store`(s) back those paths (one or many, mounted
  under arbitrary virtual prefixes).

Unscoped tokens (and legacy clients hitting `/mcp/<tenant>/<store>/*`)
keep working unchanged. The new behaviour is additive and gated on
the token-config binding from 03, plus a feature flag for cautious
rollout.

After this lands, a tenant admin can create `engineering-docs` (02),
mint a token bound to it (03), connect to `/mcp`, and see only the
engineering subset of `acme/docs` — read tools yes, write tools no,
git tools yes (single-store), no other store visible.

## Out of scope

- Per-mount git histories on a multi-store composite. v1: git tools
  and transaction tools are disallowed on configs that span more
  than one underlying store. A future spec wires per-mount git/tx.
- Replacing or deprecating the URL-based `/mcp/<tenant>/<store>/*`
  routing. It stays for unscoped tokens. Deprecation is a separate
  decision once configs are widely adopted.
- Search-index scoping. `search_content` against a composite that
  unions multiple stores returns results from all of them. Filtering
  the search index by mount prefix is a v2 concern — for v1, the
  embedder runs per-store and the composite concatenates results.
- Multi-tenant configs. A config always belongs to one tenant; all
  mounts in a config must reference stores in that tenant (enforced
  in 02).

## Files added

```
stash_mcp/routing/mcp_server_resolver.py     # token → config → composite store middleware
stash_mcp/stores/composite_filesystem.py     # CompositeFileSystem wrapping N FileSystems
stash_mcp/stores/composite_store.py          # CompositeLoadedStore, returned by the new resolver
stash_mcp/mcp_server_runtime.py              # tool-allowlist enforcement helper (companion to _instrumented_tool)
tests/routing/test_mcp_server_resolver.py
tests/stores/test_composite_filesystem.py
tests/mcp_server/test_runtime_tool_allowlist.py
tests/mcp_server/test_runtime_path_isolation.py
```

## Files modified

```
stash_mcp/auth/api_token_provider.py         # populate Principal.claims['mcp_server_id'] from the row
stash_mcp/auth/principal.py                  # convenience accessor Principal.mcp_server_id (optional)
stash_mcp/mcp_server.py                      # _instrumented_tool consults the config's tool allowlist
                                              # REGISTERED_TOOL_NAMES exposed for 02's validators
stash_mcp/main.py                            # middleware order: Auth → McpServerResolver → StoreResolver → app
stash_mcp/config.py                          # STASH_MCP_CONFIGS_ENABLED (default false until rolled)
stash_mcp/routing/store_resolver.py          # short-circuit when current_store is already set
stash_mcp/errors.py                          # McpServerToolNotAllowed, McpServerConfigDisabled, McpServerMultiStoreGitForbidden
stash_mcp/tenant_admin/mcp_servers.py        # add validate_runtime_compatibility check
docs/mcp/README.md                           # spec chain
```

## Design

### What the middleware chain looks like

Existing (post docs/auth/04-routing):

```
HTTP → StashAuthMiddleware → StoreResolverMiddleware → app
```

After 04:

```
HTTP → StashAuthMiddleware → McpServerResolverMiddleware → StoreResolverMiddleware → app
```

Order matters: auth runs first to materialise `Principal`. The new
resolver runs next — it cares only about scoped tokens. The legacy
`StoreResolverMiddleware` runs last and is now conditional: if
`current_store()` is already set (by the new resolver), it does
nothing; otherwise it does what it always did (regex the URL,
resolve `<tenant>/<store>`, set `current_store`).

This means **both routing models live simultaneously** until we
decide to deprecate one. The decision is driven by the token, not
by the URL.

### `McpServerResolverMiddleware`

```python
# stash_mcp/routing/mcp_server_resolver.py

class McpServerResolverMiddleware:
    """Resolve a request's MCP server config from the principal's token.

    Runs after StashAuthMiddleware, before StoreResolverMiddleware. Only
    affects /mcp/* and /api/* requests. If the principal carries a
    `mcp_server_id` claim, loads the config and binds a composite store
    to `current_store` for the duration of the request. If the claim
    is absent, leaves `current_store` untouched — StoreResolverMiddleware
    will handle URL-based resolution next.
    """

    def __init__(self, app, *, registry: StoreRegistry, prefixes=("/mcp", "/api")):
        self.app = app
        self.registry = registry
        self.prefixes = prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not Config.MCP_CONFIGS_ENABLED:
            await self.app(scope, receive, send); return
        if not any(scope["path"].startswith(p) for p in self.prefixes):
            await self.app(scope, receive, send); return

        principal = current_principal()
        mcp_server_id = principal.claims.get("mcp_server_id") if principal else None
        if not mcp_server_id:
            await self.app(scope, receive, send); return

        # Load config + tools + content roots + mounts + stores.
        config = await self._load_config(mcp_server_id)
        if config is None or not config.enabled:
            raise McpServerConfigDisabled(...)

        composite = await self._build_composite(config)
        set_current_mcp_server(config)            # new contextvar, see below
        token = set_current_store(composite)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_store(token)
            reset_current_mcp_server()
```

Two contextvars are now in play during a scoped request:

- `current_store` holds the composite `LoadedStore` (existing
  contextvar from docs/auth/04-routing, repurposed).
- `current_mcp_server` is new — holds the resolved `McpServer` row
  with its tools and content roots. `_instrumented_tool` reads it
  to enforce the allowlist.

Both are reset on the way out.

### `CompositeLoadedStore`

Conforms to the existing `LoadedStore` shape so downstream code
(tool handlers, `_fs()`, `_bare_fs()`) doesn't have to know it's a
composite. Three relevant attributes:

```python
@dataclass
class CompositeLoadedStore:
    tenant_id: uuid.UUID
    filesystem: CompositeFileSystem
    fs_for_mcp: CompositeFileSystem
    git_backend: GitBackend | None         # set only if config has a single underlying store
    transaction_manager: TransactionManager | None  # same condition
    underlying_store_ids: frozenset[uuid.UUID]

    @property
    def is_single_store(self) -> bool:
        return len(self.underlying_store_ids) == 1

    @property
    def display_name(self) -> str:
        return self._config_name   # for OverviewContent fallback
```

The constructor walks the config's content roots and mounts, calls
`registry.get(...)` per distinct store, and assembles the composite.
If the config has exactly one underlying store, `git_backend` and
`transaction_manager` are forwarded from that store's `LoadedStore`
so git tools and transactions Just Work. If more than one store,
both are `None` and the runtime rejects git/tx tool calls (see
"Multi-store rules" below).

`fs_for_mcp` returns the same `CompositeFileSystem` as `filesystem`
because the transaction-wrapping logic that the per-store
`fs_for_mcp` does is single-store-only; for multi-store configs
there is no transaction, so no wrapping. For single-store configs,
the underlying store's `fs_for_mcp` (the transaction-wrapping
filesystem) is wrapped inside the composite. Both cases keep
`filesystem` and `fs_for_mcp` interchangeable from the handler's
point of view.

### `CompositeFileSystem`

Implements the same interface as `FileSystem` so the tool handlers
need zero changes. Internal model:

```python
class CompositeFileSystem:
    """Routes file ops to the right underlying FileSystem by virtual prefix."""

    def __init__(self, mounts: list[CompositeMount]):
        # mounts sorted by virtual_prefix length descending so longer
        # prefixes match first (so a mount at "docs/team-a" beats
        # "docs" for paths under "docs/team-a/").
        self._mounts = sorted(mounts, key=lambda m: -len(m.virtual_prefix))

    def _resolve(self, agent_path: str) -> tuple[FileSystem, str]:
        """Map an agent-facing relative path to (underlying_fs, fs_relative_path).

        Raises ContentNotFound if the path doesn't fall inside any mount.
        """
        normalized = agent_path.lstrip("/")
        for mount in self._mounts:
            prefix = mount.virtual_prefix
            if prefix == "":
                # root mount: catches anything not caught by a longer prefix
                fs_rel = posixpath.join(mount.subpath, normalized)
                return mount.fs, fs_rel
            if normalized == prefix or normalized.startswith(prefix + "/"):
                tail = normalized[len(prefix):].lstrip("/")
                fs_rel = posixpath.join(mount.subpath, tail)
                return mount.fs, fs_rel
        raise ContentNotFound(f"path {agent_path!r} is not inside any mount")
```

And then each `FileSystem` operation forwards:

```python
    def read_file(self, path: str) -> str:
        fs, fs_rel = self._resolve(path)
        return fs.read_file(fs_rel)

    def write_file(self, path: str, content: str) -> None: ...
    def list_dir(self, path: str) -> list[FileEntry]: ...
    def exists(self, path: str) -> bool: ...
    # etc.
```

`list_dir` deserves special care: a virtual prefix appears as a
directory entry in its parent's listing, even though no underlying
store has a file there. So `list_dir("")` on a composite with
mounts at `engineering` and `ops` yields synthetic directory entries
for `engineering/` and `ops/`. Path-collision rules from 02 already
ensure prefixes don't overlap, so the synthesis is well-defined.

The underlying `FileSystem._resolve_path` containment check still
fires: a mount with `subpath="engineering"` plus an agent request
for `..` (which the composite would translate to `engineering/..`)
will still get rejected by `_resolve_path` because it'd escape
`content_dir`. The composite is a router, not a sandbox replacement
— the per-store sandbox is intact.

`_bare_fs()` access: the composite's `_resolve_path(agent_path)` is
exposed (mirrors `FileSystem._resolve_path`) returning the absolute
path on disk for the same containment-check use cases
(`move_content_batch`'s destination-existence pre-check is the
known caller).

### Multi-store rules

A config whose mounts reference >1 distinct `store_id` is allowed,
but several tools cannot operate on it because they assume a single
git repo / single transaction context:

- `log_content`, `diff_content`, `blame_content` — git-backed, need
  a single repo.
- `start_content_transaction`, `commit_content_transaction`,
  `abort_content_transaction` — the transaction manager binds to
  one `FileSystem`.

Enforcement is in two layers, defense-in-depth:

**At config validation time (spec 02, backported)**: extend
`stash_mcp/tenant_admin/mcp_servers.py` with
`validate_runtime_compatibility(config)`. Called on POST/PATCH. If
the config has >1 underlying store and `config.tools` contains any
of the disallowed names, reject with 400
`/problems/mcp-server/multi-store-git-forbidden`. The UI in 02
should prevent the user from checking these tools when adding a
second store; the server-side check is the safety net.

**At runtime (this spec)**: a small additional check inside
`_instrumented_tool`. If `current_store().is_single_store` is
False and `tool_name` is in the disallowed set, raise
`McpServerMultiStoreGitForbidden`. This catches any config that
was authored before the validator existed, or any future bug that
lets one slip through.

### `_instrumented_tool` changes

`_instrumented_tool` already wraps every tool with:

1. Metric instrumentation.
2. `_enforce_tool_scope(tool_name, required_scope)` for scope-bitmap
   enforcement.

Add a new check **before** the scope check:

```python
# stash_mcp/mcp_server.py — inside _instrumented_tool

config = current_mcp_server()
if config is not None:
    if tool_name not in config.allowed_tool_names:
        raise McpServerToolNotAllowed(
            f"tool {tool_name!r} is not enabled on MCP server config "
            f"{config.slug!r}"
        )
    if (
        tool_name in _MULTI_STORE_DISALLOWED_TOOLS
        and not current_store().is_single_store
    ):
        raise McpServerMultiStoreGitForbidden(
            f"tool {tool_name!r} requires a single-store config; "
            f"{config.slug!r} spans {len(current_store().underlying_store_ids)} stores"
        )

# existing scope check follows
```

`current_mcp_server()` returning `None` means the request is
unscoped (legacy URL-based) — no per-config gating applies, current
behaviour preserved. `_MULTI_STORE_DISALLOWED_TOOLS` is a
module-level frozenset listing the six tool names above.

The order — config allowlist before scope — is deliberate. A token
that wasn't allowlisted for the tool should hit the more specific
error rather than a generic scope error.

### `ApiTokenAuthProvider` change

Currently `authenticate` loads the `ApiToken` row, builds the
`Principal` with `claims = {"scopes": "...comma-separated..."}`.

Extend `claims` with `mcp_server_id` when present:

```python
# stash_mcp/auth/api_token_provider.py — inside authenticate

claims = {"scopes": row.scopes}
if row.mcp_server_id is not None:
    claims["mcp_server_id"] = str(row.mcp_server_id)
return Principal(
    user_id=row.user_id,
    auth_method="api_token",
    tenant_roles=...,           # populated by membership lookup
    claims=claims,
)
```

`OIDCAuthProvider` and `SessionCookieAuthProvider` are not changed —
human sessions and bearer JWTs are inherently unscoped. A human in
the SPA hitting `/api/<tenant>/<store>/...` keeps going through
URL-based resolution. The new resolver only fires for `api_token`
auth, since that's the only path where `mcp_server_id` is present.

(A future enhancement could let humans pick a "view as this MCP
server" mode in the SPA for debugging — out of scope.)

### Tool surface negotiation

FastMCP's tool catalog is built at startup; we can't easily
register-then-unregister tools per request. Two approaches:

- **(A) Filter at call time.** Every tool stays registered, but
  `_instrumented_tool` rejects calls to non-allowlisted tools with
  `McpServerToolNotAllowed`. The agent sees all tools in the
  catalog but gets errors on the ones not in the config. Simple,
  but leaks the catalog.

- **(B) Filter `tools/list`.** Hook FastMCP's `tools/list`
  handler to filter the response by the active config's allowlist
  on the way out. Combined with (A) for defense in depth.

Ship both. (A) is the correctness net; (B) is what the agent
sees, and matters for tool-discovery quality. (B) requires reaching
into FastMCP's protocol handlers — there's a hook
(`mcp.list_tools_handler` or a decorator depending on SDK version)
that returns a `list[Tool]`. Wrap it to consult
`current_mcp_server()` and drop entries not in the allowlist.

For unscoped requests, the unfiltered catalog is returned (current
behaviour).

### Feature flag

`STASH_MCP_CONFIGS_ENABLED` (env var, bool, default `false`). When
off:

- `McpServerResolverMiddleware.__call__` short-circuits to
  `self.app(...)` for all requests.
- `_instrumented_tool`'s new check is skipped because
  `current_mcp_server()` will never be set.
- `ApiTokenAuthProvider` still populates `mcp_server_id` in claims
  (cheap, no behaviour change without the resolver).
- 02's CRUD and 03's token-mint work as before — the data is
  there, it just doesn't shape runtime.

When on, the full behaviour described above kicks in.

Rollout plan:

1. Ship 01, 02, 03 to develop-0.2.0. Flag off.
2. Ship 04 to develop-0.2.0. Flag still off.
3. Soak in a dev environment with the flag on; verify scoped
   tokens behave correctly, unscoped tokens unchanged.
4. Flip the flag on for the dogfood deployment (ReasonFlow's
   Stash) for a week. Watch metrics.
5. Default to `true` in a follow-up PR. Document the env var as
   "set to `false` to fall back to URL-only routing."

### What `tools/list` returns to an unscoped token

Unchanged: the full tool catalog the process registers at startup,
modulo `STASH_READ_ONLY` and the git-tracking flag (existing
behaviour). Configs don't affect unscoped clients.

### How the OverviewContent / SPA changes (none)

The SPA still talks to `/api/<tenant>/<store>/...` and the legacy
URL-based resolver. Humans don't carry scoped tokens. So the SPA
needs no changes for this spec — `OrganizationSettingsModal`'s MCP
Servers tab (02) and the token picker (03) are the only UI
surfaces touched by phase 2.

## Test plan

`tests/routing/test_mcp_server_resolver.py`:

- Unscoped token + URL `/mcp/acme/docs/...` → request resolves to
  the legacy `LoadedStore` for `acme/docs`. Same as before this
  spec.
- Scoped token (config = `engineering-docs`, simple root, one
  mount in `docs` at `engineering/`) + URL `/mcp/whatever/...` →
  composite store with one underlying mount; `current_store` is
  the composite; `current_mcp_server` is the config.
- Scoped token + the config is `enabled=false` → 401-ish error
  `McpServerConfigDisabled`. (4xx, picks a 4xx code consistent
  with existing patterns — probably 403.)
- Scoped token + the underlying store referenced in a mount has
  been deleted → 500 with a clear error (the mount's RESTRICT FK
  should prevent this state, but defensive test).
- Flag off → resolver short-circuits; behaviour identical to
  pre-04.

`tests/stores/test_composite_filesystem.py`:

- `read_file("foo.md")` on a simple-root composite (mount at root
  of store `docs/`) returns store `docs`'s `foo.md`.
- `read_file("foo.md")` on a virtual composite with one mount at
  prefix `engineering` and another at `ops` → `engineering/foo.md`
  hits the engineering mount; `ops/foo.md` hits the ops mount;
  `foo.md` at root → ContentNotFound (no root mount).
- A root mount + a prefixed mount → root is the catch-all, prefix
  takes precedence for matching paths (sort-by-prefix-length
  ensures it).
- `list_dir("")` on a virtual composite with no root mount returns
  synthetic dir entries for each top-level virtual prefix.
- `list_dir("engineering")` walks into the engineering mount's
  store and lists its `engineering/` subdirectory.
- Containment: a path with `..` segments at the agent layer still
  rejected by the underlying `FileSystem._resolve_path`.
- A mount with `subpath="engineering"` and an agent path of
  `engineering/../ops` → rejected.

`tests/mcp_server/test_runtime_tool_allowlist.py`:

- Scoped token, config allows `[read_content, search_content]`,
  agent calls `read_content` → success.
- Same config, agent calls `edit_content` →
  `McpServerToolNotAllowed`.
- `tools/list` over the scoped session returns only the two
  allowlisted tools.
- Unscoped token, same process → `tools/list` returns the full
  catalog. `edit_content` callable.
- Config with `enabled=false` → connect fails (resolver rejects);
  tools never enumerated.

`tests/mcp_server/test_runtime_path_isolation.py`:

- Scoped token, config has one simple mount at
  `acme/docs/engineering/` → `read_content("foo.md")` reads
  `docs/engineering/foo.md` from the on-disk store. `read_content("../../sensitive.md")`
  rejected.
- Scoped token, config has virtual mounts `engineering` and `ops`
  drawn from different stores → reads via both prefixes hit the
  right stores; cross-prefix paths (`engineering/../ops/...`)
  rejected by containment.
- Config spans >1 store, `log_content` in allowlist (validator
  somehow missed it) → runtime returns
  `McpServerMultiStoreGitForbidden`. (Hand-craft the config via DB
  insert; the validator from 02 shouldn't let this happen via
  the API.)

02's POST/PATCH tests get one additional case (added in this
spec's PR, in `tests/tenant_admin/test_mcp_servers_routes.py`):

- POST with multi-store mounts and `log_content` in the tools list
  → 400 `/problems/mcp-server/multi-store-git-forbidden`.

## Acceptance

1. `uv run pytest` clean; `uv run ruff check stash_mcp` clean.
2. Bring up the auth-enabled stack with `STASH_MCP_CONFIGS_ENABLED=true`.
3. As `acme` admin, create `engineering-docs` (single-store, simple
   root, tools: `read_content`, `search_content`, `list_content`,
   `log_content`).
4. Mint a token bound to `engineering-docs`. Connect an MCP client
   to `/mcp` with that token.
5. `tools/list` returns exactly the four allowlisted tools.
6. `read_content("foo.md")` reads
   `content/<acme>/docs/engineering/foo.md` — verify by inspecting
   the on-disk path.
7. `read_content("../sensitive.md")` → error.
8. `edit_content` → `McpServerToolNotAllowed`.
9. Stop. Mint a second token, unscoped, against the same Stash.
   Connect to `/mcp/acme/docs/` (legacy). `tools/list` returns the
   full catalog. `read_content("engineering/foo.md")` works
   identically. **The two routing models coexist.**
10. As `acme` admin, change the config to a virtual root with two
    mounts (one in `docs`, one in `reasonflow`). Save. The
    runtime starts treating the composite as multi-store: git
    tools become unavailable; reads still work across both
    mounts.
11. Set `STASH_MCP_CONFIGS_ENABLED=false`, restart the server.
    The legacy `/mcp/acme/docs/` still works. The scoped token
    falls back to no-effect (claims still set, but no resolver
    fires) — depending on what the client does, this is either
    "works with full catalog" (if the URL is legacy-shaped) or
    "404" (if the URL is the bare `/mcp` and no resolver bound a
    store). This is the expected rollback behaviour.

## Open questions

- **Search.** `search_content` against a composite that unions two
  stores: should results carry the underlying store identifier in
  the response, or only the agent-facing path with virtual prefix?
  Lean agent-facing-path only; the user shouldn't have to know
  about the underlying split. **Defer until search wiring is
  reviewed in code.**
- **Resource registry.** The MCP `Resources` surface (`stash://` URI
  template; `README.md` registered as a resource per the existing
  notes) — does it honour the composite, or stay rooted in the
  underlying store(s)? Lean composite-aware, behind the same
  feature flag; needs a small change in `mcp_server.create_mcp_server`'s
  resource block. **Confirm in implementation.**
- **Audit at runtime.** Should an MCP request audit which config it
  ran under? Probably yes — useful for traceability when an agent
  goes rogue. v1 candidate: write an `mcp.request` audit row on
  each tool call with `actor=token, target_kind=mcp_server,
  target_id=config.id, action=tool_name`. **Decide before
  enabling the flag in dogfood.** If yes, add to this spec's PR.
- **Hot-reload of config changes.** A tenant admin edits a config
  while an agent has a live MCP session. Today the resolver loads
  the config per-request from the DB, so the next request reflects
  the edit. Good — no cache invalidation. The tool catalog
  exposed by `tools/list` is the snapshot at session start,
  though — agents may keep referencing tools that were removed.
  Tradeoff: hot-changing the catalog mid-session is invasive on the
  protocol side. v1 accepts the stale-catalog-until-reconnect
  behaviour, with the runtime check catching attempts to call
  removed tools.

## Notes for the Claude Code session

- The `CompositeFileSystem` is the load-bearing primitive. Get it
  right and the rest falls into place. Get it wrong (prefix
  matching, containment) and you have a security incident. Write
  the tests first; the implementation will pop out.
- The middleware order in `stash_mcp/main.py` is fragile because
  Starlette runs `add_middleware` in reverse order. Add a comment
  block making the runtime order explicit, the same way
  docs/auth/02-providers-middleware's middleware-mounting code does.
- `_instrumented_tool` is already a high-traffic wrapper. Don't
  add database round-trips inside it — the config is already
  resolved by the middleware and lives on the contextvar. The new
  check is a frozenset lookup.
- `_MULTI_STORE_DISALLOWED_TOOLS` lives in `mcp_server.py` next to
  `REGISTERED_TOOL_NAMES` (introduced in 02). Don't import it from
  a new module; the colocation makes the relationship between
  "what's registered" and "what needs single-store semantics"
  visible at a glance.
- The composite store's `tenant_id` is the config's `tenant_id`.
  Don't compute it from the union of mounts' store-tenant-ids —
  02 already enforces that all mounts in a config belong to the
  config's tenant, so the lookup is single-source.
- The feature flag default of `false` is important for first
  rollout. Don't be tempted to flip it to `true` "since the tests
  pass" — the soak in the dogfood deployment is the actual
  acceptance gate.
- The `tools/list` filter (approach B above) is small but
  protocol-touching. If the FastMCP version we use doesn't have a
  clean hook, ship approach A only and open a follow-up to add
  the catalog filter once a hook is available. Approach A is
  correct on its own; B is for UX of tool discovery.
- Keep the new middleware's prefix list (`/mcp`, `/api`) in sync
  with the legacy resolver's. If they diverge, scoped tokens
  silently behave differently between MCP and REST.
- 02's `validate_runtime_compatibility` is a small but real
  change to 02's PR — flag it during code review of this PR if
  02 already merged.
