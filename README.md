<p align="center">
  <img src="assets/logo/stash-mcp-icon-dark.svg" alt="Stash-MCP" width="128" height="128">
</p>

<h1 align="center">Stash-MCP</h1>

<p align="center">
  A file-backed content server that exposes documents to AI agents via the Model Context Protocol (MCP).<br>
  Stash content as files, serve them as MCP resources, and let agents update them through tools.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#features">Features</a> •
  <a href="#usage">Usage</a> •
  <a href="#configuration">Configuration</a> •
  <a href="USAGE.md">Full Docs</a>
</p>

---

## Features

- **Centralized knowledge store** — A single place to stash documentation, notes, specs, and reference material that any connected agent can access
- **File-first design** — Files on disk are the source of truth. No database layer. Inspect, edit, or manage content directly on the filesystem
- **MCP native** — Expose content as MCP resources (read path) and provide MCP tools (write path) so agents can both consume and update documentation
- **Human-friendly UI** — A simple web browser/viewer so humans can manage content alongside agents
- **Simple deployment** — Single Docker container with a volume mount. No external dependencies

## Architecture

```
┌─────────────────────────────────────────────┐
│  Docker Container                           │
│                                             │
│  ┌───────────┐  ┌────────────────────────┐  │
│  │  Web UI   │  │  FastAPI               │  │
│  │  Browser/ │──│  REST API              │  │
│  │  Viewer   │  │                        │  │
│  └───────────┘  └──────────┬─────────────┘  │
│                            │                │
│                 ┌──────────┴─────────────┐  │
│                 │  FastMCP Server        │  │
│                 │  - Resources (read)    │  │
│                 │  - Tools (write)       │  │
│                 │  - Notifications       │  │
│                 └──────────┬─────────────┘  │
│                            │                │
│                 ┌──────────┴─────────────┐  │
│                 │  Filesystem Layer      │  │
│                 │  /data/content/        │  │
│                 └────────────────────────┘  │
│                            │                │
└────────────────────────────┼────────────────┘
                             │
                    Volume Mount
                   ./content:/data/content
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Package management | uv (or pip/venv) |
| MCP server | FastMCP |
| REST API | FastAPI |
| Content UI | HTML/CSS (FastAPI) |
| Containerization | Docker + Compose |
| Persistence | Filesystem (volume mount) |

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Build the image
docker build -t stash-mcp:latest .

# Start the server
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the server
docker-compose down
```

The server will be available at:
- REST API: http://localhost:8000
- UI: http://localhost:8000/ui
- MCP endpoint: http://localhost:8000/mcp
- Health check: http://localhost:8000/api/health

Your content will be persisted in the `./content` directory.

### MCP Client Configuration

To connect Claude Desktop (or other MCP clients) to the running container, add the following to your MCP client configuration:

```json
{
  "mcpServers": {
    "stash": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Local Development

```bash
# Install dependencies with uv
uv sync

# Run the server
uv run -m stash_mcp.server

# Run tests
uv run pytest

# Run linter
uv run ruff check .
```

### Claude Desktop / MCP Client

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "stash": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Stash-MCP", "-m", "stash_mcp.server"],
      "env": {
        "STASH_CONTENT_DIR": "/path/to/your/content"
      }
    }
  }
}
```

## Usage

### MCP Resources (Read)

Connect your MCP client to read documents:

```python
# List all available resources
resources = await client.list_resources()

# Read a specific document
content = await client.read_resource("stash://docs/architecture.md")
```

### MCP Tools (Write)

Agents can create, update, and delete content:

```python
# Create new content
await client.call_tool("create_content", {
    "path": "docs/new-doc.md",
    "content": "# New Document\n\nContent here..."
})

# Update existing content
await client.call_tool("update_content", {
    "path": "docs/existing-doc.md",
    "content": "Updated content..."
})

# Delete content
await client.call_tool("delete_content", {
    "path": "docs/old-doc.md"
})
```

### REST API

Access content via HTTP:

```bash
# List content
curl http://localhost:8000/api/content

# Get specific file
curl http://localhost:8000/api/content/docs/architecture.md

# Create/update file
curl -X PUT http://localhost:8000/api/content/docs/new.md \
  -H "Content-Type: application/json" \
  -d '{"content": "# New Doc"}'

# Delete file
curl -X DELETE http://localhost:8000/api/content/docs/old.md
```

### Web UI

Open http://localhost:8000/ui in your browser to:
- Browse the content tree
- View and edit documents
- Create new files and folders
- Search content (coming soon)

<p align="center">
  <img src="assets/images/user-interface.png" alt="Stash-MCP Web UI" width="800">
</p>

## Configuration

Environment variables:

- `STASH_CONTENT_ROOT` - Content directory path (default: `/data/content`)
- `STASH_HOST` - Server host (default: `0.0.0.0`)
- `STASH_PORT` - Server port (default: `8000`)
- `STASH_LOG_LEVEL` - Logging level (default: `info`)

### OAuth 2.1 Authentication (Optional)

The MCP endpoint (`/mcp`) can be protected with OAuth 2.1 using FastMCP's
built-in provider support. When enabled, MCP clients discover auth endpoints
automatically via `/.well-known/oauth-authorization-server`, handle the
redirect, and attach bearer tokens.

Set the following environment variables to enable OAuth (e.g. GitHub provider):

```bash
FASTMCP_SERVER_AUTH=fastmcp.server.auth.providers.github.GitHubProvider
FASTMCP_SERVER_AUTH_GITHUB_CLIENT_ID=your-client-id
FASTMCP_SERVER_AUTH_GITHUB_CLIENT_SECRET=your-client-secret
FASTMCP_SERVER_AUTH_GITHUB_BASE_URL=https://stash.yourdomain.com
```

FastMCP supports multiple providers (GitHub, Google, Azure, Auth0, Discord,
and others). See the [FastMCP docs](https://gofastmcp.com) for the full list
and their provider-specific env vars.

When no auth env vars are set the server runs without authentication (current
default behavior). The `/ui` and `/docs` endpoints are not affected by MCP
auth; protect those separately at the reverse proxy level if needed.

See [`.env.example`](.env.example) for a complete configuration template.

### Cloudflare Tunnel Deployment

For production deployments you can expose Stash-MCP through a Cloudflare Tunnel
with split authentication: FastMCP OAuth on `/mcp` and Cloudflare Access
(backed by Auth0) on everything else.

```bash
# With Cloudflare Tunnel
docker compose -f docker-compose.yml -f docker-compose.cloudflare.yml up -d

# Multiple stacks on one VM (each with its own .env)
docker compose -p stash-team-a -f docker-compose.yml -f docker-compose.cloudflare.yml up -d
```

See the [Cloudflare + Auth0 deployment guide](docs/cloudflare-auth0-deployment.md)
for full setup instructions including Auth0 configuration and Cloudflare Zero
Trust access policies.

## License

MIT License - see [LICENSE](LICENSE) file for details.
