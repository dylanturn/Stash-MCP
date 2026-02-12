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

For clients that use stdio transport, configure your MCP client with:

```json
{
  "mcpServers": {
    "stash": {
      "command": "python",
      "args": ["-m", "stash_mcp.server"],
      "env": {
        "STASH_CONTENT_DIR": "/path/to/your/content"
      }
    }
  }
}
```

### MCP Resources

Resources represent files that can be read by agents:

- **URI format:** `stash://path/to/file.md`
- **List resources:** Use `resources/list` to see all available files
- **Read resource:** Use `resources/read` with a specific URI

### MCP Tools

Tools allow agents to create, update, and delete content:

**create_content** - Create a new file:
```json
{
  "path": "docs/new-doc.md",
  "content": "# New Document\n\nContent..."
}
```

**update_content** - Update an existing file (or create if it doesn't exist):
```json
{
  "path": "docs/existing-doc.md",
  "content": "# Updated content..."
}
```

**delete_content** - Delete a file:
```json
{
  "path": "docs/old-doc.md"
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

The default Docker image includes the `sentence-transformers` embedding provider. To use a different provider, override the build argument:

```bash
# OpenAI embeddings
docker build --build-arg SEARCH_EXTRA=search-openai -t stash-mcp .

# Cohere embeddings
docker build --build-arg SEARCH_EXTRA=search-cohere -t stash-mcp .

# Sentence-transformers + Anthropic contextual retrieval
docker build --build-arg SEARCH_EXTRA=search-contextual -t stash-mcp .
```

#### Local Development

Install the search dependencies for your preferred embedding provider:

```bash
# Sentence-transformers (local, no API key needed)
pip install -e ".[search]"

# OpenAI embeddings
pip install -e ".[search-openai]"

# Cohere embeddings
pip install -e ".[search-cohere]"

# Sentence-transformers + Anthropic contextual retrieval
pip install -e ".[search-contextual]"
```

Then enable search by setting the environment variable:

```bash
export STASH_SEARCH_ENABLED=true
```

### How Search Works

When search is enabled, the server:

1. **Indexes content at startup** — All files are chunked (using markdown-aware splitting) and embedded into vectors
2. **Keeps the index up-to-date** — File creates, updates, and deletes automatically update the search index
3. **Persists the index to disk** — The vector index is saved to `STASH_SEARCH_INDEX_DIR` and reloaded on restart
4. **Skips unchanged files** — Incremental indexing only re-embeds files whose content has changed
5. **Auto-reindexes on model change** — If `STASH_SEARCH_EMBEDDER_MODEL` changes between restarts, the stale index is automatically cleared and rebuilt with the new model

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
| `STASH_SEARCH_EMBEDDER_MODEL` | Embedder model string | `sentence-transformers:all-MiniLM-L6-v2` |
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
