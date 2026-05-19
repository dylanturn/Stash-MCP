# Stash-MCP Plugin

Connect Claude to a [Stash-MCP](https://github.com/dylanturn/Stash-MCP) content store with smart workflows, transaction safety, and auto-bootstrapped usage patterns.

## What This Plugin Does

Stash-MCP is a file-backed documentation server that exposes content through MCP tools — 21+ tools for reading, writing, searching, and versioning files on disk. This plugin bundles three things:

1. **MCP server connection** — pre-configured HTTP transport to a running Stash-MCP instance
2. **Usage skill** — teaches Claude efficient navigation patterns, surgical editing, transaction safety, and semantic search strategy
3. **Behavioral hooks** — enforce best practices automatically:
   - **Auto-bootstrap** — reads deployment-specific conventions from `.stash/SKILL.md` on session start
   - **Transaction orphan check** — verifies no stale transactions exist before starting new ones
   - **Edit-over-overwrite guard** — prompts Claude to prefer targeted edits over full file replacement

## Setup

### 1. Run a Stash-MCP Server

The plugin connects to a running Stash-MCP instance over HTTP. Start one with Docker:

```bash
docker run -d \
  -p 8000:8000 \
  -v /path/to/your/content:/data/content \
  -e STASH_SEARCH_ENABLED=true \
  -e STASH_GIT_TRACKING=true \
  ghcr.io/dylanturn/stash-mcp:latest
```

Or with Docker Compose — see the [Stash-MCP README](https://github.com/dylanturn/Stash-MCP) for full configuration options.

### 2. Set the Environment Variable

The plugin needs to know where your Stash-MCP instance is running:

```
STASH_MCP_URL=http://localhost:8000
```

Set this in your environment or in your Claude configuration. The plugin appends `/mcp` to this URL for the MCP transport endpoint.

### 3. (Optional) Create a Deployment-Specific Skill

The plugin includes a server-universal skill that covers tool patterns and workflows. For deployment-specific conventions (your directory layout, templates, naming patterns), create a `.stash/SKILL.md` file inside your content store:

```bash
mkdir -p /path/to/your/content/.stash
```

Then create `.stash/SKILL.md` with your conventions. The SessionStart hook automatically reads this file at the beginning of each session. See the [Stash-MCP documentation](https://github.com/dylanturn/Stash-MCP) for a template.

## Components

| Component | Description |
|-----------|-------------|
| **MCP Server** (`stash`) | HTTP connection to Stash-MCP at `$STASH_MCP_URL/mcp` |
| **Skill** (`stash-mcp-usage`) | Server-universal guide: tool workflows, SHA concurrency, search strategy, anti-patterns |
| **Hook** (SessionStart) | Auto-reads `.stash/SKILL.md` from the content store on session start |
| **Hook** (PreToolUse: transaction) | Checks for orphaned transactions before `start_content_transaction` |
| **Hook** (PreToolUse: overwrite) | Prompts Claude to prefer `edit_content` over `overwrite_content` |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `STASH_MCP_URL` | Yes | Base URL of your Stash-MCP instance (e.g., `http://localhost:8000`) |

## Architecture

This plugin provides the **connection and behavioral layer**. The content-specific layer lives inside the content store itself:

```
Plugin (installed in Claude)          Content Store (on disk)
├── .mcp.json (connection)            ├── .stash/
├── skills/ (universal patterns)      │   └── SKILL.md (deployment conventions)
└── hooks/ (behavioral guardrails)    ├── your-docs/
                                      └── ...
```

The plugin teaches Claude *how* to use Stash-MCP efficiently. The `.stash/SKILL.md` in the content store teaches Claude *your specific* conventions for that store. The SessionStart hook bridges the two by auto-loading the deployment-specific skill.

## License

MIT
