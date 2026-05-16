# Auth & multi-tenancy for Stash-MCP

This directory holds the design specs for the auth + multi-tenant + multi-store
initiative. Each spec is a self-contained chunk of work for a single Claude
Code session. They are sequenced: later specs assume the earlier ones have
landed.

## Why we're doing this

Stash-MCP today assumes a single principal per server — typically protected by
running behind a reverse proxy or trusted network. The next phase needs:

- **Authenticated access** so Stash can run on the open internet for ReasonFlow
  and other dogfood consumers.
- **Multi-tenant isolation** so multiple users/orgs can share one Stash
  deployment without seeing each other's content.
- **Multiple stores per tenant** so a single tenant can have several git-backed
  content repos (e.g. team-A docs, team-B docs, personal scratch).

## Locked design decisions

These were settled during scoping on 2026-05-15 and are not re-litigated in
the specs below. Cite this file if anything tries to deviate.

- **Auth: OIDC-first.** Two providers chained: `OIDCAuthProvider` (validates
  bearer JWTs against IdP JWKS) and `ApiTokenAuthProvider` (validates Stash-
  issued opaque tokens). No basic auth. No password storage.
- **Library:** `authlib` for OIDC client + JWT validation.
- **Dev IdP:** `docker-compose.dev-idp.yml` runs dex with a preseeded test
  user. Tests use a fake JWT signer — no IdP required for unit tests.
- **Admin authorization:** Pure group-claim driven. Two env vars —
  `STASH_OIDC_GROUPS_CLAIM` and `STASH_OIDC_ADMIN_GROUP`. On every OIDC
  login, the user's `memberships` row is refreshed from the JWT claim. No
  CLI bootstrap, no admin-email allow-list, no escape hatch.
- **Tenant + store model:** A tenant owns 1..N stores. Each store is its own
  git repo at `CONTENT_DIR/<tenant_id>/<store_slug>/`. `FileSystem`,
  `GitBackend`, and `TransactionManager` are instantiated per store.
- **Persistence:** SQLAlchemy 2.x async + Alembic. SQLite for dev, Postgres
  for prod — swap via `DATABASE_URL`. Auth state in SQL; content stays
  file/git.
- **Token hashing:** HMAC-SHA256 with **versioned keys**. `api_tokens.key_version`
  smallint stores which key hashed each row. `STASH_AUTH_TOKEN_HMAC_KEYS` is
  a comma-separated list — the first entry is the active signer, the rest
  are accepted on verify so a rotation doesn't invalidate live tokens. New
  rows always write `key_version=<index of first key>`. Rolling forward is
  prepend-and-restart; rolling back the list drops the keys at the end.
- **Membership precedence:** OIDC-group-derived and manual memberships
  collide on `UNIQUE (user_id, tenant_id)`. **Manual wins.** On OIDC
  login, if a `source='manual'` row exists for the user on a tenant, the
  group-derived upsert is *skipped* (no role change, no source flip).
  Group churn is therefore invisible to manually-granted users — this is
  intentional: manual grants are an escape hatch and shouldn't silently
  flip back when the IdP's groups change.
- **Audit log:** an `audit_events` table in the v1 schema records token
  issuance/revocation, manual membership grants, OIDC group-derived role
  changes, store provisioning, and store deletion. Append-only, no UI in
  v1 — consumed via SQL by operators. Schema in `01-persistence.md`.
- **Routing:** Path-based. `/mcp/<tenant>/<store>/` and `/api/<tenant>/<store>/*`.
  Both slugs are on the wire — tenant is *not* inferred from the principal,
  because a user may be a member of multiple tenants.
- **Migration posture: none.** Pre-auth deployments stay
  `STASH_AUTH_ENABLED=false` forever. Once auth is on, `CONTENT_DIR` *must*
  already be `<tenant>/<store>/`-shaped or the server refuses to start.

## Spec chain

| # | Spec | Adds | Depends on |
|---|---|---|---|
| 01 | [Persistence + auth types](01-persistence.md) | `stash_mcp/db/`, `stash_mcp/auth/` (types only), Alembic baseline | — |
| 02 | [Providers + middleware + dev IdP](02-providers-middleware.md) | `OIDCAuthProvider`, `ApiTokenAuthProvider`, `SessionCookieAuthProvider`, ASGI middleware, `current_principal()` contextvar, `STASH_AUTH_ENABLED`, `docker-compose.dev-idp.yml` (dex) | 01 |
| 03 | [StoreRegistry + per-store content layer](03-store-registry.md) | `StoreRegistry`, per-store `FileSystem`/`GitBackend`/`TransactionManager`, `CONTENT_DIR` shape invariant | 01 |
| 04 | [Per-store HTTP routing](04-routing.md) | `/mcp/<tenant>/<store>/`, `/api/<tenant>/<store>/*`, store-resolver middleware, `current_store()` contextvar | 02, 03 |
| 05 | [Admin endpoints, CLI, OIDC callback, UI bridge](05-admin-cli.md) | `/auth/login`, `/auth/callback`, `/auth/tokens`, `/admin/*`, `stash-mcp tenant/store` CLI, minimal `stash_mcp/ui.py` redirect | 02, 03, 04 |
| 06 | [SPA + UI client wiring](06-ui-clients.md) | `stash_ui` fetch wrapper, store-scoped `API_BASE`, `StoreContext`, `/account/tokens` page; docs updates | 04, 05 |

OIDC group → tenant-membership mapping is intentionally **out of scope** for
v1. The `memberships.source` column is in the schema so we can add it later
without a migration, but admin-via-group is the only group-driven role v1
ships.

## Working with these specs

Each spec is structured the same way:

- **Goal** — what this chunk accomplishes and what's deliberately deferred.
- **Files added / modified** — concrete paths.
- **Design** — schema DDL, function signatures, env var names. Code-grounded
  enough that a Claude Code session can act on it without further design
  decisions.
- **Test plan** — what to write and where.
- **Acceptance** — observable criteria the chunk is done.
- **Open questions** — anything still worth thinking through. If empty, none.

When kicking off a Claude Code session, point it at the relevant spec file:
"Implement `docs/auth/01-persistence.md` end-to-end, then stop. Don't touch
anything outside the file/modify list."
