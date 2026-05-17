# 02 — MCP server configs (data + API + UI, inert)

## Goal

Let a tenant admin define multiple named MCP-server *configurations*
inside their tenant. Each config carries:

- A selected subset of MCP tools to expose (e.g. `read_content`,
  `search_content`, but not `edit_content`).
- One or more **content roots** — named slices of content composed
  from paths drawn from one or more `Store` rows in the same tenant.

A config is pure metadata in this spec — nothing about routing or
runtime behaviour changes here. Tokens still mint without a config
reference (03), the MCP endpoint still resolves stores by URL (04).
This spec lands the data model, the CRUD API, and the
Organization-Settings tab that authors configs. The configs sit inert
until 03 wires tokens to them and 04 makes the runtime honour them.

The reason to land this on its own: configs without enforcement are
harmless (no behaviour changes), but configs with enforcement and
without tokens-scoped-to-configs is a chicken-and-egg problem at
rollout. Inert first, then incremental.

## Out of scope

- `ApiToken.mcp_server_id` and any token-mint UI changes — that's 03.
- `McpServerResolverMiddleware`, `CompositeFileSystem`, per-tool
  allowlist enforcement — that's 04.
- Per-mount read/write permissions. The old mock had `permission:
  'read' | 'read-write'` on each mount; that distinction is collapsed
  into the per-config tool allowlist (write capability emerges from
  whether write tools are enabled at the config level, not from
  per-mount flags). The mock's permission UI does not port forward.

## Files added

```
alembic/versions/<rev>_mcp_server_configs.py
stash_mcp/tenant_admin/mcp_servers.py        # /tenants/{tenant_id}/mcp-servers/* router
stash_ui/src/app/components/McpServersTab.tsx
stash_ui/src/app/components/CreateMcpServerModal.tsx
                                             # port of the 9181f29 CreateServerModal.tsx,
                                             # with the per-mount permission UI removed and
                                             # paths replaced by store-picker + subpath
stash_ui/src/api/mcpServers.ts               # typed wrappers
tests/tenant_admin/test_mcp_servers_routes.py
```

## Files modified

```
stash_mcp/db/models.py                       # McpServer, McpServerTool, McpServerContentRoot, McpServerMount
stash_mcp/tenant_admin/__init__.py           # mount mcp_servers router on the existing /tenants prefix
stash_mcp/errors.py                          # McpServerAlreadyExists, McpServerNotFound, ContentRootNotFound, ToolNameInvalid, MountInvalid
stash_ui/src/app/components/OrganizationSettingsModal.tsx
                                             # add third tab "MCP Servers"
stash_ui/src/app/types.ts                    # McpServerConfig, ContentRoot, Mount types
docs/mcp/README.md                           # extend spec chain
```

## Design

### Data model

Four new tables, all `tenant_id`-rooted through `mcp_servers`. Cascade
on tenant delete is `passive` everywhere — same pattern as the existing
`tenants` ↔ `stores` relationship. Store references use `RESTRICT` so a
tenant admin can't delete a store that is still mounted by some config
(they get a clear error and can fix the config first).

```python
# stash_mcp/db/models.py — appended

class McpServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_mcp_servers_tenant_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="60"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tenant: Mapped[Tenant] = relationship(back_populates="mcp_servers")
    tools: Mapped[list[McpServerTool]] = relationship(
        back_populates="mcp_server",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    content_roots: Mapped[list[McpServerContentRoot]] = relationship(
        back_populates="mcp_server",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="McpServerContentRoot.sort_order",
    )


class McpServerTool(Base):
    __tablename__ = "mcp_server_tools"
    __table_args__ = (
        PrimaryKeyConstraint("mcp_server_id", "tool_name"),
        CheckConstraint(
            "tool_name ~ '^[a-z_][a-z0-9_]{0,62}$'",
            name="ck_mcp_server_tools_name",
        ),
    )

    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(63), nullable=False)

    mcp_server: Mapped[McpServer] = relationship(back_populates="tools")


class McpServerContentRoot(Base):
    __tablename__ = "mcp_server_content_roots"
    __table_args__ = (
        CheckConstraint("kind IN ('simple','virtual')", name="ck_content_roots_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    mcp_server: Mapped[McpServer] = relationship(back_populates="content_roots")
    mounts: Mapped[list[McpServerMount]] = relationship(
        back_populates="content_root",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="McpServerMount.sort_order",
    )


class McpServerMount(Base):
    __tablename__ = "mcp_server_mounts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content_root_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mcp_server_content_roots.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subpath: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    virtual_prefix: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    content_root: Mapped[McpServerContentRoot] = relationship(back_populates="mounts")
    store: Mapped[Store] = relationship()
```

Add the back-references to `Tenant` and `Store`:

```python
class Tenant(Base):
    ...
    mcp_servers: Mapped[list[McpServer]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True
    )
```

`Store` does *not* get a `mounts: list[McpServerMount]` back-ref —
configs are tenant-scoped through `McpServer.tenant_id`, and we
enforce store-tenant agreement in the route layer rather than in SQL.

### Cross-tenant store reference rule

`McpServerMount.store_id` is a foreign key to `stores.id`, but SQLite
+ SQLAlchemy can't easily express "this store must belong to the same
tenant as `mcp_server.tenant_id`." Enforce it at the application
layer: the route handler that creates or updates a mount validates
that the resolved `Store.tenant_id` matches the config's
`tenant_id`. Reject with `/problems/mount/cross-tenant` (400) if it
doesn't.

This check is the only reason a tenant admin can be trusted to author
a config that references store IDs — they can only see their own
tenant's stores via the existing API surface, but a malicious
hand-crafted request could otherwise reference an unrelated tenant's
`store_id`.

### Simple vs virtual

The DB shape collapses simple and virtual to the same tables — a
simple content root is just a content root with `kind='simple'` and
exactly one mount with `virtual_prefix=""`. The distinction survives
in two places:

- The `kind` column, mostly so the UI can render the right form.
- The route handlers, which validate that a `simple` root has exactly
  one mount and a `virtual` root has at least one. Both validations
  on POST/PATCH.

A future cleanup could drop `kind` and key off mount count instead.
For v1, keep it — the UI affordance is worth the column.

### Mount path semantics

A mount is `(store_id, subpath, virtual_prefix)`:

- `subpath`: relative to the store's `content_dir` on disk. Empty
  string = mount the entire store. Must be a normalized,
  non-absolute path with no `..` segments — same containment rules
  `FileSystem._resolve_path` uses today.
- `virtual_prefix`: the namespace the agent sees. Empty string for
  simple roots (the mount appears at the root of the agent's view).
  For virtual roots, each mount typically has a distinct prefix so
  paths don't collide.

Path collision rule: within one content root, no two mounts may share
a `virtual_prefix`, and no `virtual_prefix` may be a path-prefix of
another. (E.g. `docs` and `docs/team-a` overlap — reject.) Enforced
in the route layer at POST/PATCH time, surfacing as
`/problems/mount/conflict` (400).

`virtual_prefix` normalization: trim leading/trailing slashes; an
empty string is canonical for the root. Reject `..` segments. Apply
the same rules to `subpath`.

### Tool name validation

`McpServerTool.tool_name` is checked against a server-side allowlist
of names actually registered with FastMCP — `read_content`,
`search_content`, `edit_content`, `create_content`, `overwrite_content`,
`edit_content_batch`, `delete_content`, `move_content`,
`move_content_directory`, `move_content_batch`,
`start_content_transaction`, `commit_content_transaction`,
`abort_content_transaction`, `log_content`, `diff_content`,
`blame_content`. Anything outside this set → 400 `ToolNameInvalid`.

The allowlist lives in `stash_mcp/mcp_server.py` as a module-level
constant `REGISTERED_TOOL_NAMES`, populated alongside the existing
tool registrations. The tenant-admin route imports it. When tools
are added or removed from `mcp_server.py`, the allowlist stays in
sync because it's derived from the same registrations.

### API surface

All under `Depends(require_tenant_admin)` from 01.

```
GET    /tenants/{tenant_id}/mcp-servers                            → list[McpServerInfo]
POST   /tenants/{tenant_id}/mcp-servers                            → McpServerInfo (201)
GET    /tenants/{tenant_id}/mcp-servers/{slug}                     → McpServerInfo
PATCH  /tenants/{tenant_id}/mcp-servers/{slug}                     → McpServerInfo
DELETE /tenants/{tenant_id}/mcp-servers/{slug}?confirm=true        → 204
```

`McpServerInfo` is the read model — `McpServer` + its `tools` (list
of names) + its `content_roots` (each with `mounts`). One round-trip
to render the tab; one PATCH to update a whole config including its
tools and content roots.

```python
class MountInput(BaseModel):
    store_slug: str   # resolved to store_id server-side
    subpath: str = ""
    virtual_prefix: str = ""

class ContentRootInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    kind: Literal["simple", "virtual"]
    mounts: list[MountInput] = Field(..., min_length=1)

class McpServerCreate(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    enabled: bool = True
    tools: list[str] = Field(default_factory=list)        # tool names
    content_roots: list[ContentRootInput] = Field(default_factory=list)

class McpServerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    enabled: bool | None = None
    tools: list[str] | None = None                        # whole-list replace
    content_roots: list[ContentRootInput] | None = None   # whole-list replace
```

PATCH is whole-list-replace for tools and content roots. Partial
mount updates are not exposed — the diff would be ambiguous (is a
new mount with the same prefix an update of an existing one or a
collision?), and editing a config is rare enough that the cost of
re-sending the whole structure on the wire is fine. The UI builds
the new structure client-side and POSTs the whole thing.

Slug is in the path and is immutable, same rationale as stores.

### Audit

| Action | Target kind | Detail |
|---|---|---|
| `mcp_server.created` | `mcp_server` | `{tenant_slug, slug, name}` |
| `mcp_server.updated` | `mcp_server` | `{changed_fields: [...]}` — see below |
| `mcp_server.deleted` | `mcp_server` | `{tenant_slug, slug}` |

`mcp_server.updated` detail: the route diff'd the old and new
representations and lists only the top-level field names that
actually changed (`name`, `description`, `timeout_seconds`,
`enabled`, `tools`, `content_roots`). Not the values — the audit log
isn't the place to record full content-root trees. The DB row is the
current truth; the audit is the change record.

### UI: third tab in `OrganizationSettingsModal.tsx`

Add an `"MCP Servers"` tab between General and Stores. Visibility
gated on `role === 'admin'` (same as the Stores tab's mutation
controls). The tab is composed of two components:

- **`McpServersTab.tsx`**: list + add/edit/delete entry points,
  empty-state. Modelled on `9181f292..OrganizationSettingsModal.tsx`'s
  `ServerSettings` function, but pointed at the new API.
- **`CreateMcpServerModal.tsx`**: the create/edit form. Port from
  `9181f292..CreateServerModal.tsx` with three concrete changes:
  - **Remove per-mount permission toggles.** The `permission: 'read'
    | 'read-write'` UI in the old virtual-content-root form goes
    away. Write capability is a server-level concept now (which
    tools are in the allowlist), not a per-mount concept.
  - **Replace free-form `path` strings with store-picker + subpath.**
    Each mount has a store dropdown (populated from `StoreContext`)
    and a subpath input. The dropdown is filtered to the active
    tenant's stores.
  - **Add a tool picker.** A checklist of `REGISTERED_TOOL_NAMES`,
    grouped by capability (read / write / git / transaction). The
    UI hint about "this server can write" is derived from whether
    any write-group tool is checked.

`stash_ui/src/api/mcpServers.ts` follows the same `stashFetch`
pattern: `list`, `get`, `create`, `update`, `remove`.

### What the new tab looks like with no configs

The empty state is `0 configs → render the empty-state placeholder
plus a "Create your first MCP server" button`. No magic default
config is created. Until 03+04 land, this empty state has no runtime
implication — the existing MCP endpoint still works as it does
today.

## Test plan

`tests/tenant_admin/test_mcp_servers_routes.py`:

- `POST` minimal config (slug + name only, empty tools, empty
  content_roots) → 201 with empty arrays in the response. Useful
  shape to validate.
- `POST` with one simple content root, one mount → 201. Reading
  back returns the same structure.
- `POST` with two mounts having overlapping `virtual_prefix` → 400
  `/problems/mount/conflict`.
- `POST` with a mount referencing a store from another tenant → 400
  `/problems/mount/cross-tenant`.
- `POST` with a `tool_name` not in `REGISTERED_TOOL_NAMES` → 400
  `/problems/tool-name/invalid`.
- `POST` with `kind='simple'` and zero mounts → 400 validation.
- `POST` with `kind='simple'` and two mounts → 400 validation.
- `POST` with duplicate slug → 409 `/problems/mcp-server/already-exists`.
- `PATCH` whole-list-replace of tools: rows added/removed reflect
  exactly the new list. Audit row's `changed_fields` includes `tools`.
- `PATCH` whole-list-replace of content_roots: old roots deleted,
  new roots inserted, mounts cascade-delete cleanly.
- `DELETE` without `?confirm=true` → 400 confirmation-required.
- `DELETE` with confirm → 204; rows gone; cascade to tools, content
  roots, mounts.
- `DELETE` of a store that's mounted by some config → 409 (this
  exercises the RESTRICT FK on `mcp_server_mounts.store_id`). Test
  belongs in `tests/tenant_admin/test_stores_routes.py` from 01 —
  add it once 02 is in place.
- 403 for a tenant-member who is not admin. (Covered by
  `require_tenant_admin` from 01; smoke check on one endpoint.)
- Cross-tenant: admin on `acme` calling `/tenants/{beta_id}/mcp-servers`
  → 403.

## Acceptance

1. `uv run pytest` clean; `uv run ruff check stash_mcp` clean.
2. `alembic upgrade head` applies cleanly to a fresh DB; downgrade
   reverses cleanly.
3. Bring up the auth-enabled dev stack as in 01.
4. Log in as `acme` admin. Open Organization Settings → MCP Servers
   tab renders, shows empty state.
5. Create a config: slug `engineering-docs`, simple content root with
   one mount (store=`docs`, subpath=`engineering`), tools = `read_content`,
   `search_content`, `list_content`, `log_content`. Submit → row
   appears in the tab. Audit row exists.
6. Edit the config: switch the content root to virtual, add a second
   mount (store=`reasonflow`, subpath=`ops`, virtual_prefix=`ops`).
   Submit → row updates.
7. Try to delete the store `docs` (Stores tab → trash) → 409 with a
   helpful Problem Details message pointing at the config that
   mounts it.
8. Delete the config → 204; the store delete now succeeds.
9. Confirm the existing `/mcp/<tenant>/<store>/*` endpoint still
   works as before — this spec adds zero runtime behaviour.

## Open questions

- **Mount sort order in the response.** The DB has `sort_order` on
  mounts and content roots. The UI may want to reorder them
  (drag-and-drop). v1: rely on the order in the POST/PATCH body,
  apply it as `sort_order` server-side. Drag-and-drop is a UI
  follow-up, not a schema change.
- **Where does config description show up.** The mock shows it under
  the server name in the tab. Fine. But if/when 04's
  `McpServerResolverMiddleware` renders an MCP server-info response
  to the agent, should `description` flow through? **Open until 04.**
- **Tool grouping.** The UI shows tools grouped by capability
  (read/write/git/transaction). The grouping has to live somewhere —
  either hard-coded in the React, or returned by a new
  `GET /tenants/{id}/mcp-servers/tool-catalog` endpoint. Lean
  hard-coded for v1 — the tool set changes rarely.

## Notes for the Claude Code session

- Don't try to use a join table for tools just to look "more
  normalized." `McpServerTool` is a join table; that's fine. The
  alternative — a JSON column on `McpServer` — is harder to query
  for "show me all configs that expose `edit_content`" and not
  cheaper to maintain.
- The cross-tenant store check is the one rule that *must not* be
  forgotten. Add it to the validation tests first, then write the
  handler. Easier to keep correct that way.
- The `REGISTERED_TOOL_NAMES` constant in `mcp_server.py` should be
  populated *next to* the `@mcp.tool(...)` decorators, not by
  reflecting on the FastMCP server object at startup. The
  conditional registrations (`if not Config.READ_ONLY:` etc.) make
  reflection lie about the catalog when the server runs in
  read-only mode. The catalog needs to be the universe of *names*,
  not the universe of currently-registered tools.
- The UI port from `9181f292` is the biggest single chunk of work
  here. Keep the structure, drop the per-mount permission flags,
  swap the path strings for store-picker controls. Don't rewrite —
  the design is good, it just needs the surgery described above.
- The audit `changed_fields` on PATCH is a list of top-level field
  names, not a full diff. Computing a full diff of content_roots is
  expensive and not actually useful in an audit log — the row
  itself is the truth, and you can run blame against the DB if you
  really want timeline context.
- The Alembic migration touches four new tables and one back-ref.
  Use SQLAlchemy's autogenerate as a starting point, but
  hand-review the output — autogenerate has a history of getting
  cascade and check-constraint specifics wrong. Constraint names
  matter for downgrade correctness.
