# Stash — Content Store for AI Agents

Stash is a persistent content store you have access to via MCP. Use it to save, retrieve, organize, and manage documents and notes that persist across conversations. Think of it as your filesystem — a place to stash working documents, reference material, specs, and anything worth keeping.

## What You Have

### Resources (Read Path)

Every file in the store is exposed as an MCP resource with a `stash://` URI. Use `resources/list` to discover what's available, and `resources/read` to fetch content.

URI pattern: `stash://{path}` where path is relative to the content root.

Examples:
- `stash://docs/welcome.md`
- `stash://notes/meeting-2025-01-15.md`
- `stash://specs/api-design.yaml`

### Tools (Write Path)

You have 5 tools for managing content:

**`create_content`** — Create a new file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | File path relative to content root |
| `content` | string | yes | File content |

Creates parent directories automatically. Errors if the file already exists — use `update_content` to modify existing files.

**`update_content`** — Update an existing file (or create one).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | File path relative to content root |
| `content` | string | yes | New file content (replaces entire file) |

This is a full replacement, not a patch. Always write the complete file content.

**`delete_content`** — Delete a file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | File path to delete |

Errors if the file doesn't exist.

**`move_content`** — Move or rename a file.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_path` | string | yes | Current file path |
| `dest_path` | string | yes | New file path |

Creates parent directories at the destination automatically. Errors if the destination already exists.

**`list_content`** — List files and directories.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | no | `""` (root) | Directory to list |
| `recursive` | boolean | no | `false` | List all files recursively |

Returns directory contents with 📁 and 📄 prefixes for directories and files. With `recursive: true`, returns a flat list of all file paths.

## How to Use It

### Discover what's available

Before reading or writing, check what exists:

```
list_content(path="", recursive=true)
```

This gives you the full directory tree. Use non-recursive listing to explore one level at a time if the tree is large.

### Read a file

Use the resource URI directly:

```
resources/read → stash://docs/welcome.md
```

Or for dynamic access, the resource template `stash://{path}` resolves any path.

### Save something new

```
create_content(
  path="notes/project-ideas.md",
  content="# Project Ideas\n\n- Build a CLI dashboard\n- Automate weekly reports"
)
```

### Update an existing file

```
update_content(
  path="notes/project-ideas.md",
  content="# Project Ideas\n\n- Build a CLI dashboard\n- Automate weekly reports\n- Set up monitoring alerts"
)
```

### Organize content

```
move_content(
  source_path="notes/project-ideas.md",
  dest_path="projects/ideas.md"
)
```

### Clean up

```
delete_content(path="scratch/temp-notes.md")
```

## File Organization

Paths use forward slashes and are relative to the content root. There's no leading slash. Directories are created automatically when you write a file — you don't need to create them explicitly.

Supported file types include `.md`, `.txt`, `.json`, `.yaml`, `.yml`, `.xml`, `.html`, `.css`, `.js`, `.ts`, `.py`, `.csv`, `.toml`, `.ini`, `.rst`, `.log`, and more. Any text file works. Markdown is the most common format.

### Suggested Structure

```
docs/           — Long-lived documentation and reference material
notes/          — Working notes, meeting notes, scratchpad
specs/          — Technical specifications and designs
projects/       — Per-project working directories
templates/      — Reusable templates and boilerplate
```

You're not locked into this — organize however makes sense for the user's needs.

## Important Behaviors

- **`create_content` will fail if the file exists.** Use `update_content` instead, or check with `list_content` first.
- **`update_content` replaces the entire file.** Read the file first if you need to make a partial edit, then write back the full content with your changes.
- **Paths are sandboxed.** You cannot traverse outside the content root. Attempts to use `..` or absolute paths will be rejected.
- **Hidden files (dotfiles) are excluded** from listings but the filesystem layer skips them automatically.
- **Content is plain text.** Binary files are not supported. Everything is read and written as UTF-8 strings.
- **Changes persist immediately.** Files are written directly to disk. There's no staging, commits, or undo — be deliberate with deletions.

## When to Use Stash

Use Stash when the user asks you to save, remember, or persist something beyond the current conversation. Good candidates include:

- Reference documentation the user wants to maintain
- Working notes or drafts that evolve over multiple sessions
- Technical specs, architecture decisions, or design docs
- Templates, snippets, or reusable content
- Summaries or digests of research
- Any content the user explicitly asks you to "stash" or "save"

Don't use Stash for ephemeral responses or one-off answers — just respond normally in conversation for those.