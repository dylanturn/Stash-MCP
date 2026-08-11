# Stash — Content Store for AI Agents

Stash is a persistent content store you have access to via MCP. Use it to save, retrieve, organize, and manage documents and notes that persist across conversations. Think of it as your filesystem — a place to stash working documents, reference material, specs, and anything worth keeping.

## How It Works

Paths are POSIX-style and relative to the content root, with no leading slash (e.g. `docs/guide.md`). Writing a file creates missing parent directories automatically — there is no separate mkdir step.

Every modification is guarded by an optimistic-concurrency check: `read_content` returns a `sha` (SHA-256 of the file), and `overwrite_content`, `edit_content`, and `delete_content` require that sha. If the file changed since you read it, the call fails with a SHA mismatch — re-read and retry.

## Core Tools

### Discover

- **`list_content`** — `path` (default root), `recursive` (default false). Non-recursive entries are names prefixed with 📁 (directory) or 📄 (file); recursive listings are full relative paths.
- **`inspect_content_structure`** / **`inspect_content_structure_batch`** — heading outline of a markdown file (title, nested sections with line numbers) without reading the full content.

### Read

- **`read_content`** — `path`, optional `max_lines`. Returns `content`, `sha` (of the full file), `truncated`, and `total_lines`.
- **`read_content_batch`** — up to 10 paths in one call; per-file errors don't fail the batch.
- Files are also exposed as MCP resources under `stash://{path}`.

### Write

- **`create_content`** — `path`, `content`. New files only; errors if the file exists.
- **`edit_content`** — `file_path`, `sha`, `edits` (list of `{old_string, new_string, replace_all}`). Targeted string replacement; preferred for small changes. All edits validate before anything is written.
- **`overwrite_content`** — `path`, `content`, `sha`. Replaces the entire file.
- **`edit_content_batch`** — atomic edits across up to 10 files; if any file fails validation, nothing is written.

### Organize

- **`move_content`** — `source_path`, `dest_path`. The destination must not already exist; parent directories are created automatically.
- **`move_content_directory`** — moves a whole directory tree.
- **`move_content_batch`** — up to 10 moves, validated all-or-nothing.
- **`delete_content`** — `path`, `sha`. Deletes are permanent.

### Configuration-Dependent Tools

Depending on how this server is configured, you may also have:

- **`search_content`** — semantic search returning ranked snippets; follow up with `read_content` for full files.
- **`log_content`**, **`diff_content`**, **`blame_content`** — git history, diffs, and line-level authorship for any file.
- **Transaction tools** — when writes are git-tracked, every write requires an active transaction: call `start_content_transaction`, make your changes, then `commit_content_transaction` with a commit message (or `abort_content_transaction` to discard). Write tools will say so in their descriptions if this applies.

If a tool isn't listed in your session, that feature is disabled — and in read-only deployments no write tools are registered at all.

## Typical Workflows

Save something new:

```
create_content(path="notes/project-ideas.md", content="# Project Ideas\n\n- CLI dashboard")
```

Modify an existing file:

```
read_content(path="notes/project-ideas.md")            → returns sha
edit_content(
  file_path="notes/project-ideas.md",
  sha="<sha from read>",
  edits=[{"old_string": "- CLI dashboard", "new_string": "- CLI dashboard\n- Monitoring alerts"}],
)
```

Reorganize:

```
move_content(source_path="notes/project-ideas.md", dest_path="projects/ideas.md")
```

## Suggested Structure

```
docs/           — Long-lived documentation and reference material
notes/          — Working notes, meeting notes, scratchpad
specs/          — Technical specifications and designs
projects/       — Per-project working directories
templates/      — Reusable templates and boilerplate
```

You're not locked into this — organize however makes sense for the user's needs.

## Important Behaviors

- **`create_content` fails if the file exists.** Use `overwrite_content` or `edit_content` for existing files.
- **Writes require the current sha.** Always `read_content` first; a SHA mismatch means the file changed under you.
- **Paths are sandboxed.** You cannot traverse outside the content root; `..` escapes are rejected.
- **Hidden files (dotfiles) are excluded** from listings.
- **Content is UTF-8 text.** Binary files are not supported.
- **Deletes are permanent** — there is no trash. On git-tracked servers, uncommitted transaction changes can be discarded with `abort_content_transaction`, but a committed delete only survives in git history.

## When to Use Stash

Use Stash when the user asks you to save, remember, or persist something beyond the current conversation: reference documentation, working notes or drafts that evolve over sessions, technical specs, templates, research digests, or anything the user explicitly asks you to "stash" or "save."

Don't use Stash for ephemeral responses or one-off answers — just respond normally in conversation for those.
