---
name: stash-mcp-usage
description: >
  Behavioral guide for working with a Stash-MCP content store. Use when
  the user asks to "read from stash", "update docs in the content store",
  "search the knowledge base", "create a document", "find documentation",
  or any task involving Stash-MCP tools (create_content, read_content,
  edit_content, search_content, list_content, move_content, etc.).
  Teaches efficient navigation, surgical editing, transaction safety,
  and semantic search strategy.
version: 0.1.7
---

# Stash-MCP Usage Guide

Stash-MCP is a file-backed content store accessed through MCP tools. Content lives as files on disk, optionally git-tracked, with semantic search available when enabled. Only README.md files surface as MCP resources — everything else goes through tools.

This skill covers **server-universal** patterns: how to use the tools efficiently regardless of what content is in the store. For deployment-specific conventions (directory layout, templates, naming), read `.stash/SKILL.md` from the content store itself — the SessionStart hook handles this automatically.

## Mental Model

Think of Stash-MCP as a filesystem with guardrails:

- **Files on disk** — markdown, code, any text format
- **SHA-256 concurrency** — every read returns a hash; every write requires it. If the hash doesn't match, someone changed the file since you read it. Re-read, reassess, retry.
- **Transactions** — when git tracking is enabled, *every* write requires an active transaction. The lock is global; one transaction at a time across all sessions.
- **Semantic search** — natural language queries against embedded content chunks. Not keyword search.

## Content Types

Stash stores files as-is on disk. Anything text-based round-trips losslessly through the tools; binary types (images, etc.) are stored and served as assets but should not be opened with `read_content` — you'll get raw bytes.

### Document types

| Class | Extensions | Notes |
|-------|------------|-------|
| **Markdown** (primary) | `.md`, `.markdown` | First-class. Heading hierarchy parsed by `inspect_content_structure`. Only `README.md` surfaces as an MCP resource — everything else is tool-only. |
| **Diagrams** | `.mmd`, `.mermaid`, `.gantt` | Rendered as diagrams in the UI viewer. Plain text under the hood — edit like any text file. `.gantt` is YAML-based. |
| **API specs** | `.json` with an `openapi` root key | Rendered as an OpenAPI viewer in the UI. Stored as plain JSON. Slices can be embedded into markdown via ` ```stash-embed ` — see below. |
| **Tabular** | `.csv`, `.tsv` | Rendered as HTML tables in the UI. |
| **Web** | `.html`, `.htm` | Rendered in a sandboxed iframe. Fragments can also be embedded into markdown via ` ```stash-embed ` (CSS selector). |
| **Structured text** | `.json`, `.yaml`, `.yml`, `.toml`, `.xml`, `.ini`, `.cfg` | Stored as text, no special rendering. |
| **Code** | `.py`, `.js`, `.ts`, `.css`, `.rst`, `.txt`, `.log`, plus any other text extension | Stored as text. Searchable. |
| **Image assets** | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.svg`, `.ico`, `.bmp` | Served via `/ui/raw/<path>` for embedding. Do **not** `read_content` these — store and link instead. |

There is no extension allowlist for storage. Files with unknown extensions are accepted and served as `text/plain`.

### Embedding in markdown

Markdown is the host format — several other types can be embedded inline so a single document renders as a richer view:

- **Images** — standard markdown syntax: `![alt text](relative/path.png)`. Relative paths are rewritten to `/ui/raw/` URLs at render time, so the image just needs to live in the content store. Absolute URLs and `data:` URIs also pass through.
- **Mermaid diagrams** — fenced code block tagged ` ```mermaid ` renders inline. Use this for one-off diagrams; reserve standalone `.mmd` files for diagrams you want to reuse or link to.
- **Gantt charts** — fenced code block tagged ` ```gantt ` (YAML body) renders inline. Standalone `.gantt` files work the same way. **The YAML schema is Stash-specific** (not Mermaid gantt syntax) — see `references/gantt-format.md` before authoring.
- **CSV / TSV tables** — fenced code block tagged ` ```csv ` or ` ```tsv ` renders as an HTML table inline. Good for small, document-scoped tables; use standalone `.csv` files when the data is the artifact.
- **Embed-by-reference** — fenced code block tagged ` ```stash-embed ` (YAML body) renders a slice of another document inline. The source stays the single source of truth; edits there propagate to every embed.

  **Shared fields:**
  - `src:` (required) — path to the source file. Absolute paths (`/specs/orders.json`) are rooted at the content store; relative paths resolve against the embedding document's directory.
  - `type:` (optional) — override auto-detection. Supported values: `openapi`, `html`. Auto-detection uses the `src` extension plus content sniffing; set `type:` explicitly when the extension is ambiguous (e.g. an HTML snippet stored as `.txt`).

  **OpenAPI sources** (`.json` / `.yaml` / `.yml` with a top-level `openapi` key):
  - `tag:` — keep only operations tagged with this value.
  - `path:` — keep only this exact path (e.g. `/orders/{order_id}`).
  - `operationId:` — keep only this single operation.

  Filters combine with AND. With no filters, the full spec renders. Filtered embeds drop the `components.schemas` block since the point is a focused slice.

  **HTML sources** (`.html` / `.htm`):
  - `selector:` — any CSS selector (id, class, tag, attribute, combinators all work). Returns the matched subtree(s). With no selector, returns the document `<body>` contents.

  `<style>` blocks from the source are preserved and re-emitted wrapped in a CSS `@scope` rule keyed to a per-embed class, so the source's styling applies only to its own fragment and doesn't leak into the host doc. Multiple embeds from different sources can use the same generic selectors (e.g. `section { ... }`) without colliding. Requires a browser with `@scope` support (Chrome/Edge 118+, Safari 17.4+, Firefox 128+).

  **Examples:**
  ````markdown
  ```stash-embed
  src: /specs/orders.json
  tag: orders
  ```

  ```stash-embed
  src: /reports/q2.html
  selector: "#risks"
  ```
  ````

  **Errors** render inline (missing `src`, source not found, no selector match, ambiguous type, etc.) — they never silently drop content. If you see a red error box in a rendered doc, fix the embed reference.
- **Raw HTML** — passes through the markdown renderer by design. `<details>`, `<img>`, `<video>`, `<iframe>`, `<div>` all work. Use sparingly; markdown syntax is preferable when it covers the case.

**Cannot be embedded inline:** PDFs, Office documents (`.docx`, `.xlsx`, `.pptx`), Jupyter notebooks (`.ipynb`), and other binary formats. Link to them as assets if needed, but Stash has no native renderer for these — `read_content` will return unreadable bytes.

**Rule of thumb:** if the asset is referenced from one document, embed it as a fenced block. If multiple documents reference it, store it as a standalone file and link.

## Tool Categories at a Glance

Stash exposes 21+ tools across five categories. Not all are always available — availability depends on server configuration. Only use tools that appear in the tool list.

| Category | Tools | Always Available |
|----------|-------|-----------------|
| Discovery | `list_content`, `inspect_content_structure(_batch)`, `search_content` | list/inspect yes, search conditional |
| Reading | `read_content(_batch)` | Yes |
| Writing | `create_content`, `edit_content(_batch)`, `overwrite_content`, `delete_content`, `move_content(_batch/_directory)` | Only when not read-only |
| Transactions | `start_content_transaction`, `commit_content_transaction`, `abort_content_transaction`, `list_content_transactions` | Only with git tracking enabled |
| Git History | `log_content`, `diff_content`, `blame_content` | Only with git tracking enabled |

## Core Principles

### 1. Progressive Narrowing (Don't Read Everything)

Each discovery step narrows scope before the next. Never skip straight to reading full files.

```
list_content(recursive=true)        → map the territory
inspect_content_structure(path)     → understand doc shape without reading content
search_content(query)               → find specific content by meaning
read_content(path, max_lines=50)    → sample before committing to full read
read_content(path)                  → read only what you actually need
```

`inspect_content_structure` is the most underused tool. It returns heading outlines without reading file content — use it to understand document organization before deciding what to read.

### 2. Edit, Don't Overwrite

`edit_content` applies targeted string replacements. `overwrite_content` replaces the entire file. Prefer edit because:

- It preserves content you didn't intend to change
- It's safer when working from partial context (you may not have the full file in memory)
- It documents *what changed* rather than *what the file looks like now*

Use `overwrite_content` only when regenerating an entire file from scratch.

### 3. Transactions Wrap Every Write (when git tracking is on)

When the server has git tracking enabled, every write tool requires an active transaction owned by your session — `create_content`, `overwrite_content`, `edit_content`, `edit_content_batch`, `delete_content`, `move_content`, `move_content_batch`, and `move_content_directory` are all gated. Calling any of them without an active transaction raises:

> `TransactionError: No active transaction. Call start_content_transaction first.`

The choreography is the same whether you're touching one file or twenty:

```
list_content_transactions()    → check for orphans first
start_content_transaction()    → acquire the global lock
[... one or more write operations (create/overwrite/edit/delete/move, including batch variants) ...]
commit_content_transaction(message="descriptive commit message")
```

Multi-file changes are simply the case where the transaction spans more than one operation — same mechanism, same atomicity guarantee. If something goes wrong mid-transaction, call `abort_content_transaction()` to roll back all staged changes.

When git tracking is **off**, writes go straight to disk and the transaction tools aren't registered. Check the tool list to know which mode you're in.

### 4. SHA Means "I've Seen This Version"

Every `read_content` call returns a SHA-256 hash. Pass this hash to write operations. If the file changed between your read and your write, the operation fails — this is intentional. Re-read the file, check what changed, then retry with the new SHA.

Batch operations (`edit_content_batch`) validate all SHAs before writing anything. One stale SHA aborts the entire batch.

### 5. Search With Natural Language

Semantic search works on meaning, not keywords. Write queries as natural language questions or phrases:

- Good: "how does the trigger system handle webhook events"
- Bad: "trigger webhook"

Scores: 0.65+ is a strong match, 0.50–0.65 is worth reading to verify, below 0.50 is likely noise. Use `file_types` to filter (e.g., `.md` for docs only). Multiple short queries often beat one complex query.

See `references/search-strategy.md` for detailed guidance.

## Anti-Patterns

- **Reading entire files when you only need structure** — use `inspect_content_structure`
- **Overwriting when you can edit** — `edit_content` is almost always safer
- **Calling write tools without an active transaction** (when git tracking is on) — every write requires one, even single-file edits; you'll get `TransactionError: No active transaction. Call start_content_transaction first.`
- **Ignoring SHA mismatches** — they mean the file changed; re-read before retrying
- **Searching with single keywords** — semantic search needs natural language
- **Assuming tool availability** — check the tool list before planning workflows that depend on git history or search
- **Starting transactions without checking for orphans** — a prior interrupted session may have left one open

## Detailed References

For in-depth coverage beyond this overview:

- **`references/tool-reference.md`** — behavioral guide for every tool, organized by category
- **`references/workflow-patterns.md`** — complete choreography patterns with rationale
- **`references/search-strategy.md`** — embedding model characteristics, score interpretation, query techniques
- **`references/gantt-format.md`** — schema and examples for `.gantt` files and ` ```gantt ` blocks (Stash-specific, not Mermaid)
