# 03 — Token scoping to MCP server configs

## Goal

Let users mint API tokens that name a specific MCP-server config (from
02) they intend the token for. Display the chosen config in the
token-list UI. The column and the picker are metadata only in this
spec — no middleware reads them yet. 04 turns it on.

After this lands, a user opening the Account Settings → API Tokens
tab can:

- Pick which MCP-server config the token is for (from the configs
  defined in tenants they're a member of), or leave it unscoped to
  preserve current behaviour.
- See, in the list, which config each existing token is bound to.

Tokens minted before this spec stay unscoped (`mcp_server_id = NULL`)
and behave exactly as they do today.

## Out of scope

- Runtime use of `mcp_server_id`. That's 04. Until 04 lands, a
  token's `mcp_server_id` is inspectable but inert.
- Admin-side token minting (a global admin minting a token for
  another user). The current model is user-mints-own-token; this
  spec doesn't change that.
- Migrating existing tokens. Pre-03 tokens stay `NULL`; the user
  re-mints if they want a scoped one.

## Files added

```
alembic/versions/<rev>_api_token_mcp_server_id.py
tests/auth/test_token_routes_mcp_server.py
```

## Files modified

```
stash_mcp/db/models.py                       # ApiToken.mcp_server_id
stash_mcp/auth/routes.py                     # create_token accepts mcp_server_id; list_tokens returns it
stash_mcp/errors.py                          # McpServerNotFound reused; new McpServerForbidden
stash_ui/src/app/components/TokensManager.tsx  # add server-picker on create form, badge on rows
stash_ui/src/app/components/CreateTokenForm.tsx (inside TokensManager, may be split)
stash_ui/src/api/tokens.ts                   # type widens to carry mcp_server
docs/mcp/README.md                           # spec chain
```

## Design

### Schema change

One nullable column, one FK, one index. `ON DELETE SET NULL` so
deleting a config doesn't cascade-revoke tokens — the tokens become
unscoped instead, which is intentionally noticeable but not
destructive. Rolling back the column is a clean drop.

```python
# stash_mcp/db/models.py — ApiToken extension

class ApiToken(Base):
    ...
    mcp_server_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="SET NULL"),
        nullable=True,
    )
    mcp_server: Mapped[McpServer | None] = relationship()
```

Alembic migration:

- Add the nullable column.
- Add the FK with `ON DELETE SET NULL`.
- Add an index on `(mcp_server_id)` — 04's resolver will query
  tokens by config, infrequently but enough to want the index.

### `ApiToken.scopes` stays the same

`scopes` is still a comma-separated string of `{read, write, admin}`.
This spec deliberately doesn't promote it to JSON or to a join table.
Two reasons:

- Conceptually different from config binding. `scopes` is a
  capability bitmap ("what verbs may this token attempt"); the
  config binding is a foreign-key relationship ("which config does
  this token belong to"). Cramming them together to save a column
  trades clarity for cleverness.
- Migration-free. A new column is a clean add; reshaping `scopes`
  would need a backfill and a parser-version bump.

When 04 lands, both the `scopes` capability bitmap *and* the
`mcp_server.tools` allowlist apply — the effective tool surface is
their intersection. (Spec 04 covers this.)

### Authorization rule on mint

A user may scope a token to any config in any tenant they're a
*member* of (admin or member role, doesn't matter — read-only members
also need scoped tokens). Cross-tenant minting is forbidden: a user
who is not a member of tenant T cannot mint a token bound to a
config in T.

Validation order in `POST /auth/tokens`:

1. `mcp_server_id` is absent or `null` → unscoped token (current
   behaviour). Allowed.
2. `mcp_server_id` is present → load the row; 404 if it doesn't
   exist (`/problems/mcp-server/not-found`).
3. Check `principal.has_role_on(config.tenant_id, "member")`. 403
   `/problems/mcp-server/forbidden` if not — same shape as the
   admin Forbidden, different `type` so the UI can render an
   appropriate message ("you don't have access to this MCP server").
4. Issue the token with `mcp_server_id` set.

Audit detail on `token.created` gains a `mcp_server_id` field when
non-null. No new audit action — the binding is captured on the
existing row.

### `GET /auth/tokens` response shape

Add `mcp_server` to each token in the list:

```json
{
  "id": "...",
  "name": "engineering-agent",
  "scopes": ["read"],
  "created_at": "...",
  "expires_at": "...",
  "last_used_at": null,
  "mcp_server": {
    "id": "...",
    "tenant_slug": "acme",
    "slug": "engineering-docs",
    "name": "Engineering docs"
  }
}
```

`mcp_server` is `null` for unscoped tokens. Including
`tenant_slug` saves a roundtrip — the UI renders the badge as
`acme/engineering-docs` and shouldn't have to fetch the tenant
separately.

The list endpoint joins through `mcp_servers` to populate this. A
second-level join through `tenants` for `tenant_slug` is acceptable
here — tokens are listed once per user and `User → ApiToken` is
typically <50 rows. No N+1 concern.

### UI: server picker on the create form

The Account Settings modal → API Tokens tab → "New token" form
gets one new control: a select labelled **MCP server**. The default
option is `"Any (unscoped, legacy behaviour)"`. The dropdown lists
configs from tenants the user is a member of, grouped by tenant:

```
Any (unscoped)
─────────────
acme
  engineering-docs
  oncall-bot
beta
  staging-readonly
```

Where does the picker source its list? Two options:

1. **A new endpoint** `GET /auth/visible-mcp-servers` that returns
   the union of configs across tenants the user is a member of.
   One round-trip; cleanest.
2. **Synthesize client-side** from `StoreContext.tenants` + a per-
   tenant `GET /tenants/{id}/mcp-servers` call. N+1, but no new
   endpoint.

Lean (1). The endpoint is small, doesn't need admin gate (a
member can see the names of configs in their tenant — the configs
themselves aren't secret), and it pre-sorts by tenant for the
dropdown grouping.

```python
@router.get("/visible-mcp-servers")
async def list_visible_mcp_servers(
    principal: Principal = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
) -> list[VisibleMcpServer]:
    tenant_ids = [tid for tid, _ in principal.tenant_roles.items()]
    rows = (
        await session.execute(
            select(McpServer, Tenant.slug)
            .join(Tenant, Tenant.id == McpServer.tenant_id)
            .where(McpServer.tenant_id.in_(tenant_ids))
            .where(McpServer.enabled.is_(True))
            .order_by(Tenant.slug, McpServer.slug)
        )
    ).all()
    return [...]
```

`enabled.is_(True)` filters out disabled configs — minting a token
for a disabled config is allowed by the binding rule above, but the
UI default doesn't surface them. (A user can still hand-craft the
request, which is fine — the system tolerates it; runtime in 04
will refuse to serve a disabled config.)

### UI: badge on the token list

Each row in the token list shows a small chip after the name:

- `[acme / engineering-docs]` — for scoped tokens.
- nothing — for unscoped tokens. (Don't render an explicit "Any"
  chip; absence is the signal.)

The chip is muted styling (same `--stash-text-secondary` family
used elsewhere). Clicking the chip is a no-op in this spec — there
is no per-config page in the user UI yet.

### Revoke semantics unchanged

`DELETE /auth/tokens/{id}` still sets `revoked_at`. Doesn't care
about `mcp_server_id`. The cascade only goes the other way —
deleting a config nulls the FK on its tokens.

### What 04 will do with this

For context only — not implemented here. 04's resolver will, on
each MCP request:

1. Resolve the token via the existing `ApiTokenAuthProvider`.
2. If the token has `mcp_server_id` set, load the config and the
   resolver pivots from URL-based store resolution to config-based
   composite-store resolution.
3. If `mcp_server_id` is NULL, fall back to today's behaviour —
   URL must contain `<tenant>/<store>`, `StoreResolverMiddleware`
   handles it. This is the bridge that lets unscoped legacy
   tokens keep working through the rollout.

This spec lays the rail; 04 runs the train.

## Test plan

`tests/auth/test_token_routes_mcp_server.py`:

- `POST /auth/tokens` with no `mcp_server_id` → unscoped row, same
  as today.
- `POST` with a valid `mcp_server_id` (config in user's tenant) →
  row with the FK set; response carries `mcp_server` block.
- `POST` with `mcp_server_id` pointing at a config in another
  tenant the user is not a member of → 403
  `/problems/mcp-server/forbidden`.
- `POST` with `mcp_server_id` pointing at a nonexistent config →
  404 `/problems/mcp-server/not-found`.
- `POST` with `mcp_server_id` referencing a disabled config →
  201 (allowed; the binding succeeds). Audit row still records it.
- `GET /auth/tokens` after the above creates returns the
  `mcp_server` block correctly populated for scoped rows and
  `null` for the unscoped.
- `DELETE /admin/tenants/{id}/mcp-servers/{slug}` (from spec 02,
  if 02 has shipped) nulls `mcp_server_id` on bound tokens; the
  tokens remain usable (unscoped). Add this test in 02's suite
  once 03 is also present.
- `GET /auth/visible-mcp-servers`:
  - Member of one tenant with two configs → returns both.
  - Member of two tenants → returns the union, grouped (verifiable
    by sort order).
  - Member of no tenants → returns `[]`.
  - Disabled configs are filtered out.

Add a smoke test that pre-03 tokens (with no `mcp_server_id`)
continue to authenticate and serve requests as before. The
`ApiTokenAuthProvider` shouldn't care about the new column; it
verifies the hash and stuffs scopes into `Principal.claims` as
today. Add an assertion that `mcp_server_id` is *not* in
`Principal.claims` yet — 04 will add it, not this spec.

## Acceptance

1. `uv run pytest` clean; `uv run ruff check stash_mcp` clean.
2. `alembic upgrade head` applies, `alembic downgrade -1` reverses.
3. Bring up the auth-enabled stack. Log in as `acme` user.
4. Open Account Settings → API Tokens → "New token". The form shows
   the MCP-server picker with `acme`'s configs grouped under
   `acme`. Default is `"Any (unscoped)"`.
5. Mint a token bound to `engineering-docs`. The token appears in
   the list with an `[acme / engineering-docs]` chip.
6. Use the new token against the legacy `/mcp/acme/docs` endpoint —
   still works, exactly as it would for an unscoped token. (The
   binding is inert in 03.)
7. As `acme` admin (02), delete `engineering-docs`. The chip on
   the token disappears; the token continues to authenticate.

## Open questions

- **Should disabled configs appear in the picker?** Currently no.
  Argument for yes: a user wants to mint a token in advance for a
  config that's been temporarily disabled. Lean no for v1 — the
  user can flip it back on, then mint.
- **Token-info self-introspection.** `/auth/me` doesn't return the
  current token's `mcp_server_id`. Worth adding? Probably as part
  of 04, once it has runtime meaning.

## Notes for the Claude Code session

- The migration is a single column + FK + index. Resist the urge
  to also rename `scopes` or promote it to JSON in this PR. That
  decision belongs in its own spec if it ever happens.
- The `/auth/visible-mcp-servers` endpoint is *not* admin-gated.
  It's a read of the user's own visibility set. Don't put it
  under `require_admin` or `require_tenant_admin` — just
  `require_principal`.
- The chip in the token list should reuse whatever badge primitive
  the modal already uses (see `OrganizationSettingsModal.tsx`
  post-`d7cf10f` for the `ADMIN` badge in the General tab). Don't
  define a new chip component.
- The list-response shape grows. The existing TypeScript type for
  `TokenInfo` lives in `stash_ui/src/api/tokens.ts` (or wherever
  the tokens-manager imports it from). Widen the type *once* and
  let the new `mcp_server` field be optional.
- The `enabled` filter in `/auth/visible-mcp-servers` is a
  product decision (don't surface disabled configs by default in
  the dropdown). Keep it. Don't add a `?include_disabled=true`
  query param "for completeness" — there's no caller for it yet.
