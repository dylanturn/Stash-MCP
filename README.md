<p align="center">
  <img src="assets/logo/stash-mcp-icon-dark.svg" alt="Stash-MCP" width="128" height="128">
</p>

<h1 align="center">Stash-MCP</h1>

<p align="center">
  A file-backed content server that exposes documents to AI agents via the Model Context Protocol.<br>
  Files on disk are the source of truth — agents read them as MCP resources and update them through MCP tools.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#features">Features</a> •
  <a href="#the-ui">The UI</a> •
  <a href="#usage">Usage</a> •
  <a href="#configuration">Configuration</a> •
  <a href="USAGE.md">Full Docs</a>
</p>

<p align="center">
  <img src="assets/images/ui-markdown-mermaid.png" alt="Stash-MCP rendering a project plan with a Mermaid architecture diagram" width="900">
</p>

---

## Features

- **Centralized knowledge store** — One place to stash documentation, notes, specs, and reference material that any connected agent can access
- **File-first design** — Files on disk are the source of truth. No database layer. Inspect, edit, or manage content directly on the filesystem
- **MCP native** — Content is exposed as MCP resources (read path) and MCP tools (write path), so agents can both consume and update documentation
- **Rich rendering** — Markdown with Mermaid diagrams, syntax-highlighted code, and a built-in OpenAPI viewer for `.json` specs
- **Semantic search** *(opt-in)* — Vector-based search across all stashed content; local embeddings run on ONNX Runtime (no PyTorch/CUDA in the image), with pluggable remote providers
- **Git tracking** *(opt-in)* — File history, diffs, and blame are exposed as MCP tools; writes are gated behind atomic git-committed transactions
- **Read-only mode** — Serve reference docs to agents without allowing any modifications
- **Simple deployment** — Single Docker container with a volume mount. No external dependencies

## The UI

Stash-MCP ships with a browser UI so humans can curate the same content their agents are reading. It uses the same filesystem as the MCP server — anything an agent writes shows up immediately, and anything you write is available to the agent on the next read.

<table>
  <tr>
    <td width="50%"><img src="assets/images/ui-browse-readme.png" alt="File tree with Markdown rendered alongside"></td>
    <td width="50%"><img src="assets/images/ui-markdown-top.png" alt="Markdown rendering with tables and status callouts"></td>
  </tr>
  <tr>
    <td align="center"><sub>Browse the content tree with rendered Markdown</sub></td>
    <td align="center"><sub>Tables, callouts, and headings, with an on-page outline</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="assets/images/ui-openapi.png" alt="OpenAPI 3.0.3 spec rendered as grouped endpoints"></td>
    <td width="50%"><img src="assets/images/ui-edit.png" alt="In-browser editor with raw Markdown and metadata sidebar"></td>
  </tr>
  <tr>
    <td align="center"><sub>OpenAPI <code>.json</code> specs render as a grouped endpoint list</sub></td>
    <td align="center"><sub>Edit content in-browser with a live metadata sidebar</sub></td>
  </tr>
</table>

## Architecture

<p align="center">
  <img src="assets/images/architecture.svg" alt="Stash-MCP architecture diagram" width="820">
</p>

| Component | Technology |
|-----------|------------|
| Package management | uv (or pip/venv) |
| MCP server | FastMCP |
| REST API | FastAPI |
| Content UI | HTML/CSS (FastAPI) |
| Semantic search | numpy + fastembed/ONNX Runtime (local models); Pydantic AI (remote providers) — optional |
| Containerization | Docker + Compose |
| Persistence | Filesystem (volume mount) |

## Quick Start

### Claude Desktop Extension (one-click install)

The fastest way to use Stash-MCP with Claude Desktop is the `.mcpb` Desktop Extension:

1. Download `stash-mcp.mcpb` from the [latest release](https://github.com/dylanturn/Stash-MCP/releases/latest)
2. Double-click the file — Claude Desktop opens the installer
3. Set your **Content Directory** (the folder where your documents live)
4. Optionally enable **Git Tracking** or **Semantic Search**
5. Click **Install** — the Stash icon appears alongside tool calls in Claude

> **Requirements:** [uv](https://docs.astral.sh/uv/getting-started/installation/) must be installed and on your PATH.

### Docker Compose (recommended for servers)

```bash
docker-compose up -d        # start
docker-compose logs -f      # tail logs
docker-compose down         # stop
```

Endpoints:

| Endpoint | Purpose |
|---|---|
| `http://localhost:8000/ui` | Web UI |
| `http://localhost:8000/mcp` | MCP (Streamable HTTP) |
| `http://localhost:8000/api/...` | REST API |
| `http://localhost:8000/api/health` | Health check |

Your content is persisted in `./content`.

### Local development

```bash
uv sync                       # install deps
uv run -m stash_mcp.main      # run the server
uv run pytest                 # run tests
uv run ruff check .           # lint
```

## Connecting MCP clients

Once the server is running, connect Claude Desktop, Claude Code, Cursor, or any other MCP client using one of the methods below.

**Claude Desktop via `mcp-proxy`** — bridges Desktop's stdio transport to Stash-MCP's Streamable HTTP endpoint:

```json
{
  "mcpServers": {
    "stash": {
      "command": "uvx",
      "args": ["mcp-proxy", "--transport", "streamablehttp", "http://localhost:8000/mcp"]
    }
  }
}
```

> **Note:** `uvx` must be on the PATH that Claude Desktop sees. On macOS, GUI apps may not inherit your shell PATH — use the full path if needed (e.g. `/Users/you/.local/bin/uvx`).

`npx mcp-remote` works as an alternative if you have Node.js but not uv:

```json
{
  "mcpServers": {
    "stash": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

**Native Streamable HTTP** (Claude Code, Cursor, anything that supports HTTP MCP natively):

```json
{
  "mcpServers": {
    "stash": { "url": "http://localhost:8000/mcp" }
  }
}
```

Or from the CLI:

```bash
claude mcp add --transport http stash http://localhost:8000/mcp
```

**Local stdio (no container)** — run the server as a stdio subprocess directly from your MCP client config:

```json
{
  "mcpServers": {
    "stash": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Stash-MCP", "-m", "stash_mcp.server"],
      "env": { "STASH_CONTENT_ROOT": "/path/to/your/content" }
    }
  }
}
```

## Usage

### MCP resources (read)

Every file in the content directory is exposed as an MCP resource under the `stash://` scheme:

```python
resources = await client.list_resources()
content   = await client.read_resource("stash://docs/architecture.md")
```

### MCP tools (write)

Agents create, edit, move, and delete content through MCP tools. Modifications are guarded by an optimistic-concurrency check: `read_content` returns the file's SHA-256, which `edit_content`, `overwrite_content`, and `delete_content` require:

```python
await client.call_tool("create_content", {
    "path": "docs/new-doc.md",
    "content": "# New Document\n\nContent here..."
})

result = await client.call_tool("read_content", {"path": "docs/existing-doc.md"})

await client.call_tool("edit_content", {
    "file_path": "docs/existing-doc.md",
    "sha": result.data["sha"],
    "edits": [{"old_string": "old text", "new_string": "new text"}]
})

await client.call_tool("delete_content", {
    "path": "docs/old-doc.md",
    "sha": "<sha from read_content>"
})
```

With git tracking enabled, three additional read tools are exposed: `log_content`, `diff_content`, and `blame_content`. See [Git Tracking](#git-tracking).

### REST API

The same content is accessible over HTTP:

```bash
curl http://localhost:8000/api/content                          # list
curl http://localhost:8000/api/content/docs/architecture.md     # read
curl -X PUT http://localhost:8000/api/content/docs/new.md \
     -H "Content-Type: application/json" \
     -d '{"content": "# New Doc"}'                              # write
curl -X DELETE http://localhost:8000/api/content/docs/old.md    # delete
```

### Web UI

Open `http://localhost:8000/ui` to browse the content tree, view rendered Markdown and OpenAPI specs, edit documents, and search content (semantic search when enabled, filename filtering otherwise). See [The UI](#the-ui) for screenshots.

## Configuration

Core environment variables:

- `STASH_CONTENT_ROOT` — Content directory path (default: `/data/content`)
- `STASH_HOST` — Server host (default: `0.0.0.0`)
- `STASH_PORT` — Server port (default: `8000`)
- `STASH_LOG_LEVEL` — Logging level (default: `info`)

The rest of this section covers optional modes — read-only, git tracking, sync, transactions, search, and metrics — and the full env var reference.

### Read-only mode

Set `STASH_READ_ONLY=true` to disable all write tools. The server then only exposes read resources and tools — agents can read and search content but cannot create, update, delete, or move files, and transaction tools are not registered.

Use read-only mode when serving reference documentation to agents without allowing modifications, or when exposing content from a shared volume that other processes own.

```yaml
environment:
  - STASH_READ_ONLY=true
```

### Git tracking

Set `STASH_GIT_TRACKING=true` to enable git-aware features. The content directory must already be a git repository (contain a `.git` folder).

What it enables:

- Three additional MCP tools: `log_content`, `diff_content`, and `blame_content`
- Search results enriched with `last_changed_at`, `changed_by`, and `commit_message`
- All writes (when `STASH_READ_ONLY=false`) are automatically committed to the local git repo and gated behind transactions (see [Transactions](#transactions))

```yaml
environment:
  - STASH_GIT_TRACKING=true
```

### Git sync

Set `STASH_GIT_SYNC_ENABLED=true` to have the server periodically pull from a remote git repository. Requires `STASH_GIT_TRACKING=true`.

The server pulls from `STASH_GIT_SYNC_REMOTE`/`STASH_GIT_SYNC_BRANCH` every `STASH_GIT_SYNC_INTERVAL` seconds.

**Authentication.** Provide `STASH_GIT_SYNC_TOKEN` for HTTPS token authentication. The token is injected via a local git credential helper at `.git/stash-credential-helper.sh` — no manual credential configuration is required.

**Auto-clone on startup.** Set `STASH_GIT_SYNC_URL` to the HTTPS URL of the repository. When the content directory is empty, the server clones from that URL using `STASH_GIT_SYNC_BRANCH` and `STASH_GIT_SYNC_TOKEN`, then configures the remote as `STASH_GIT_SYNC_REMOTE`. `STASH_GIT_TRACKING` is auto-enabled after a successful clone, so you don't need to set it explicitly.

```yaml
environment:
  - STASH_GIT_SYNC_ENABLED=true
  - STASH_GIT_SYNC_URL=https://github.com/org/content-repo.git
  - STASH_GIT_SYNC_BRANCH=main
  - STASH_GIT_SYNC_TOKEN=${GITHUB_TOKEN}
```

If the content directory already contains a git repository, the clone is skipped and sync proceeds as normal (the remote must already be configured):

```yaml
environment:
  - STASH_GIT_TRACKING=true
  - STASH_GIT_SYNC_ENABLED=true
  - STASH_GIT_SYNC_REMOTE=origin
  - STASH_GIT_SYNC_BRANCH=main
  - STASH_GIT_SYNC_TOKEN=${GITHUB_TOKEN}
```

### Transactions

When `STASH_GIT_TRACKING=true` and `STASH_READ_ONLY=false`, all writes are gated behind transactions. A batch of related changes is committed to git as a single atomic unit.

Workflow:

1. Call `start_content_transaction` — acquires an exclusive write lock and returns a transaction ID
2. Perform any number of write calls (`create_content`, `overwrite_content`, `edit_content`, `edit_content_batch`, `delete_content`, `move_content`, `move_content_directory`, `move_content_batch`) — all changes are staged
3. Call `commit_content_transaction` with a commit message — commits all staged changes to git and releases the lock
4. If something goes wrong, call `abort_content_transaction` — rolls back all staged changes and releases the lock

**Concurrency.** Only one transaction can be active at a time. A second agent attempting `start_content_transaction` waits up to `STASH_TRANSACTION_LOCK_WAIT` seconds for the lock. If the active transaction is not committed or aborted within `STASH_TRANSACTION_TIMEOUT` seconds, it is automatically aborted.

### Mode matrix

| `STASH_READ_ONLY` | `STASH_GIT_TRACKING` | `STASH_GIT_SYNC_ENABLED` | Behavior |
|---|---|---|---|
| `false` | `false` | — | Default: writes go directly to disk, no git |
| `true`  | `false` | — | Read-only: no write tools registered |
| `false` | `true`  | `false` | Writes committed to local git via transactions |
| `true`  | `true`  | `false` | Read-only + git history/blame tools available |
| `false` | `true`  | `true`  | Writes committed to git + periodic pulls from remote |
| `true`  | `true`  | `true`  | Read-only + git history/blame + auto-sync from remote |

### Docker Compose examples

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

**Auto-syncing from a remote repo (empty content directory — auto-clones on startup):**
```yaml
environment:
  - STASH_READ_ONLY=true
  - STASH_GIT_SYNC_ENABLED=true
  - STASH_GIT_SYNC_URL=https://github.com/org/content-repo.git
  - STASH_GIT_SYNC_BRANCH=main
  - STASH_GIT_SYNC_TOKEN=${GITHUB_TOKEN}
```

**Auto-syncing from a remote repo (content directory already initialised):**
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

### Search configuration

Semantic search is **disabled by default**. To enable:

- `STASH_SEARCH_ENABLED` — Enable semantic search (default: `false`)
- `STASH_SEARCH_INDEX_DIR` — Directory for search index persistence (default: `/data/.stash-index`)
- `STASH_SEARCH_EMBEDDER_MODEL` — Embedder model string (default: `onnx:BAAI/bge-small-en-v1.5`), see below
- `STASH_MODEL_CACHE_DIR` — Where locally downloaded model weights are cached (default: `/data/models`; mount a volume there so the download happens once)
- `STASH_SEARCH_ONNX_THREADS` — onnxruntime thread count for the `onnx:` backend (default: onnxruntime's, one per host core; set e.g. `2` under container CPU limits)
- `STASH_SEARCH_HYBRID_ENABLED` — Fuse BM25 keyword matching with vector search (default: on when `bm25s` is installed — the `search`, `search-contextual` and `search-hybrid` extras include it; the API-provider and torch extras do not)
- `STASH_SEARCH_HEADING_CONTEXT` — Prepend `path > heading > subheading` to each chunk before embedding (default: `true`)
- `STASH_SEARCH_RERANK_ENABLED` — Rescore the top results with a cross-encoder (default: `false`, see [Reranking](#reranking))
- `STASH_CONTEXTUAL_RETRIEVAL` — Enable Claude-powered contextual chunk enrichment (default: `false`)
- `STASH_CONTEXTUAL_MODEL` — Model for contextual retrieval (default: `claude-haiku-4-5-20251001`)
- `ANTHROPIC_API_KEY` — Required when contextual retrieval is enabled

**Embedding backends.** The model string's prefix selects the backend:

| Prefix | Backend | Install extra | Example |
|---|---|---|---|
| `onnx:` | Local, ONNX Runtime via [fastembed](https://github.com/qdrant/fastembed) — no PyTorch, no CUDA libraries (**default**) | `search` | `onnx:BAAI/bge-small-en-v1.5` (384-dim, 512-token window, ~66 MB — the default), `onnx:BAAI/bge-base-en-v1.5` (768-dim, higher quality, ~210 MB), `onnx:sentence-transformers/all-MiniLM-L6-v2` (fp32, 384-dim, 256-token window, ~90 MB). Any model in `fastembed.TextEmbedding.list_supported_models()` works. |
| `openai:` | OpenAI embeddings API via Pydantic AI | `search-openai` | `openai:text-embedding-3-small` |
| `cohere:` | Cohere embeddings API via Pydantic AI | `search-cohere` | `cohere:embed-english-v3.0` |
| `sentence-transformers:` | Local, PyTorch via sentence-transformers (opt-in; ~5 GB of torch + CUDA wheels) | `search-torch` | `sentence-transformers:all-mpnet-base-v2` |

Model files are downloaded from Hugging Face on first use into `STASH_MODEL_CACHE_DIR/fastembed`. Models that need instruction prefixes (`intfloat/*e5*`, `nomic-*`, `snowflake-arctic-*`, `mixedbread-*`, `BAAI/bge-*-en` v1) get them automatically; override with `STASH_SEARCH_QUERY_PREFIX` / `STASH_SEARCH_DOCUMENT_PREFIX`.

> The default model's published MTEB retrieval score (51.7, against ~42 for `all-MiniLM-L6-v2`) is measured on the full-precision weights; fastembed ships a half-precision ONNX export, which reproduced the PyTorch vectors to within 8e-4 cosine in a side-by-side check here.

**How retrieval works.** Chunks are embedded with a `path > heading > subheading` breadcrumb so a sliding-window chunk keeps its section identity, and any chunk that would overflow the model's token window is split rather than silently truncated. Queries run against both the vector index and a BM25 keyword index; the two rankings are fused with Reciprocal Rank Fusion, diversified with MMR, and optionally rescored by a cross-encoder.

#### Reranking

A cross-encoder reads the query and the chunk together instead of comparing two independently-made vectors, which reorders the shortlist much more accurately — for prose. Measured over 24 queries against this repository's own docs and code (MRR, higher is better):

| Configuration | Overall | Prose questions | Literal identifiers | Code questions |
|---|---|---|---|---|
| Default (hybrid, no reranking) | 0.904 | 0.875 | 1.000 | 0.856 |
| `STASH_SEARCH_RERANK_ENABLED=true` | **0.938** | **1.000** | 1.000 | 0.833 |

Reranking costs an extra ~80 MB model download and takes a query from ~3 ms to ~190 ms (CPU, 20 candidates), so it is **off by default**. Turn it on for documentation- and notes-heavy stashes; leave it off if your content is mostly code or if the Web UI's live search needs to stay instant.

- `STASH_SEARCH_RERANK_MODEL` — cross-encoder to use (default: `Xenova/ms-marco-MiniLM-L-6-v2`)
- `STASH_SEARCH_RERANK_CANDIDATES` — how many results to rescore (default: `20`; ~10 ms each)

> With reranking on, the `score` field returned by `/api/search` and `search_content` is the cross-encoder's logit — unbounded, sometimes negative, and only comparable within a single result set — rather than a 0–1 cosine similarity.

When search is enabled, the server exposes:

- An MCP `search_content` tool for agents
- REST endpoints at `/api/search`, `/api/search/status`, and `/api/search/reindex`
- Vector-based search in the Web UI sidebar

The index records a fingerprint of everything that determines its vectors — the embedder model, chunk size and overlap, the heading-breadcrumb setting, contextual retrieval and any document prefix. Change one of those and the stale index is cleared and rebuilt automatically on the next start; retrieval-only settings (MMR, recency, hybrid, reranking) never force a rebuild.

**Upgrading an existing deployment triggers one full re-index**, even if you pin the previous model: this release changes the text that gets embedded (heading breadcrumbs, context-window splitting), and an index written before those existed carries no fingerprint to prove otherwise. The first start after the upgrade also builds the BM25 index for hybrid retrieval. Both happen in the background — the server answers immediately, and `GET /api/search/status` reports progress. To keep the previous model, set `STASH_SEARCH_EMBEDDER_MODEL=onnx:sentence-transformers/all-MiniLM-L6-v2`; for the PyTorch backend, build with `--build-arg SEARCH_EXTRA=search-torch` and use `sentence-transformers:all-MiniLM-L6-v2`.

> **CPU requirement:** numpy ≥ 2.4 wheels (a dependency of every search extra; `uv.lock` pins 2.4.x) are built for the x86-64-v2 baseline (SSE4.2/POPCNT) and fail with `Illegal instruction` on older or generic virtual CPUs. On Proxmox/QEMU VMs with the `kvm64` CPU type, search cannot start regardless of backend — set the VM CPU type to `host` (or `x86-64-v2-AES`) or leave `STASH_SEARCH_ENABLED=false`.

See [USAGE.md](USAGE.md) for detailed search setup instructions.

### Local metrics

Stash-MCP collects **local, opt-out** usage metrics — nothing is sent externally. Metrics are stored in a [TinyFlux](https://github.com/citrusvanilla/tinyflux) time-series CSV file on disk and give operators visibility into tool call rates, response times, error rates, HTTP request patterns, content growth, and search performance.

Metrics are **enabled by default**. To disable:

```yaml
environment:
  - STASH_METRICS_ENABLED=false
```

| Environment Variable | Default | Description |
|---|---|---|
| `STASH_METRICS_ENABLED` | `true` | Set to `false` to disable all metrics collection |
| `STASH_METRICS_PATH` | `{STASH_CONTENT_ROOT}/../metrics.csv` | Path to the TinyFlux CSV database file |
| `STASH_METRICS_RETENTION_DAYS` | `90` | Auto-prune data points older than this many days (`0` = keep forever) |

What is collected:

- **Tool calls** — tool name, duration (ms), success/failure, error type, transport (stdio/http)
- **HTTP requests** — method, endpoint path, status code class (2xx/4xx/5xx), duration (ms)
- **Content events** — create/update/delete/move events with file extension and size
- **Search queries** — provider, hashed query, result count, duration (ms)
- **Server lifecycle** — startup and shutdown events

### Full environment variable reference

| Env Var | Default | Purpose |
|---|---|---|
| `STASH_CONTENT_ROOT` | `/data/content` | Content directory path |
| `STASH_HOST` | `0.0.0.0` | Server host |
| `STASH_PORT` | `8000` | Server port |
| `STASH_LOG_LEVEL` | `info` | Logging level |
| `STASH_READ_ONLY` | `false` | Disable all write tools |
| `STASH_GIT_TRACKING` | `false` | Enable git read tools and blame-enriched search results |
| `STASH_GIT_SYNC_ENABLED` | `false` | Enable periodic pull from remote (requires `STASH_GIT_TRACKING=true`) |
| `STASH_GIT_SYNC_URL` | — | HTTPS URL of the remote repository; when set, auto-clones into an empty content directory and auto-enables `STASH_GIT_TRACKING` |
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
| `STASH_SEARCH_EMBEDDER_MODEL` | `onnx:BAAI/bge-small-en-v1.5` | Embedder model: `onnx:` (local, ONNX Runtime), `openai:`, `cohere:`, or `sentence-transformers:` (local, PyTorch; needs `search-torch`) |
| `STASH_MODEL_CACHE_DIR` | `/data/models` | Cache for locally downloaded model weights (`onnx:` models go in a `fastembed/` subdir) |
| `STASH_SEARCH_ONNX_THREADS` | — | onnxruntime thread count for the `onnx:` backend (default: one per host core; set under container CPU limits) |
| `STASH_SEARCH_QUERY_PREFIX` | *(model default)* | Instruction prepended to queries; `""` disables |
| `STASH_SEARCH_DOCUMENT_PREFIX` | *(model default)* | Instruction prepended to documents; `""` disables |
| `STASH_SEARCH_HEADING_CONTEXT` | `true` | Prepend `path > heading` breadcrumbs to chunks before embedding |
| `STASH_SEARCH_HYBRID_ENABLED` | *(on if `bm25s` installed)* | Fuse BM25 keyword search with vector search |
| `STASH_SEARCH_RERANK_ENABLED` | `false` | Rescore top results with a cross-encoder |
| `STASH_SEARCH_RERANK_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Cross-encoder used for reranking |
| `STASH_SEARCH_RERANK_CANDIDATES` | `20` | How many results to rescore |
| `STASH_CONTEXTUAL_RETRIEVAL` | `false` | Enable Claude-powered contextual chunk enrichment |
| `STASH_CONTEXTUAL_MODEL` | `claude-haiku-4-5-20251001` | Model for contextual retrieval |
| `ANTHROPIC_API_KEY` | — | Required when contextual retrieval is enabled |
| `STASH_METRICS_ENABLED` | `true` | Collect local usage metrics |
| `STASH_METRICS_PATH` | `{content_root}/../metrics.csv` | TinyFlux CSV database file path |
| `STASH_METRICS_RETENTION_DAYS` | `90` | Auto-prune points older than N days (0 = keep forever) |

## License

MIT License — see [LICENSE](LICENSE) for details.
