# Tenant-admin self-service + MCP server configs

This directory holds the design specs for the next phase of Stash-MCP
after the auth/multi-tenant foundation (see [`docs/auth/`](../auth/README.md)
specs 01–06) lands. Each spec is a self-contained chunk of work for a
single Claude Code session. They are sequenced: later specs assume the
earlier ones have landed.

## Why we're doing this

The auth foundation gave us tenants, stores, and global-admin
plumbing. The Organization Settings modal that ships today is
read-only for tenant admins because every CRUD endpoint requires
admin role on the `default` tenant. Two things are missing:

- **Self-service stores.** A tenant admin should be able to add and
  remove stores in their tenant without escalating to a global
  admin. Today they can't.
- **Scoped MCP-server configs.** Stash-MCP currently exposes one MCP
  endpoint that serves a whole store. Real deployments want
  different agents to see different slices — engineering docs only,
  runbooks read-only + ops scratch read-write, a tenant-wide view
  with limited tools, etc. There's no first-class object for that
  today, and the routing model is URL-based per store. The original
  Organization-Settings UI had a mock "MCP Servers" tab that
  modelled this; spec `d7cf10f` replaced it with a real Stores list
  because the mock wasn't backed by anything. This series is the
  real backing.

The shape: tenant admins author named MCP-server configs in the UI.
Each config selects a subset of tools to expose and one or more
content roots that compose paths from the tenant's stores. Users
mint API tokens bound to a config. The single `/mcp` endpoint reads
the token, resolves the config, and serves a scoped view —
restricted tools, restricted paths, possibly spanning multiple
underlying stores.

## Locked design decisions

These were settled during scoping on 2026-05-16 and are not
re-litigated in the specs below. Cite this file if anything tries to
deviate.

- **Tenant metadata stays global-admin only.** Tenant display name +
  slug are not editable by tenant admins. The General tab in the
  Organization Settings modal remains read-only. The mutation
  surface in this phase is stores and MCP-server configs — nothing
  else about the tenant itself.
- **Parallel router, not widened `require_admin`.** The new
  tenant-scoped surface lives under `/tenants/{tenant_id}/*`, gated
  by a new `require_tenant_admin` dependency. The existing
  `/admin/*` global-admin surface is unchanged. Keeping the surfaces
  separate at the router level means an accidental guard slip in
  one place doesn't expose tenant-admin to the rest of the admin
  API.
- **Shared store-ops module.** `stash_mcp/stores/admin_ops.py`
  contains the provisioning/rename/delete bodies. The global-admin
  router and the new tenant-admin router both delegate to it, so
  the two surfaces can't drift.
- **MCP server config shape.** A config has: tools (allowlist), and
  content roots. A content root is `simple` (one mount) or
  `virtual` (≥1 mount). A mount is `(store_id, subpath,
  virtual_prefix)`. Mounts can reference multiple stores within
  the same tenant; cross-tenant references are forbidden and
  enforced at the route layer.
- **Per-mount read/write permissions are gone.** The old mock had a
  `read` / `read-write` toggle per mount inside a virtual content
  root. That distinction collapses into the per-config tool
  allowlist: write capability emerges from whether write tools are
  enabled at the config level. Simpler, fewer enforcement surfaces.
- **Routing is keyed on the token, not the URL.** A scoped token
  presented at `/mcp` resolves to one config; the existing URL form
  `/mcp/<tenant>/<store>/*` keeps working for unscoped tokens.
  Coexistence, not replacement. Deprecation of the URL form is a
  separate decision once configs are widely adopted.
- **`ApiToken.scopes` stays comma-separated. Config binding gets its
  own column.** `ApiToken.mcp_server_id` is a new nullable FK with
  `ON DELETE SET NULL`. NULL = legacy behaviour. Not NULL = scoped
  via config. The two concepts are different and shouldn't share a
  column.
- **Git tools and transactions are single-store-only.** A config
  that composes paths from more than one store cannot expose
  `log_content`, `diff_content`, `blame_content`, or any of the
  transaction tools. Validated at config-author time (UI prevents
  it) and re-checked at runtime (defense in depth). Per-mount
  git/tx is a future spec.
- **Rollout via feature flag.** `STASH_MCP_CONFIGS_ENABLED` defaults
  off. Specs 01–03 ship with no runtime behaviour change; 04 ships
  with the flag off; the flag flips in a follow-up PR after a soak
  in dogfood. The default flips to `true` only once we're
  satisfied.
- **`REGISTERED_TOOL_NAMES` is hand-maintained.** A module-level
  frozenset in `stash_mcp/mcp_server.py`, populated next to the
  `@mcp.tool(...)` decorators. Not reflected from the FastMCP
  server object — the conditional registrations
  (`if not Config.READ_ONLY:` etc.) make reflection lie.
- **Synthetic composite store, not multi-store rewrite.**
  `CompositeLoadedStore` and `CompositeFileSystem` masquerade as a
  single `LoadedStore`/`FileSystem` so downstream code (tool
  handlers, `_fs()`, `_bare_fs()`) is unchanged. Wrapper over
  rewrite.

## Spec chain

| # | Spec | Adds | Depends on |
|---|---|---|---|
| 01 | [Tenant-admin scope and stores CRUD](01-tenant-admin.md) | `require_tenant_admin`, parallel `/tenants/{tenant_id}/stores/*` router, shared `stash_mcp/stores/admin_ops.py`, modal wiring for store create/edit/delete | `docs/auth/05`, `docs/auth/06` |
| 02 | [MCP server configs (data + API + UI, inert)](02-mcp-server-configs.md) | `mcp_servers` + `mcp_server_tools` + `mcp_server_content_roots` + `mcp_server_mounts` tables, `/tenants/{tenant_id}/mcp-servers/*` CRUD, MCP Servers tab in Organization Settings, `REGISTERED_TOOL_NAMES` constant | 01 |
| 03 | [Token scoping to MCP server configs](03-token-scoping.md) | `ApiToken.mcp_server_id` column, server picker in the token-mint form, `[tenant/config]` chip in the token list, `GET /auth/visible-mcp-servers` | 02 |
| 04 | [Runtime enforcement: resolver, composite FS, tool allowlist](04-runtime-enforcement.md) | `McpServerResolverMiddleware`, `CompositeFileSystem`, `CompositeLoadedStore`, per-config tool-allowlist check in `_instrumented_tool`, multi-store git/tx disable-rule, `STASH_MCP_CONFIGS_ENABLED` flag | 02, 03 |

Specs 01–03 are independently mergeable in order. Spec 04 is the only
one that changes runtime behaviour (and even then, only when the
feature flag is on).

## Working with these specs

Each spec is structured the same way:

- **Goal** — what this chunk accomplishes and what's deliberately
  deferred.
- **Files added / modified** — concrete paths.
- **Design** — schema DDL, function signatures, env var names.
  Code-grounded enough that a Claude Code session can act on it
  without further design decisions.
- **Test plan** — what to write and where.
- **Acceptance** — observable criteria the chunk is done.
- **Open questions** — anything still worth thinking through. If
  empty, none.
- **Notes for the Claude Code session** — implementation gotchas and
  things to avoid.

When kicking off a Claude Code session, point it at the relevant
spec file: "Implement `docs/mcp/01-tenant-admin.md` end-to-end, then
stop. Don't touch anything outside the file/modify list."
