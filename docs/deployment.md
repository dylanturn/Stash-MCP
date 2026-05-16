# Deployment

Stash-MCP ships in two deployment shapes. Pick **one** when you set up an
instance — there is no in-place migration between them.

| Mode | `STASH_AUTH_ENABLED` | Identity | URL shape | Use when |
|------|----------------------|----------|-----------|----------|
| Auth-disabled (legacy) | `false` (default) | Single trusted principal — protect with a reverse proxy or VPN | `/api/*`, `/mcp/`, `/ui` | Solo / homelab / internal-only |
| Auth-enabled | `true` | OIDC (per-user sessions + bearer JWTs) plus issued API tokens | `/api/<tenant>/<store>/*`, `/mcp/<tenant>/<store>/`, `/ui/<tenant>/<store>/` | Public deployment, multi-user, multi-tenant |

> **Migration posture: none.** Once a deployment goes auth-enabled, the
> on-disk layout under `STASH_CONTENT_ROOT` becomes `<tenant_id>/<store_slug>/`
> and the server refuses to start if it doesn't already look that way.
> Don't flip an existing legacy deployment to auth-enabled in place — stand
> up a new instance and rsync your content under the new layout.

## Auth-disabled deployment

This is the original Stash-MCP shape. Nothing about it changes; see the
quick start in [README.md](../README.md). Required env vars:

| Variable | Default | Purpose |
|----------|---------|---------|
| `STASH_CONTENT_ROOT` | `/data/content` | Content storage root |
| `STASH_HOST` / `STASH_PORT` | `0.0.0.0` / `8000` | Bind address |

Operate behind a reverse proxy if you expose it beyond a trusted network.
The SPA at `/ui` is **not** supported in this mode — use the
server-rendered HTML UI mounted at `/ui` by `stash_mcp/ui.py`. Auth-enabled
deployments use the React SPA.

## Auth-enabled deployment

Auth-enabled mode adds:

* An OIDC client that issues browser session cookies on successful login.
* A bearer-JWT path for OIDC-issued access tokens (machine clients that
  speak OIDC).
* Stash-issued opaque API tokens for MCP clients that don't.
* Per-tenant + per-store routing — every API/MCP request carries a
  tenant and store slug in the path.

### Required env vars

| Variable | Notes |
|----------|-------|
| `STASH_AUTH_ENABLED=true` | Switches the whole app into auth mode |
| `STASH_DATABASE_URL` | SQLAlchemy URL. `sqlite+aiosqlite:///./stash.db` for dev; `postgresql+asyncpg://...` for prod |
| `STASH_AUTH_TOKEN_HMAC_KEYS` | Comma-separated HMAC keys. First entry is the active signer; trailing entries are accepted on verify (rotation) |
| `STASH_SESSION_SECRET` | 32+ random bytes; signs the browser session cookie |
| `STASH_OIDC_DISCOVERY_URL` | e.g. `https://accounts.google.com/.well-known/openid-configuration` |
| `STASH_OIDC_CLIENT_ID` / `STASH_OIDC_CLIENT_SECRET` | Issued by your IdP |
| `STASH_OIDC_ADMIN_GROUP` | Group claim value that grants tenant-admin role |
| `STASH_OIDC_GROUPS_CLAIM` | Defaults to `groups`; override for IdPs that use a different claim |
| `STASH_CONTENT_ROOT` | Must be empty or already `<tenant_id>/<store_slug>/`-shaped at boot |

Optional:

| Variable | Default | Notes |
|----------|---------|-------|
| `STASH_OIDC_AUDIENCE` | (unset) | Required if your IdP issues access tokens with an `aud` claim that isn't the client_id |
| `STASH_OIDC_SCOPES` | `openid profile email groups` | Override only if your IdP uses different scope names |
| `STASH_SESSION_MAX_AGE` | `43200` (12h) | Session cookie lifetime in seconds |
| `STASH_SESSION_COOKIE_NAME` | `stash_session` | Cookie name |
| `STASH_INSECURE_COOKIES` | `false` | Set `true` to drop the `Secure` flag for `http://` dev |

The server validates these at startup and aborts with a clear message
listing what's missing. See `Config.validate_auth_config()` in
`stash_mcp/config.py` for the source of truth.

### Postgres setup

For production use Postgres. Stash uses `asyncpg`; install it as part of
the deployment (it's pulled in by the main package).

```bash
createdb stash
export STASH_DATABASE_URL=postgresql+asyncpg://stash:stash@db:5432/stash
uv run alembic upgrade head
```

Alembic migrations live under `alembic/`. Re-run `alembic upgrade head`
on every deploy.

### Dev IdP (dex) for local testing

A docker-compose file is provided that runs [dex](https://dexidp.io) with
a single preseeded user. Use it to exercise the OIDC flow without standing
up a real IdP:

```bash
docker-compose -f docker-compose.dev-idp.yml up -d
# dex listens on http://localhost:5556/dex
# default user: stash@example.com / password
```

Point your local Stash at it:

```bash
export STASH_AUTH_ENABLED=true
export STASH_DATABASE_URL=sqlite+aiosqlite:///./stash.db
export STASH_OIDC_DISCOVERY_URL=http://localhost:5556/dex/.well-known/openid-configuration
export STASH_OIDC_CLIENT_ID=stash-mcp
export STASH_OIDC_CLIENT_SECRET=dev-secret
export STASH_OIDC_ADMIN_GROUP=stash-admins
export STASH_SESSION_SECRET=$(openssl rand -hex 32)
export STASH_AUTH_TOKEN_HMAC_KEYS=$(openssl rand -hex 32)
export STASH_INSECURE_COOKIES=true
uv run alembic upgrade head
uv run -m stash_mcp.main
```

Then visit `http://localhost:8000/ui` and the SPA will bounce you through
`/auth/login` to dex.

### Provisioning tenants and stores

Once the server is running, use the admin CLI to provision your first
tenant and store:

```bash
uv run stash-mcp tenant create --slug acme --display-name "Acme Inc"
uv run stash-mcp store create --tenant acme --slug docs --display-name "Docs"
# Or, clone an existing repo into a store:
uv run stash-mcp store create --tenant acme --slug docs \
  --git-remote https://github.com/acme/docs.git
```

Stores live at `STASH_CONTENT_ROOT/<tenant_id>/<store_slug>/`. The
server only reads/writes inside these directories.

### MCP clients and API tokens

MCP clients that don't speak OIDC (e.g. Claude Desktop) authenticate with
a Stash-issued API token. Mint one from the web UI:

1. Sign in at `https://your-host/ui` (browser bounces through OIDC).
2. Navigate to `/ui/account/tokens`.
3. Click **New token**, name it (e.g. `laptop-claude-desktop`), pick
   scopes, copy the token.
4. Configure your MCP client with the token as a bearer header against
   `https://your-host/mcp/<tenant>/<store>/`.

See [USAGE.md](../USAGE.md#mcp-with-an-api-token) for client config
examples.

### Reverse proxy

With auth enabled, a reverse proxy is no longer required for *security* —
the application enforces it. You still want one for TLS termination and
rate-limiting. The minimum responsibilities:

* Terminate TLS.
* Pass through `Authorization`, cookies, and the request body unchanged.
* Don't strip `If-Match` or `ETag` headers (the SPA uses them for
  conditional writes).

## Choosing a deployment shape

| Question | Auth-disabled | Auth-enabled |
|----------|----------------|--------------|
| Single trusted user / homelab? | ✓ | overkill |
| Multiple users? | ✗ | ✓ |
| Multi-tenant (orgs that can't see each other)? | ✗ | ✓ |
| Public internet exposure? | risky | ✓ |
| OIDC infrastructure (Google Workspace, Okta, dex)? | not needed | required |
| Migration story off of it later? | one-way move to auth-enabled means rsync, not in-place | n/a |
