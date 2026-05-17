# 01 — Tenant-admin scope and stores CRUD

## Goal

Let a tenant admin manage the stores inside *their own* tenant from the
UI without needing global-admin (admin-on-`default`) rights. After this
spec lands, the Stores tab in the Organization Settings modal stops
being read-only for tenant admins: they can create stores, rename them,
change their git remote, and delete them.

Tenant metadata itself (display name, slug) stays read-only here — that
remains a global-admin-only operation via `/admin/tenants/{id}`. The
General tab in the modal does not change.

This is the first of four specs (01–04) that together let a tenant admin
fully manage the MCP-server surface their tenant exposes. 01 is the
prerequisite auth-shape change. 02 adds the MCP-server-config CRUD on
top of it. 03 wires tokens to configs. 04 turns it on at runtime. 01–03
are independently mergeable; 04 depends on 02+03.

## Out of scope

- Tenant CRUD. Creating/renaming/deleting tenants stays global-admin
  only. The `/admin/tenants` surface is untouched.
- User CRUD, membership CRUD, audit-log read. Same reason — these are
  global-admin concerns. A tenant admin who needs to invite someone goes
  through their IdP group, or asks a global admin for a manual
  membership.
- Cross-tenant admin. A user who is an admin on tenant A still gets 403
  on tenant B's endpoints.
- MCP server configs. That's 02.

## Files added

```
stash_mcp/tenant_admin/__init__.py
stash_mcp/tenant_admin/routes.py             # /tenants/{tenant_id}/stores/*
stash_mcp/stores/admin_ops.py                # shared store provisioning + delete helpers
tests/tenant_admin/__init__.py
tests/tenant_admin/test_stores_routes.py
tests/tenant_admin/test_require_tenant_admin.py
```

## Files modified

```
stash_mcp/admin/dependencies.py              # add require_tenant_admin
stash_mcp/admin/routes.py                    # delegate store create/delete bodies to admin_ops
stash_mcp/main.py                            # mount tenant_admin router; add /tenants prefix to AuthMiddleware allowlist
stash_mcp/errors.py                          # no new error types; reuse StoreAlreadyExists/StoreNotFound/etc.
stash_ui/src/app/components/OrganizationSettingsModal.tsx
                                             # the Stores tab gains a "New store" button,
                                             # row-level edit, and delete; gated on role === 'admin'
stash_ui/src/api/admin.ts                    # typed wrappers for the new endpoints
docs/mcp/README.md                           # extend the spec chain table
USAGE.md                                     # tenant-admin walkthrough
```

## Design

### Why a parallel router

The natural impulse is to widen `require_admin` to accept "admin on
whatever tenant the path names." Don't. The global-admin surface in
`/admin/*` covers things tenant admins shouldn't touch — tenant CRUD,
user CRUD, the audit log, cross-tenant memberships. Keeping the two
surfaces separate at the router level means an accidental delete of a
guard in one place doesn't expose tenant-admin to the rest of the admin
API.

The new surface lives under `/tenants/{tenant_id}/*`, mirrors the shape
of `/admin/tenants/{tenant_id}/*`, and gates on `require_tenant_admin`.
Existing global-admin endpoints continue to work for users who are
admins on `default` — a global admin still uses `/admin/*`, not the new
surface.

### `require_tenant_admin`

Same shape as `require_admin` (`stash_mcp/admin/dependencies.py`), just
scoped to the path's `tenant_id` instead of `default`.

```python
# stash_mcp/admin/dependencies.py

async def require_tenant_admin(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Reject the request unless the caller is admin on *this* tenant."""
    principal = current_principal()
    if principal is None:
        raise Unauthenticated("tenant-admin endpoints require authentication")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant {tenant_id} not found")
    if not principal.has_role_on(tenant.id, "admin"):
        raise Forbidden("admin role required on this tenant")
    return principal
```

FastAPI's path-param resolution binds `tenant_id` for us, the same way
the existing tenant-store handlers receive it. No new auth machinery —
`Principal.has_role_on` is the same call `require_admin` makes today,
just with a different `tenant_id`.

### Shared store ops

Factor the bodies of the existing `create_store` and `delete_store` in
`stash_mcp/admin/routes.py` into a new module so both routers call the
same code. Drift between the global-admin and tenant-admin
implementations of "provision a store" is the exact kind of thing that
breaks subtly in production six months from now.

```python
# stash_mcp/stores/admin_ops.py

async def provision_store(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant: Tenant,
    body: StoreCreate,
) -> Store:
    """Create the DB row, audit, then call the registry to provision on disk.
    On disk failure, deletes the row before re-raising. Idempotent on
    StoreAlreadyExists."""

async def deprovision_store(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant: Tenant,
    slug: str,
) -> None:
    """Invalidate the registry, rmtree the on-disk repo, audit, delete the row."""

async def rename_store(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant: Tenant,
    store: Store,
    body: StoreUpdate,
) -> Store:
    """Update display_name and/or git_remote_url and/or git_branch.
    Slug is not editable — it's part of the mount path."""
```

The existing `/admin/tenants/{tenant_id}/stores` handlers shrink to a
few lines each — fetch the tenant, call the op, return the response
model. Audit rows are written inside the op, so the actor is whoever
was passed in (global admin from `/admin/*`, tenant admin from
`/tenants/*`).

### New endpoints

All gated by `Depends(require_tenant_admin)`. Same response shapes as
the existing `/admin` endpoints — `StoreInfo`, `list[StoreInfo]`, 204
on delete — so the UI can reuse the existing `StoreInfo` type. Same
Problem Details for errors (`StoreAlreadyExists`, `StoreNotFound`,
`ConfirmationRequired`, `TenantNotFound`).

```
GET    /tenants/{tenant_id}/stores                 → list[StoreInfo]
POST   /tenants/{tenant_id}/stores                 → StoreInfo
GET    /tenants/{tenant_id}/stores/{slug}          → StoreInfo
PATCH  /tenants/{tenant_id}/stores/{slug}          → StoreInfo
DELETE /tenants/{tenant_id}/stores/{slug}?confirm=true → 204
```

`StoreCreate` keeps its current shape from `admin/routes.py`. New:

```python
class StoreUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    git_remote_url: str | None = Field(default=None)
    git_branch: str | None = Field(default=None)
```

All fields optional; the op applies whichever are present. Slug is not
in the body — it stays in the path and is immutable. Trying to rename
a slug means creating a new store and deleting the old one, which is
explicitly a user decision, not a one-click button.

Renaming `git_remote_url` or `git_branch` on a live store has real
side effects (next sync pulls from a different place). The op records
both old and new values in the audit detail so a rollback path exists.
It does *not* re-clone. If the admin needs a fresh clone, they delete
and recreate.

Audit actions, all written inside the op:

| Action | Target kind | Detail |
|---|---|---|
| `store.provisioned` | `store` | `{tenant_slug, slug, git_remote_url, git_branch}` |
| `store.renamed` | `store` | `{old, new}` per changed field |
| `store.deleted` | `store` | `{tenant_slug, slug}` |

`store.renamed` is new; the others already exist. The audit row's
`actor_user_id` will be the tenant admin's user, distinguishable from
global-admin actions by the actor's role on the target tenant.

### Middleware allowlist

`/tenants/*` is *not* a public prefix — it requires auth. The current
`StoreResolverMiddleware` only fires on `/mcp/<tenant>/<store>/*` and
`/api/<tenant>/<store>/*`, so a `GET /tenants/{id}/stores` doesn't go
through it. Good — there's no current store to resolve, and the
tenant_id in the path is what `require_tenant_admin` operates on.

`StashAuthMiddleware` runs on everything not in `public_prefixes`, and
the new prefix should *not* be added there. Confirm in tests that an
unauthenticated request to `/tenants/{id}/stores` returns 401, not 200.

### UI: the Stores tab gains buttons

The Stores tab in `OrganizationSettingsModal.tsx` (post-`d7cf10f`)
already lists stores from `StoreContext`. Changes:

- **New store** button in the tab header, only rendered when the active
  store's role is `admin`.
- Each row gets an edit pencil and a trash icon, same gating.
- Clicking edit opens a small inline form for display name + git remote
  + git branch. Slug shows as muted, read-only, with the mount path
  underneath as today.
- Clicking trash opens a typed-slug-guard confirm (must type the store
  slug) before issuing `DELETE` with `?confirm=true`.
- On any mutation, refresh the tab's data via `StoreContext.refresh()`
  (or a tab-local refetch). Don't optimistically mutate the context —
  the server is the source of truth for provisioning state, especially
  because create can fail after the row exists (disk provisioning).

`stash_ui/src/api/admin.ts` (a sibling of the existing fetch helpers)
gets typed wrappers: `listStores`, `createStore`, `getStore`,
`updateStore`, `deleteStore`. Reuses the same `stashFetch` /
Problem-Details pattern from 06.

### Error mapping (toast targets)

| HTTP | Problem type | UI |
|---|---|---|
| 400 | `/problems/validation` | inline form errors |
| 400 | `/problems/confirmation-required` | shouldn't happen — UI always passes confirm |
| 401 | `/problems/auth/unauthenticated` | redirect to `/auth/login` |
| 403 | `/problems/auth/forbidden` | toast + hide controls (defensive — server is source of truth) |
| 404 | `/problems/tenant/not-found`, `/problems/store/not-found` | toast + close modal |
| 409 | `/problems/store/already-exists` | inline error on the slug field |

### Why not just expand `require_admin`

A previous design draft considered widening `require_admin` to accept
"admin on the path's tenant_id" instead of always checking `default`.
Rejected:

- The same dependency would then guard endpoints that should *not* be
  tenant-admin-callable (tenant CRUD, user CRUD, audit log). Every
  such endpoint would need a hand-rolled "actually require global"
  check, multiplying the surface area.
- The dependency signature changes shape — the global-admin endpoints
  don't have a `tenant_id` path param, so the dependency would need
  branching on whether one is present. Brittle.
- Separating the surfaces makes the audit log read more clearly: a
  global-admin action on `/admin/tenants/X/stores` and a
  tenant-admin action on `/tenants/X/stores` have different paths,
  not just different actors.

The parallel-surface approach is more code but less fragile.

## Test plan

`tests/tenant_admin/test_require_tenant_admin.py`:

- Unauthenticated → 401 with `WWW-Authenticate`.
- Authenticated but not a member of the tenant → 403.
- Member but not admin → 403.
- Admin on a *different* tenant → 403.
- Admin on the path's tenant → passes through.
- Admin on `default` only (a global admin who is not a member of the
  target tenant) → 403. Global admin must use `/admin/*`, not
  `/tenants/*`. This is the surprising case worth a test.

`tests/tenant_admin/test_stores_routes.py`:

- `POST /tenants/{id}/stores` creates a store, audit row exists,
  on-disk path appears.
- `POST` with duplicate slug → 409 `/problems/store/already-exists`.
- `PATCH` updates display name only; row reflects, audit row exists.
- `PATCH` updates git_remote_url + git_branch in one call; audit row
  records both old/new pairs.
- `DELETE` without `?confirm=true` → 400 `/problems/confirmation-required`.
- `DELETE` with confirm → 204, row gone, on-disk path gone, registry
  invalidated, audit row exists.
- `GET` list returns admin's stores in slug order.
- `GET` detail returns 404 with the correct Problem type when missing.

Re-use existing fixtures from `tests/admin/test_admin_routes.py` —
the test database setup, OIDC fake, principal helpers all transfer.

## Acceptance

1. `uv run pytest` clean. `uv run ruff check stash_mcp` clean.
2. Bring up the auth-enabled dev stack
   (`docker-compose.yml + docker-compose.dev-auth.yml + docker-compose.dev-idp.yml`).
3. Log in as a user whose dex membership puts them in `acme` with
   admin role.
4. Open the Organization Settings modal. Stores tab shows the existing
   stores. The "New store" button is visible.
5. Click "New store", create `team-c-docs` with a git remote. Modal
   updates to show the new store. Audit row exists in the DB.
6. Edit `team-c-docs`'s display name. Row updates; modal reflects.
7. Delete `team-c-docs` with the typed-slug confirm. Row gone; on-disk
   path gone.
8. Log in as a non-admin member of `acme`. Open the modal. Stores tab
   shows stores but no "New store" button, no per-row edit/delete.
9. As a global admin who is *not* an admin on `acme`, the modal is
   read-only for `acme` — global admins manage tenants from elsewhere
   (out of scope for this UI).

## Open questions

- **Renaming `git_remote_url` semantics.** Today's `git_backend`
  reads the remote URL from the rendered git config on disk. Patching
  `git_remote_url` on the DB row doesn't change the on-disk repo. The
  op should either (a) also run `git remote set-url` on the live repo,
  or (b) leave it and let the next manual sync pick it up via the
  registry's reload path. (a) is more correct but adds a subprocess
  call. (b) is simpler. **Open: which?** Lean (a) — the DB and the
  disk should not silently disagree.
- **Tenant slug rename.** Out of scope here, but worth noting: a tenant
  slug rename invalidates the mount path `/mcp/<tenant>/<store>/*` and
  every existing API token that addresses it. Global-admin op, but
  needs its own treatment.

## Notes for the Claude Code session

- The new dependency, router, and ops module total well under 500
  lines of Python. Don't be tempted to refactor adjacent admin code
  while you're in there; keep the diff small and reviewable.
- `stash_mcp/stores/admin_ops.py` is the right home for the shared
  bodies. Resist the urge to put them under `tenant_admin/` — they
  belong to the stores domain, not the admin surface.
- Reuse the existing `_audit` helper from `admin/routes.py` — copy it
  into `admin_ops.py` as a module-private function and have both
  routers' bodies call into the ops module. Do *not* import from
  `stash_mcp.admin.routes` in the new module (circularity risk).
- Frontend testing follows the existing posture (manual). No new test
  framework in this PR.
- The modal's typed-slug-guard for delete: copy the pattern from
  whatever existing destructive confirmation uses (likely the user
  delete in the admin-UI design (`docs/design/admin-ui.md`, if landed); otherwise it's a small new
  primitive — three states, "type the slug" / mismatch / match-enabled).
