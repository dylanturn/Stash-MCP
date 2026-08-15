# Stash-MCP Usage Guide

This guide covers common usage patterns and workflows for Stash-MCP.

## Installation

### Docker (Recommended)

The easiest way to run Stash-MCP is with Docker:

```bash
# Clone the repository
git clone https://github.com/dylanturn/Stash-MCP.git
cd Stash-MCP

# Start the server
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the server
docker-compose down
```

Your content will be stored in the `./content` directory on your host machine.

### Local Development

For development or if you prefer to run without Docker:

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode
pip install -e ".[dev]"

# Set content directory (optional, defaults to /data/content)
export STASH_CONTENT_DIR=./content

# Run the web server (includes REST API and UI)
python -m stash_mcp.web_server

# Or run the MCP server for stdio transport
python -m stash_mcp.server
```

## Using the Web Interface

Navigate to http://localhost:8000/ui to access the web interface.

The UI allows you to:
- Browse all your content files
- View file contents
- Navigate through directories
- Search content (semantic search when enabled, filename filtering otherwise)

## Using the REST API

The REST API is available at http://localhost:8000

### API Documentation

Interactive API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Common API Operations

**List all content:**
```bash
curl http://localhost:8000/api/content
```

**Read a specific file:**
```bash
curl http://localhost:8000/api/content/docs/welcome.md
```

**Create or update a file:**
```bash
curl -X PUT http://localhost:8000/api/content/notes/my-note.md \
  -H "Content-Type: application/json" \
  -d '{"content": "# My Note\n\nContent here..."}'
```

**Delete a file:**
```bash
curl -X DELETE http://localhost:8000/api/content/old-file.md
```

## Using the MCP Protocol

Connect your MCP client to Stash-MCP to allow AI agents to access and manage content.

### MCP Configuration

Stash-MCP runs as an HTTP server exposing a Streamable HTTP MCP endpoint at `/mcp`. Connect MCP clients using one of the following methods.

**Option 1: Claude Desktop via `mcp-proxy` (Recommended for Desktop)**

`mcp-proxy` bridges Claude Desktop's stdio transport to Stash-MCP's Streamable HTTP endpoint:

```json
{
  "mcpServers": {
    "stash": {
      "command": "uvx",
      "args": [
        "mcp-proxy",
        "--transport",
        "streamablehttp",
        "http://localhost:8000/mcp"
      ]
    }
  }
}
```

> **Note:** `uvx` must be on the PATH that Claude Desktop sees. On macOS, GUI apps may not inherit your shell PATH — use the full path if needed (e.g. `/Users/you/.local/bin/uvx`).

Alternatively, use `npx mcp-remote` if you have Node.js but not uv:

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

**Option 2: Native Streamable HTTP (Claude Code, Cursor, etc.)**

Clients that support Streamable HTTP natively can connect directly:

```json
{
  "mcpServers": {
    "stash": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Claude Code CLI:
```bash
claude mcp add --transport http stash http://localhost:8000/mcp
```

**Option 3: Local stdio (no container)**

Run the server as a stdio subprocess directly from your MCP client config:

```json
{
  "mcpServers": {
    "stash": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Stash-MCP", "-m", "stash_mcp.server"],
      "env": {
        "STASH_CONTENT_ROOT": "/path/to/your/content"
      }
    }
  }
}
```

### Troubleshooting MCP Connections

**"Connection refused" errors**

Ensure the server is running and reachable:
```bash
curl http://localhost:8000/api/health
```
If this fails, check that the Docker container is up (`docker-compose ps`) or the local server process is running.

**`uvx` / `npx` not found**

Claude Desktop may not inherit your shell's PATH. Use the full absolute path to the binary:
- Find it with `which uvx` or `which npx` in your terminal
- On macOS: typically `/Users/you/.local/bin/uvx` or `/usr/local/bin/npx`
- Update your MCP config to use the full path as the `command` value

**Tools not appearing in Claude**

After editing your MCP config, fully restart Claude Desktop (quit and reopen — not just reload). Check the MCP server logs:
- macOS: `~/Library/Logs/Claude/mcp-server-stash.log`
- Windows: `%APPDATA%\Claude\logs\mcp-server-stash.log`

**Timeout on first connection**

The search index build runs in the background at startup and can take a few seconds for large content directories. The MCP endpoint is available immediately, but `search_content` results may be empty until indexing completes. Check indexing status via:
```bash
curl http://localhost:8000/api/search/status
```

### MCP Resources

Resources represent files that can be read by agents:

- **URI format:** `stash://path/to/file.md`
- **List resources:** Use `resources/list` to see all available files
- **Read resource:** Use `resources/read` with a specific URI

### MCP Tools

Tools allow agents to create, edit, overwrite, move, and delete content. Modifications require the file's current SHA-256, returned by `read_content`:

**create_content** - Create a new file (errors if it already exists):
```json
{
  "path": "docs/new-doc.md",
  "content": "# New Document\n\nContent..."
}
```

**read_content** - Read a file and get its `sha` for later modifications:
```json
{
  "path": "docs/existing-doc.md"
}
```

**edit_content** - Apply targeted string-replacement edits to an existing file:
```json
{
  "file_path": "docs/existing-doc.md",
  "sha": "<sha from read_content>",
  "edits": [{"old_string": "old text", "new_string": "new text"}]
}
```

**overwrite_content** - Replace the full content of an existing file:
```json
{
  "path": "docs/existing-doc.md",
  "sha": "<sha from read_content>",
  "content": "# Updated content..."
}
```

**delete_content** - Delete a file:
```json
{
  "path": "docs/old-doc.md",
  "sha": "<sha from read_content>"
}
```

**search_content** *(available when search is enabled)* - Semantic search:
```json
{
  "query": "authentication flow",
  "max_results": 5,
  "file_types": ".md,.py"
}
```

## Semantic Search

Stash-MCP includes an optional semantic search feature that lets agents and users find content by meaning rather than exact keywords. Search is **disabled by default** and must be explicitly enabled.

### Enabling Search

#### With Docker Compose

Add the search environment variable to your `docker-compose.yml`:

```yaml
services:
  stash-mcp:
    build: .
    environment:
      - STASH_SEARCH_ENABLED=true
```

The default Docker image includes the local ONNX Runtime embedding backend ([fastembed](https://github.com/qdrant/fastembed) — no PyTorch or CUDA libraries, so the image stays small). To use a different provider, override the build argument:

```bash
# OpenAI embeddings
docker build --build-arg SEARCH_EXTRA=search-openai -t stash-mcp .

# Cohere embeddings
docker build --build-arg SEARCH_EXTRA=search-cohere -t stash-mcp .

# ONNX Runtime + Anthropic contextual retrieval
docker build --build-arg SEARCH_EXTRA=search-contextual -t stash-mcp .

# ONNX Runtime + BM25 hybrid retrieval
docker build --build-arg SEARCH_EXTRA=search-hybrid -t stash-mcp .

# Local PyTorch / sentence-transformers backend (opt-in; adds ~5 GB of torch + CUDA wheels)
docker build --build-arg SEARCH_EXTRA=search-torch -t stash-mcp .
```

#### Local Development

Install the search dependencies for your preferred embedding provider:

```bash
# Local ONNX Runtime embeddings (default, no API key needed)
pip install -e ".[search]"

# OpenAI embeddings
pip install -e ".[search-openai]"

# Cohere embeddings
pip install -e ".[search-cohere]"

# ONNX Runtime + Anthropic contextual retrieval
pip install -e ".[search-contextual]"

# Local PyTorch / sentence-transformers embeddings (opt-in)
pip install -e ".[search-torch]"
```

Then enable search by setting the environment variable:

```bash
export STASH_SEARCH_ENABLED=true
```

#### Choosing an Embedding Model

`STASH_SEARCH_EMBEDDER_MODEL` selects both the backend (by prefix) and the model:

| Model string | Backend | Notes |
|---|---|---|
| `onnx:BAAI/bge-small-en-v1.5` | ONNX Runtime (default) | 384-dim, 512-token window, ~66 MB. MTEB retrieval 51.7. |
| `onnx:BAAI/bge-base-en-v1.5` | ONNX Runtime | 768-dim, higher quality, ~210 MB (doubles index size) |
| `onnx:sentence-transformers/all-MiniLM-L6-v2` | ONNX Runtime | The pre-0.2 default. fp32, 384-dim, 256-token window, ~90 MB; identical vectors to the PyTorch model (~1e-7). |
| `onnx:<any fastembed model>` | ONNX Runtime | See `python -c "from fastembed import TextEmbedding; print([m['model'] for m in TextEmbedding.list_supported_models()])"` |
| `openai:text-embedding-3-small` | OpenAI API | Requires `OPENAI_API_KEY` and the `search-openai` extra |
| `cohere:embed-english-v3.0` | Cohere API | Requires `CO_API_KEY` and the `search-cohere` extra |
| `sentence-transformers:all-mpnet-base-v2` | PyTorch | Requires the `search-torch` extra |

Models trained with instruction prefixes get them automatically — `query: ` / `passage: ` for the e5 family, `search_query: ` / `search_document: ` for nomic, the "Represent this sentence…" instruction for arctic, mxbai and bge v1. (bge **v1.5** models are used bare, as their model card recommends.) Override with `STASH_SEARCH_QUERY_PREFIX` and `STASH_SEARCH_DOCUMENT_PREFIX`.

Local model files are downloaded on first use into `STASH_MODEL_CACHE_DIR` (default `/data/models`; ONNX models under a `fastembed/` subdirectory). Mount a volume there so the download happens once. With the HTTP server the download happens in the background during the first index build, so the server starts and answers health checks immediately (the stdio server, `stash-mcp-stdio`, builds the index before it starts serving, as before).

Set `STASH_SEARCH_ONNX_THREADS` (e.g. `2`) to cap onnxruntime's thread pool when the container runs under a CPU limit — by default onnxruntime sizes it from the host's core count.

> **CPU requirement:** numpy ≥ 2.4 wheels are built for the x86-64-v2 baseline (SSE4.2/POPCNT). On Proxmox/QEMU VMs using the generic `kvm64` CPU type the process dies with `Illegal instruction` when search is enabled, whichever backend you pick — use CPU type `host` (or `x86-64-v2-AES`) for the VM.

### How Search Works

When search is enabled, the server:

1. **Indexes content at startup** — Files are split into overlapping windows and embedded into vectors. Each chunk also records a `path > heading > subheading` breadcrumb, returned with the result so you can see where a snippet came from (`STASH_SEARCH_HEADING_CONTEXT=true` additionally folds it into the embedded text; measured worse on both corpora tested, so it is off by default)
2. **Never truncates silently** — A window that would overflow the embedding model's token limit is split into evenly-sized pieces first, so no text goes unembedded (`STASH_SEARCH_CHUNK_SIZE` is in characters, models cap tokens)
3. **Keeps the index up-to-date** — File creates, updates, and deletes automatically update the search index
4. **Persists the index to disk** — The vector index and the BM25 index are saved to `STASH_SEARCH_INDEX_DIR` and reloaded on restart
5. **Skips unchanged files** — Incremental indexing only re-embeds files whose content has changed
6. **Auto-reindexes when the index would be stale** — The index records a fingerprint of everything that determines its vectors: the embedder model, chunk size and overlap, the heading-breadcrumb setting and any document prefix. Change any of them and the index is cleared and rebuilt on the next start. Retrieval-only settings (MMR, recency, hybrid, reranking) never force a rebuild

At query time:

1. The query is embedded (with the model's query instruction, if it has one) and matched against the vector index
2. In parallel, BM25 matches the query's literal tokens — env var names, function names, paths — against the same chunks
3. The two rankings are fused with Reciprocal Rank Fusion, then diversified with MMR (and capped per file)
4. If `STASH_SEARCH_RERANK_ENABLED=true`, a cross-encoder rescores the top `STASH_SEARCH_RERANK_CANDIDATES` results
5. Optionally, a git-blame recency boost is blended in (`STASH_SEARCH_RECENCY_WEIGHT`)

### Reranking

Vector search compares a query vector with chunk vectors that were made without ever seeing the query. A cross-encoder reads both together and scores the pair directly. Measured over 42 queries against a 52-document (~305 KB) technical-documentation corpus (MRR):

| Configuration | Overall | Prose questions | Literal identifiers | Concept questions |
|---|---|---|---|---|
| Previous defaults (all-MiniLM-L6-v2, dense) | 0.740 | 0.841 | 0.646 | 0.604 |
| Current defaults | 0.865 | 0.856 | **1.000** | 0.688 |
| `STASH_SEARCH_RERANK_ENABLED=true` | **0.882** | **0.895** | 0.958 | **0.719** |

```bash
export STASH_SEARCH_RERANK_ENABLED=true      # ~120 MB extra download
export STASH_SEARCH_RERANK_CANDIDATES=10     # ~22 ms per candidate, per query
```

Reranking runs only on contested result sets — when the top two retrieval scores are further apart than `STASH_SEARCH_RERANK_MARGIN` (default `0.1`), retrieval already has a clear winner and the cross-encoder is skipped, which on the benchmark skipped 29% of queries and cut mean latency from 218 ms to 160 ms with no quality change. Queries go from ~4 ms to ~160 ms at the default 10 candidates, which is why it is off by default. Rescoring 20 instead doubles the latency for no gain (0.880 vs 0.882), and truncating chunks to save time costs more accuracy than it saves (0.845). Worth it when precision matters more than latency — note it is slightly *negative* on exact-identifier queries, which the lexical index already answers perfectly.

Model choice matters more than model size. On this corpus `Xenova/ms-marco-MiniLM-L-12-v2` (~120 MB, the default) scored 0.880 and `Xenova/ms-marco-MiniLM-L-6-v2` (~80 MB) scored 0.863 — no better than not reranking — while `jinaai/jina-reranker-v1-tiny-en` (0.824) and `jinaai/jina-reranker-v1-turbo-en` (0.816) both scored *worse than no reranking at all* despite being larger. `BAAI/bge-reranker-base` is stronger again but over 1 GB.

> With reranking on, the `score` field in search results is the cross-encoder's logit — unbounded, sometimes negative, comparable only within one result set — instead of a 0–1 cosine similarity.

### Using Search via MCP

When search is enabled, a `search_content` tool is registered in the MCP server:

```python
# Search for content by meaning
result = await client.call_tool("search_content", {
    "query": "authentication flow",
    "max_results": 5,
    "file_types": ".md,.py"  # optional: filter by extension
})
```

### Using Search via REST API

Three search endpoints are available when search is enabled:

```bash
# Semantic search
curl "http://localhost:8000/api/search?q=authentication+flow&max_results=5"

# Check search engine status
curl http://localhost:8000/api/search/status

# Trigger a full reindex
curl -X POST http://localhost:8000/api/search/reindex
```

### Using Search in the Web UI

When search is enabled, the sidebar search box uses vector-based semantic search with debounced queries. Results link directly to the matching files. When search is disabled, the sidebar provides client-side filename filtering instead.

### Contextual Retrieval

For higher quality search results, enable contextual retrieval. This uses Claude to generate a short contextual preamble for each chunk before embedding, improving retrieval accuracy:

```bash
export STASH_SEARCH_ENABLED=true
export STASH_CONTEXTUAL_RETRIEVAL=true
export ANTHROPIC_API_KEY=your-api-key
```

> **Note:** Contextual retrieval requires the `search-contextual` dependency group and an Anthropic API key. It increases indexing time and cost but improves search relevance.

## Content Organization

Organize your content in a way that makes sense for your use case:

```
content/
├── docs/           # Documentation
├── notes/          # Personal notes
├── specs/          # Technical specifications
├── reference/      # Reference materials
└── examples/       # Example content
```

The directory structure maps directly to MCP resource URIs, so:
- `content/docs/api.md` → `stash://docs/api.md`
- `content/notes/2024-01-15.md` → `stash://notes/2024-01-15.md`

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `STASH_CONTENT_DIR` | Path to content directory | `/data/content` |
| `STASH_HOST` | Server host address | `0.0.0.0` |
| `STASH_PORT` | Server port | `8000` |
| `STASH_LOG_LEVEL` | Log level (debug, info, warning, error) | `info` |
| `STASH_SEARCH_ENABLED` | Enable semantic search | `false` |
| `STASH_SEARCH_INDEX_DIR` | Search index directory | `/data/.stash-index` |
| `STASH_SEARCH_EMBEDDER_MODEL` | Embedder model string (`onnx:`, `openai:`, `cohere:`, `sentence-transformers:` prefix selects the backend) | `onnx:BAAI/bge-small-en-v1.5` |
| `STASH_MODEL_CACHE_DIR` | Cache directory for locally downloaded model weights | `/data/models` |
| `STASH_SEARCH_ONNX_THREADS` | onnxruntime thread count for the `onnx:` backend | *(onnxruntime default)* |
| `STASH_SEARCH_QUERY_PREFIX` | Instruction prepended to queries (`""` to disable) | *(model default)* |
| `STASH_SEARCH_DOCUMENT_PREFIX` | Instruction prepended to documents (`""` to disable) | *(model default)* |
| `STASH_SEARCH_HEADING_CONTEXT` | Also embed the `path > heading` breadcrumb (always recorded and returned regardless) | `false` |
| `STASH_SEARCH_HYBRID_ENABLED` | Fuse BM25 keyword search with vector search | *(on if `bm25s` installed)* |
| `STASH_SEARCH_RERANK_ENABLED` | Rescore top results with a cross-encoder | `false` |
| `STASH_SEARCH_RERANK_MODEL` | Cross-encoder used for reranking | `Xenova/ms-marco-MiniLM-L-12-v2` |
| `STASH_SEARCH_RERANK_CANDIDATES` | How many results to rescore | `10` |
| `STASH_SEARCH_RERANK_MARGIN` | Rerank only when the top two scores are this close (`0` = always) | `0.1` |
| `STASH_CONTEXTUAL_RETRIEVAL` | Enable contextual chunk enrichment | `false` |
| `STASH_CONTEXTUAL_MODEL` | Model for contextual retrieval | `claude-haiku-4-5-20251001` |
| `ANTHROPIC_API_KEY` | API key for contextual retrieval | *(none)* |

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=stash_mcp

# Run specific test file
pytest tests/test_filesystem.py -v
```

### Code Quality

```bash
# Run linter
ruff check .

# Auto-fix issues
ruff check --fix .
```

### Building Docker Image

```bash
# Build the image
docker build -t stash-mcp .

# Run the container
docker run -p 8000:8000 -v $(pwd)/content:/data/content stash-mcp
```

## Troubleshooting

### Server won't start

Check that the port isn't already in use:
```bash
lsof -i :8000
```

### Content not showing up

Verify the content directory is correctly mounted/configured:
```bash
echo $STASH_CONTENT_DIR
ls -la $STASH_CONTENT_DIR
```

### Permission errors

Ensure the server has read/write permissions to the content directory:
```bash
chmod -R 755 content/
```

## Best Practices

1. **Version control:** Consider putting your content directory under git version control
2. **Backups:** Regularly backup your content directory
3. **Organization:** Use a consistent directory structure and naming convention
4. **Documentation:** Keep a README in your content directory explaining your organization system
5. **Security:** Run Stash-MCP on localhost or behind authentication if exposing to a network

## Examples

See the `content/` directory for example files that demonstrate:
- Documentation structure
- Agent instruction patterns
- Markdown formatting

## Support

For issues, questions, or contributions:
- GitHub: https://github.com/dylanturn/Stash-MCP
- Issues: https://github.com/dylanturn/Stash-MCP/issues
