# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Stash-MCP is a file-backed content server that exposes documents to AI agents via the Model Context Protocol (MCP). It provides CRUD operations, optional semantic search, optional git-based change tracking, and a web UI. Python 3.12+, managed with `uv`.

## Commands

```bash
# Install dependencies
uv sync                              # core only
uv sync --extra dev                  # with test/lint tools
uv sync --extra search               # with sentence-transformers search

# Run servers
uv run -m stash_mcp.main             # HTTP server (FastAPI + MCP StreamableHTTP + web UI)
uv run -m stash_mcp.server           # stdio MCP server (for Claude Desktop)

# Tests
uv run pytest                        # all tests
uv run pytest tests/test_api.py      # single file
uv run pytest -k "test_read"         # by name pattern

# Lint
uv run ruff check .

# Docker
docker-compose up -d
docker-compose logs -f
```

## Architecture

### Dual Transport

Two entry points serve the same MCP tools over different transports:
- `stash_mcp/main.py` — HTTP mode: FastAPI app with REST API (`/api/*`), web UI (`/ui`), and MCP over StreamableHTTP (`/mcp`). This is the primary deployment mode.
- `stash_mcp/server.py` — stdio mode: lightweight MCP server for local subprocess use (Claude Desktop extension).

Both call `create_mcp_server()` from `mcp_server.py` which is the single source of truth for all MCP tool definitions.

### Module Responsibilities

| Module | Role |
|--------|------|
| `mcp_server.py` | All MCP tool/resource definitions. Conditional registration based on config flags. Auto-instruments tools with timing metrics. |
| `filesystem.py` | Path-safe file I/O. All paths validated to stay within `CONTENT_DIR`. |
| `api.py` | FastAPI REST endpoints for CRUD, search, and git operations. |
| `ui.py` | Server-rendered HTML web UI with editor, preview, and file tree. Falls back to legacy HTML when React SPA is unavailable. |
| `frontend.py` | Mounts React SPA at `/ui` from `stash_ui/dist/` if built. |
| `config.py` | All configuration via environment variables (class attributes on `Config`). |
| `search.py` | Optional semantic search: numpy vector store, pluggable embedders (sentence-transformers, OpenAI, Cohere), optional Claude contextual retrieval enrichment. |
| `git_backend.py` | Optional git integration: blame, log, diff via `git` CLI subprocess. Periodic pull sync with credential management. |
| `transactions.py` | Optional write serialization when git tracking is on. Global async lock, session-owned, with timeout auto-abort. |
| `events.py` | Simple pub/sub bus for content change events (`CREATED`, `UPDATED`, `DELETED`, `MOVED`). |
| `metrics.py` | Local opt-out metrics via TinyFlux CSV. Auto-disabled in read-only mode. |

### Optional Features (Off by Default)

Features are enabled via environment variables and conditionally register their MCP tools:
- **Search** (`STASH_SEARCH_ENABLED=true`): Adds `search_content` tool. Requires `search` extra.
- **Git tracking** (`STASH_GIT_TRACKING=true`): Adds `blame_content`, `log_content`, `diff_content` tools. When combined with write mode, adds transaction tools.
- **Read-only mode** (`STASH_READ_ONLY=true`): Suppresses all write and transaction tools.

### Key Patterns

- **SHA-256 conflict detection**: Write operations (`overwrite_content`, `delete_content`) require the caller to pass the SHA-256 hash from the most recent read. This prevents lost updates from concurrent editors.
- **Edit operations use string replacement**: `edit_content` takes `old_string`/`new_string` pairs, not line numbers. Edits are validated in-memory before any writes.
- **Resource registry**: Only `README.md` files are registered as MCP resources. All other files accessed via tools or the `stash://{path}` resource template.
- **Event-driven side effects**: Content mutations emit events that drive metrics recording, search index invalidation, and MCP resource notifications.

### Frontend

The React SPA lives in `stash_ui/` (TypeScript + Vite). It's built during Docker image creation (Node.js stage) and served as static files. The legacy server-rendered UI in `ui.py` is the fallback.

## Testing

Tests use `pytest` + `pytest-asyncio` (auto mode). Test files mirror source modules in `tests/`. Tests create temporary directories for isolation — no external services required. The `test_search.py` and `test_git_backend.py` tests mock subprocess calls and embedding models.

## Environment Variables

All configuration is in `stash_mcp/config.py`. Key variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `STASH_CONTENT_ROOT` | `/data/content` | Content storage directory |
| `STASH_READ_ONLY` | `false` | Disable write tools |
| `STASH_SEARCH_ENABLED` | `false` | Enable semantic search |
| `STASH_GIT_TRACKING` | `false` | Enable git blame/log/diff tools |
| `STASH_GIT_SYNC_ENABLED` | `false` | Enable periodic git pull |
| `STASH_METRICS_ENABLED` | `true` | Local metrics collection |
| `STASH_HOST` / `STASH_PORT` | `0.0.0.0` / `8000` | Server bind address |