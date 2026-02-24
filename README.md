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
- **Semantic search** *(opt-in)* — Vector-based semantic search across all stashed content, powered by pluggable embedding providers
- **Git tracking** *(opt-in)* — Expose file history, diffs, and blame via MCP tools; enrich search results with commit metadata; gate writes behind atomic git-committed transactions
- **Read-only mode** — Serve reference docs to agents without allowing any modifications
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
│                 │  - Search (opt-in)     │  │
│                 └──────────┬─────────────┘  │
│                            │                │
│              ┌─────────────┼─────────────┐  │
│              │             │             │  │
│  ┌───────────┴──────┐ ┌────┴──────────┐  │  │
│  │  Filesystem      │ │ Search Engine │  │  │
│  │  /data/content/  │ │ (optional)    │  │  │
│  └──────────────────┘ └───────────────┘  │  │
│              │                           │  │
└──────────────┼───────────────────────────┘  │
               │                              │
      Volume Mount                            │
     ./content:/data/content                  │
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Package management | uv (or pip/venv) |
| MCP server | FastMCP |
| REST API | FastAPI |
| Content UI | HTML/CSS (FastAPI) |
| Semantic search | numpy + Pydantic AI (optional) |
| Containerization | Docker + Compose |
| Persistence | Filesystem (volume mount) |

## Quick Start

### Claude Desktop Extension (One-Click Install)

The easiest way to use Stash-MCP with Claude Desktop is via the `.mcpb` Desktop Extension:

1. Download `stash-mcp.mcpb` from the [latest release](https://github.com/dylanturn/Stash-MCP/releases/latest)
2. Double-click the downloaded `.mcpb` file — Claude Desktop will open the extension installer
3. In the installer, set your **Content Directory** (the folder where your documents live)
4. Optionally enable **Git Tracking** or **Semantic Search**
5. Click **Install** — the Stash icon will appear alongside tool calls in Claude

> **Requirements:** [uv](https://docs.astral.sh/uv/getting-started/installation/) must be installed and available on your PATH.

### Using Docker Compose (Recommended)

```bash
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
- Search content (semantic search when enabled, filename filtering otherwise)

<p align="center">
  <img src="assets/images/user-interface.png" alt="Stash-MCP Web UI" width="800">
</p>

## Configuration

Environment variables:

- `STASH_CONTENT_ROOT` - Content directory path (default: `/data/content`)
- `STASH_HOST` - Server host (default: `0.0.0.0`)
- `STASH_PORT` - Server port (default: `8000`)
- `STASH_LOG_LEVEL` - Logging level (default: `info`)

### Read-Only Mode

Set `STASH_READ_ONLY=true` to disable all write tools. In this mode the server only exposes read resources and tools — agents can read and search content but cannot create, update, delete, or move files, and transaction tools are not registered.

Use read-only mode when serving reference documentation to agents without allowing modifications, or when you want to expose content from a shared volume that other processes own.

```yaml
environment:
  - STASH_READ_ONLY=true
```

### Git Tracking

Set `STASH_GIT_TRACKING=true` to enable git-aware features. The content directory must already be a git repository (i.e. contain a `.git` folder).

**What it enables:**

- Three additional MCP tools: `log_content`, `diff_content`, and `blame_content`
- Search results are enriched with `last_changed_at`, `changed_by`, and `commit_message` metadata
- All writes (when `STASH_READ_ONLY=false`) are automatically committed to the local git repo and gated behind transactions (see [Transactions](#transactions) below)

```yaml
environment:
  - STASH_GIT_TRACKING=true
```

### Git Sync

Set `STASH_GIT_SYNC_ENABLED=true` to have the server periodically pull from a remote git repository. Requires `STASH_GIT_TRACKING=true`.

The server pulls from `STASH_GIT_SYNC_REMOTE`/`STASH_GIT_SYNC_BRANCH` every `STASH_GIT_SYNC_INTERVAL` seconds.

**Authentication:** Provide `STASH_GIT_SYNC_TOKEN` for HTTPS token authentication. The token is injected via a local git credential helper stored at `.git/stash-credential-helper.sh` — no manual credential configuration is required.

```yaml
environment:
  - STASH_GIT_TRACKING=true
  - STASH_GIT_SYNC_ENABLED=true
  - STASH_GIT_SYNC_REMOTE=origin
  - STASH_GIT_SYNC_BRANCH=main
  - STASH_GIT_SYNC_TOKEN=${GITHUB_TOKEN}
```

### Transactions

When `STASH_GIT_TRACKING=true` and `STASH_READ_ONLY=false`, all writes are gated behind transactions. This ensures that a batch of related changes is committed to git as a single atomic unit.

**Workflow:**

1. Call `start_content_transaction` — acquires an exclusive write lock and returns a `transaction_id`
2. Perform any number of `create_content`, `update_content`, `delete_content`, or `move_content` calls — all changes are staged
3. Call `commit_content_transaction` with the `transaction_id` — commits all staged changes to git and releases the lock
4. If something goes wrong, call `abort_content_transaction` — rolls back all staged changes and releases the lock

**Concurrency:** Only one transaction can be active at a time. A second agent attempting `start_content_transaction` will wait up to `STASH_TRANSACTION_LOCK_WAIT` seconds for the lock to be released. If the active transaction is not ended or aborted within `STASH_TRANSACTION_TIMEOUT` seconds, it is automatically aborted.

### Mode Matrix

| `STASH_READ_ONLY` | `STASH_GIT_TRACKING` | `STASH_GIT_SYNC_ENABLED` | Behavior |
|---|---|---|---|
| `false` | `false` | — | Default: writes go directly to disk, no git |
| `true` | `false` | — | Read-only: no write tools registered |
| `false` | `true` | `false` | Writes committed to local git via transactions |
| `true` | `true` | `false` | Read-only + git history/blame tools available |
| `false` | `true` | `true` | Writes committed to git + periodic pulls from remote |
| `true` | `true` | `true` | Read-only + git history/blame + auto-sync from remote |

### Docker Compose Examples

**Read-only documentation server:**
```yaml
environment:
  - STASH_READ_ONLY=true
```

**Read-only with git history access:**
```yaml
environment:
  - STASH_READ_ONLY=true
  - STASH_GIT_TRACKING=true
```

**Auto-syncing from a remote repo:**
```yaml
environment:
  - STASH_READ_ONLY=true
  - STASH_GIT_TRACKING=true
  - STASH_GIT_SYNC_ENABLED=true
  - STASH_GIT_SYNC_REMOTE=origin
  - STASH_GIT_SYNC_BRANCH=main
  - STASH_GIT_SYNC_TOKEN=${GITHUB_TOKEN}
```

**Writable with git-tracked transactions:**
```yaml
environment:
  - STASH_GIT_TRACKING=true
  - STASH_GIT_SYNC_ENABLED=true
  - STASH_GIT_SYNC_TOKEN=${GITHUB_TOKEN}
  - STASH_GIT_AUTHOR_DEFAULT=my-agent <agent@example.com>
```

### Search Configuration

Semantic search is **disabled by default**. Set the following to enable it:

- `STASH_SEARCH_ENABLED` - Enable semantic search (default: `false`)
- `STASH_SEARCH_INDEX_DIR` - Directory for search index persistence (default: `/data/.stash-index`)
- `STASH_SEARCH_EMBEDDER_MODEL` - Pydantic AI embedder model (default: `sentence-transformers:all-MiniLM-L6-v2`)
- `STASH_CONTEXTUAL_RETRIEVAL` - Enable Claude-powered contextual chunk enrichment (default: `false`)
- `STASH_CONTEXTUAL_MODEL` - Model for contextual retrieval (default: `claude-haiku-4-5-20251001`)
- `ANTHROPIC_API_KEY` - Required when contextual retrieval is enabled

When search is enabled, the server exposes:
- An MCP `search_content` tool for agents
- REST endpoints at `/api/search`, `/api/search/status`, and `/api/search/reindex`
- Vector-based search in the Web UI sidebar

Changing `STASH_SEARCH_EMBEDDER_MODEL` between restarts automatically clears the stale index and triggers a full rebuild with the new model.

See [USAGE.md](USAGE.md) for detailed search setup instructions.

### Full Environment Variable Reference

| Env Var | Default | Purpose |
|---|---|---|
| `STASH_CONTENT_ROOT` | `/data/content` | Content directory path |
| `STASH_HOST` | `0.0.0.0` | Server host |
| `STASH_PORT` | `8000` | Server port |
| `STASH_LOG_LEVEL` | `info` | Logging level |
| `STASH_READ_ONLY` | `false` | Disable all write tools |
| `STASH_GIT_TRACKING` | `false` | Enable git read tools and blame-enriched search results |
| `STASH_GIT_SYNC_ENABLED` | `false` | Enable periodic pull from remote (requires `STASH_GIT_TRACKING=true`) |
| `STASH_GIT_SYNC_REMOTE` | `origin` | Remote name to pull from |
| `STASH_GIT_SYNC_BRANCH` | `main` | Branch to sync |
| `STASH_GIT_SYNC_INTERVAL` | `60` | Seconds between pulls |
| `STASH_GIT_SYNC_RECURSIVE` | `false` | Include submodule updates on pull |
| `STASH_GIT_SYNC_TOKEN` | — | HTTPS token for git authentication |
| `STASH_GIT_AUTHOR_DEFAULT` | `stash-mcp <stash@local>` | Fallback committer/author identity |
| `STASH_TRANSACTION_TIMEOUT` | `300` | Seconds before an active transaction is auto-aborted |
| `STASH_TRANSACTION_LOCK_WAIT` | `120` | Seconds a queued agent waits for the transaction lock |
| `STASH_SEARCH_ENABLED` | `false` | Enable semantic search |
| `STASH_SEARCH_INDEX_DIR` | `/data/.stash-index` | Search index directory |
| `STASH_SEARCH_EMBEDDER_MODEL` | `sentence-transformers:all-MiniLM-L6-v2` | Pydantic AI embedder model |
| `STASH_CONTEXTUAL_RETRIEVAL` | `false` | Enable Claude-powered contextual chunk enrichment |
| `STASH_CONTEXTUAL_MODEL` | `claude-haiku-4-5-20251001` | Model for contextual retrieval |
| `ANTHROPIC_API_KEY` | — | Required when contextual retrieval is enabled |

## License

MIT License - see [LICENSE](LICENSE) file for details.
