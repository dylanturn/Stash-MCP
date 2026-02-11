# Cloudflare Tunnel + Auth0 Production Deployment

This guide covers deploying Stash-MCP through a Cloudflare Tunnel with split
authentication:

- **`/mcp`** — FastMCP's built-in OAuth (Auth0 via OIDC)
- **Everything else** (`/ui`, `/docs`, REST API) — Cloudflare Access backed by Auth0

## Prerequisites

- A Cloudflare account with Zero Trust enabled
- An Auth0 tenant
- Docker and Docker Compose installed on the deployment host
- The `stash-mcp:latest` image built locally (`docker build -t stash-mcp:latest .`)

## Compose Files

The default `docker-compose.yml` is a local-only setup.  The Cloudflare
infrastructure lives in a separate overlay file so the local default is
unchanged.

```bash
# Local only
docker compose up -d

# With Cloudflare Tunnel
docker compose -f docker-compose.yml -f docker-compose.cloudflare.yml up -d

# Multiple stacks on one VM (each with its own .env)
docker compose -p stash-team-a -f docker-compose.yml -f docker-compose.cloudflare.yml up -d
docker compose -p stash-team-b -f docker-compose.yml -f docker-compose.cloudflare.yml up -d
```

Each stack gets its own `.env` with its `TUNNEL_TOKEN` and OAuth vars.  No port
bindings in the cloudflare overlay — `cloudflared` connects outbound and routes
to `stash:8000` over the internal Docker network.

---

## Auth0 Configuration

### 1. Create an Auth0 Application (for Cloudflare Access)

In the Auth0 dashboard:

1. Go to **Applications → Create Application**
2. Type: **Regular Web Application**
3. Name: `Stash Cloudflare Access` (or a per-stack name)
4. Note the **Client ID** and **Client Secret**
5. Under **Settings → Allowed Callback URLs**, add:
   `https://<team-name>.yourdomain.com/cdn-cgi/access/callback`
6. Under **Settings → Allowed Logout URLs**, add:
   `https://<team-name>.yourdomain.com`

### 2. Create a separate Auth0 Application (for FastMCP OAuth on `/mcp`)

This is a separate application because it uses a different callback URL
(FastMCP's `/auth/callback`).

1. Go to **Applications → Create Application**
2. Type: **Regular Web Application**
3. Name: `Stash MCP OAuth`
4. Note the **Client ID** and **Client Secret**
5. Under **Settings → Allowed Callback URLs**, add:
   `https://<team-name>.yourdomain.com/mcp/auth/callback`
6. Under **Settings → Allowed Logout URLs**, add:
   `https://<team-name>.yourdomain.com`

### 3. Auth0 API (optional, for audience validation)

If you want to scope tokens to Stash specifically:

1. Go to **APIs → Create API**
2. Name: `Stash MCP`
3. Identifier (audience): `https://stash.yourdomain.com`
4. This audience value goes into the FastMCP env vars if the provider supports it

---

## Cloudflare Zero Trust Configuration

### 1. Create a Tunnel (per stack)

In the Zero Trust dashboard ([one.dash.cloudflare.com](https://one.dash.cloudflare.com)):

1. Go to **Networks → Tunnels → Create a tunnel**
2. Name: `stash-team-a` (or whatever identifies this stack)
3. Copy the **tunnel token** — this goes in the stack's `.env` as `TUNNEL_TOKEN`
4. Add a public hostname:
   - **Subdomain**: `stash-team-a`
   - **Domain**: `yourdomain.com`
   - **Service type**: HTTP
   - **URL**: `stash:8000`

### 2. Add Auth0 as an Identity Provider

In the Zero Trust dashboard:

1. Go to **Settings → Authentication → Login methods → Add new**
2. Select **OpenID Connect**
3. Configure:
   - **Name**: Auth0
   - **App ID**: Client ID from the Auth0 Cloudflare Access application (step 1)
   - **Client Secret**: Client Secret from the same application
   - **Auth URL**: `https://<your-tenant>.auth0.com/authorize`
   - **Token URL**: `https://<your-tenant>.auth0.com/oauth/token`
   - **Certificate URL**: `https://<your-tenant>.auth0.com/.well-known/jwks.json`
   - **OIDC Claims**: leave defaults (sub, email, email_verified, name)
4. Click **Test** and **Save**

### 3. Create Access Applications

Three applications, evaluated in order of path specificity:

#### Application A — Bypass `/mcp`

FastMCP handles auth on this route.

1. **Access → Applications → Add Application → Self-hosted**
2. Application name: `Stash MCP endpoint`
3. Application domain: `stash-team-a.yourdomain.com`
4. Path: `/mcp`
5. Add policy:
   - Name: `Bypass`
   - Action: **Bypass**
   - Include: Everyone

#### Application B — Bypass `/.well-known/oauth-authorization-server`

MCP clients need to reach this for OAuth discovery.

1. **Access → Applications → Add Application → Self-hosted**
2. Application name: `Stash OAuth discovery`
3. Application domain: `stash-team-a.yourdomain.com`
4. Path: `/.well-known/oauth-authorization-server`
5. Add policy:
   - Name: `Bypass`
   - Action: **Bypass**
   - Include: Everyone

#### Application C — Protect everything else with Auth0

Covers `/ui`, `/docs`, REST API endpoints.

1. **Access → Applications → Add Application → Self-hosted**
2. Application name: `Stash UI`
3. Application domain: `stash-team-a.yourdomain.com`
4. Path: *(leave empty — catches all unmatched paths)*
5. Identity providers: Select **Auth0** only
6. Add policy:
   - Name: `Allow company`
   - Action: **Allow**
   - Include: Emails ending in `@yourcompany.com` (or whatever rule fits)

### 4. (Optional) Terraform

All of the above can be managed as code with the Cloudflare Terraform provider.
A `cloudflare.tf` and per-stack `.tfvars` would cover the tunnel, DNS record,
Access IdP, and all three Access applications with policies.  This is
recommended if managing multiple stacks.

---

## Per-Stack `.env` File

```bash
# Cloudflare Tunnel
TUNNEL_TOKEN=eyJhIjoiYWJjMTIz...

# FastMCP OAuth (Auth0 via OIDC)
# Uses the separate "Stash MCP OAuth" Auth0 application
FASTMCP_SERVER_AUTH=fastmcp.server.auth.providers.auth0.Auth0Provider
FASTMCP_SERVER_AUTH_AUTH0_CONFIG_URL=https://<your-tenant>.auth0.com/.well-known/openid-configuration
FASTMCP_SERVER_AUTH_AUTH0_CLIENT_ID=<mcp-app-client-id>
FASTMCP_SERVER_AUTH_AUTH0_CLIENT_SECRET=<mcp-app-client-secret>
FASTMCP_SERVER_AUTH_AUTH0_AUDIENCE=https://stash.yourdomain.com
FASTMCP_SERVER_AUTH_AUTH0_BASE_URL=https://stash-team-a.yourdomain.com
FASTMCP_SERVER_AUTH_AUTH0_REQUIRED_SCOPES=openid,email
```

See [`.env.example`](../.env.example) for all available variables.

---

## Verification

After deploying a stack:

| # | Command / Action | Expected Result |
|---|-----------------|-----------------|
| 1 | `curl https://stash-team-a.yourdomain.com/ui` | Redirects to Auth0 login (Cloudflare Access) |
| 2 | `curl https://stash-team-a.yourdomain.com/.well-known/oauth-authorization-server` | Returns FastMCP OAuth discovery JSON (no auth challenge) |
| 3 | `curl https://stash-team-a.yourdomain.com/mcp` | Returns 401 from FastMCP (not Cloudflare), expects OAuth token |
| 4 | Connect with an MCP client using OAuth | Completes Auth0 login flow, tools accessible |
| 5 | `curl https://stash-team-a.yourdomain.com/docs` | Redirects to Auth0 login (Cloudflare Access) |
