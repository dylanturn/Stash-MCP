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
version: 0.1.0
---

# Stash-MCP Usage Guide

Stash-MCP is a file-backed content store accessed through MCP tools. Content lives as files on disk, optionally git-tracked, with semantic search available when enabled. Only README.md files surface as MCP resources — everything else goes through tools.

This skill covers **server-universal** patterns: how to use the tools efficiently regardless of what content is in the store. For deployment-specific conventions (directory layout, templates, naming), read `.stash/SKILL.md` from the content store itself — the SessionStart hook handles this automatically.

## Mental Model

Think of Stash-MCP as a filesystem with guardrails:

- **Files on disk** — markdown, code, any text format
- **SHA-256 concurrency** — every read returns a hash; every write requires it. If the hash doesn't match, someone changed the file since you read it. Re-read, reassess, retry.
- **Transactions** — optional global write lock for atomic multi-file changes. One transaction at a time across all sessions.
- **Semantic search** — natural language queries against embedded content chunks. Not keyword search.

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

### 3. Transactions for Multi-File Changes

Any operation touching more than one file should use a transaction:

```
list_content_transactions()    → check for orphans first
start_content_transaction()    → acquire the global lock
[... create, edit, delete, move operations ...]
commit_content_transaction(message="descriptive commit message")
```

If something goes wrong mid-transaction, call `abort_content_transaction()` to roll back all changes. Without transactions, a failure mid-way leaves the store in an inconsistent state.

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
- **Skipping transactions for multi-file changes** — partial failures corrupt state
- **Ignoring SHA mismatches** — they mean the file changed; re-read before retrying
- **Searching with single keywords** — semantic search needs natural language
- **Assuming tool availability** — check the tool list before planning workflows that depend on git history or search
- **Starting transactions without checking for orphans** — a prior interrupted session may have left one open

## Detailed References

For in-depth coverage beyond this overview:

- **`references/tool-reference.md`** — behavioral guide for every tool, organized by category
- **`references/workflow-patterns.md`** — complete choreography patterns with rationale
- **`references/search-strategy.md`** — embedding model characteristics, score interpretation, query techniques
