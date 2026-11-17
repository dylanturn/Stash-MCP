# Tool Reference

Behavioral guide for every Stash-MCP tool, organized by category. This supplements tool descriptions (which explain *what*) with guidance on *when* and *how*.

## Discovery & Navigation

### list_content(path?, recursive?)

List files and directories in the content store.

- Use `recursive: true` for initial orientation — get the full directory tree in one call
- Use shallow listing (no `recursive`) when exploring a specific subdirectory
- Hidden files (dotfiles) are excluded by default
- Returns directory structure as formatted text, not file contents

### inspect_content_structure(path) / inspect_content_structure_batch(paths[])

Parse markdown heading hierarchy and return a document outline — **without reading file content**.

This is the key efficiency tool. Use it to:

- Understand how a document is organized before deciding whether to read it
- Scan multiple documents' structures in a single batch call (up to 10)
- Decide which section of a long document is relevant before doing a targeted read with `max_lines`

The batch variant is ideal after `list_content` identifies candidate markdown files — inspect them all at once rather than one by one.

### inspect_content_links(path)

List the files that reference a file (`incoming`) and the files it references (`outgoing`) — links, images, and `stash-embed` blocks, each resolved to a content-root path.

- Use it before moving, renaming, or deleting a file to see what depends on it
- Use it instead of `find_content` when the question is "what links here?" — a text search for the file name misses relative links (`../specs/api.json` and `/specs/api.json` are the same file) and matches mentions inside code blocks
- `outgoing` entries carry `exists`; `false` means a broken link in that document
- Works for any file as the target (e.g. which documents embed an image); only markdown and HTML files have outgoing references
- `kind` is `link` or `embed` (images, media, `stash-embed` blocks)
- A path that does not exist returns `exists: false` with any dangling references to it under `incoming`

### search_content(query, max_results?, file_types?)

Semantic similarity search across indexed content. Only available when search is enabled on the server.

- Accepts natural language queries — not keyword search
- `max_results` defaults to 5; increase for broader surveys
- `file_types` is a comma-separated filter (e.g., `.md,.py`) — use it to focus results
- Returns matching chunks with similarity scores and file paths
- See `search-strategy.md` for score interpretation and query techniques

## Reading

### read_content(path, max_lines?) / read_content_batch(paths[], max_lines?)

Read file content and receive the SHA-256 hash required for subsequent writes.

- The SHA is an optimistic concurrency token — store it and pass it to any write operation on this file
- `max_lines` reads only the first N lines — use this for large files to assess relevance before committing to a full read
- Batch reads up to 10 files in a single call — more efficient than sequential reads
- If a file doesn't exist, returns an error (does not create it)

**SHA lifecycle:**
```
read_content(path) → content + sha
  ↓ (time passes, file may change)
edit_content(path, sha, edits) → succeeds if sha matches current file
                                → fails if file changed (re-read needed)
```

## Writing

### create_content(path, content)

Create a new file. **Fails if the file already exists** — this is intentional to prevent accidental overwrites. Use `overwrite_content` or `edit_content` for existing files.

### edit_content(file_path, sha, edits[]) / edit_content_batch(edit_operations[])

Apply targeted string-replacement edits. The preferred tool for modifying existing files.

- Each edit specifies `old_string` and `new_string`
- `old_string` must match exactly one occurrence in the file (unless using `replace_all: true`)
- Edits are applied **sequentially** — later edits see the result of earlier ones in the same call
- Requires the SHA from the most recent read
- Batch variant operates on up to 10 files atomically: all SHAs validated before any writes

**When to use:**
- Updating a section of a document
- Fixing a typo or changing a value
- Any modification where you're changing *part* of a file

### overwrite_content(path, content, sha)

Replace the entire file content. Requires the current SHA.

**When to use:**
- Regenerating a file entirely from a template
- The file content is being completely replaced (not modified)
- You have the complete desired content in working memory

**When NOT to use:**
- When modifying part of a file — use `edit_content` instead
- When you're working from partial context and might drop content you didn't mean to

### delete_content(path, sha)

Delete a file permanently. Requires the current SHA. Irreversible outside of git history (if git tracking is enabled).

If other files still link to or embed the deleted file, the confirmation lists them. Fix or remove those references in the same transaction.

### move_content(source_path, dest_path) / move_content_batch(moves[]) / move_content_directory(source_path, dest_path)

Rename or relocate files and directories.

- `move_content` — single file rename/move
- `move_content_batch` — up to 10 file moves atomically
- `move_content_directory` — move an entire directory subtree; destination must not exist

**Moves do not rewrite links — they report the ones they broke.** `move_content` appends them to its confirmation text; the batch and directory variants return a `broken_links` list of `{file, old_target, new_target}`. For each entry, edit `file` so the link that used to reach `old_target` reaches `new_target`.

- Other files still pointing at the old path are reported with the new location as `new_target`
- Relative links inside a moved file that no longer resolve are reported with `old_target` equal to `new_target` (the target did not move; the linking file did)
- Relative links between files that moved together keep working and are not reported
- The list is capped at 50 entries; `broken_links_total` is set when there are more
- No `broken_links` entries means the move broke nothing — no follow-up scan is needed

## Transactions

When git tracking is enabled and the server is not in read-only mode, **every write tool requires an active transaction owned by the calling session**. The gated set is `create_content`, `overwrite_content`, `edit_content`, `edit_content_batch`, `delete_content`, `move_content`, `move_content_batch`, and `move_content_directory`. This applies equally to single-file edits and multi-file changes — any of these without an active transaction raises:

> `TransactionError: No active transaction. Call start_content_transaction first.`

Transactions provide a global write lock and atomic commit semantics.

When git tracking is **off**, writes go directly to disk and these transaction tools are not registered.

### list_content_transactions()

Check whether a transaction is currently active, which session owns it, and whether this session is the owner. **Always call this before starting a new transaction** to detect orphaned transactions from interrupted sessions.

### start_content_transaction()

Acquire the global write lock. Only one transaction can be active at a time across all sessions. If another transaction is active, this call will wait (up to the configured timeout) or fail.

While a transaction is active:
- Git sync is paused (no remote pulls)
- All write operations are staged but not committed
- Other sessions cannot start transactions

### commit_content_transaction(message, author?)

Commit all staged changes as a single git commit. The `message` should be descriptive of what changed and why. Optional `author` parameter for attribution (format: `"Name <email>"`).

After commit:
- The transaction lock is released
- Git sync resumes (if enabled)
- Changes are pushed to the remote (if git sync is enabled)

### abort_content_transaction()

Discard all uncommitted changes via `git reset --hard HEAD` and release the transaction lock. Use this when:
- Something went wrong mid-transaction
- You discovered the planned changes are no longer needed
- You're cleaning up an orphaned transaction from a previous session

## Git History

Only available when git tracking is enabled. These tools help resolve contradictions, understand change history, and identify current vs. stale content.

### log_content(path, max_count?)

View recent commits that touched a specific file. `max_count` defaults to 20.

Use to answer: "When was this last updated?" and "How frequently does this change?"

### diff_content(path, ref?)

Show what changed in a file since a git reference. Defaults to `HEAD~1` (last commit). Use any valid git ref: `HEAD~5`, a branch name, a commit SHA.

Use to answer: "What changed recently?" and "What did the last update do?"

### blame_content(path, start_line?, end_line?)

Line-level authorship with timestamps. Optional line range for targeted queries.

Use to answer: "Who wrote this section?" and "Is this section from a recent deliberate update or is it stale?"
