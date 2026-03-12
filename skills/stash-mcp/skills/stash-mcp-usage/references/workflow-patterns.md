# Workflow Patterns

Complete choreography patterns for common Stash-MCP operations. Each pattern explains the sequence, the rationale, and what to watch for.

## Pattern: Content Discovery (Progressive Narrowing)

**When:** Starting work, exploring unfamiliar content, answering "what's in here?"

```
list_content(recursive=true)
  → map the full directory tree
  → identify candidate files by path and name

inspect_content_structure_batch([candidate .md files])
  → understand document organization without reading content
  → decide which documents and sections are relevant

search_content("natural language query about what you need")
  → find specific content by meaning
  → use scores to prioritize: 0.65+ read first, 0.50-0.65 maybe, <0.50 skip

read_content(path, max_lines=50)
  → sample the most promising files before full reads

read_content(path)
  → read only what you actually need
```

**Why this order:** Each step narrows scope before the next. An agent that skips to `read_content` on multiple files burns through context budget reading content that may be irrelevant. Progressive narrowing keeps context lean.

**Watch for:** Large stores with hundreds of files — use `search_content` early to cut through the noise rather than inspecting every file's structure.

## Pattern: Surgical Edit

**When:** Modifying part of an existing document.

```
read_content(path)
  → get current content + SHA

edit_content(path, sha, edits=[
  {"old_string": "exact text to find", "new_string": "replacement text"},
  {"old_string": "another section", "new_string": "updated section"}
])
  → apply targeted replacements
```

**Why:** `edit_content` only changes what you specify. Everything else in the file stays untouched. This is critical when working from partial context — you may not have the entire file in your working memory, and `overwrite_content` would silently drop anything you forgot.

**Watch for:**
- `old_string` must match exactly one occurrence (unless `replace_all: true`). If the string appears multiple times, provide more surrounding context to make it unique.
- Edits are sequential — edit #2 sees the result of edit #1. Plan accordingly.
- SHA mismatch means the file changed. Re-read, check the diff, then retry.

## Pattern: Transactional Multi-File Change

**When:** Any operation touching more than one file. Reorganizations, template-based creation, coordinated updates.

```
list_content_transactions()
  → check for orphaned transactions
  → if one exists and this session owns it: decide to commit or abort
  → if one exists and another session owns it: wait or inform the user

start_content_transaction()
  → acquire the global write lock

[... multiple create/edit/delete/move operations ...]

commit_content_transaction(message="descriptive message about what changed and why")
  → atomic commit of all changes
```

**Why:** Without transactions, a failure after modifying 3 of 5 files leaves the store inconsistent. Transactions ensure all-or-nothing. They also batch all changes into a single git commit, keeping history clean.

**Watch for:**
- Always check for orphans first. A crashed session may have left a lock open.
- Keep transactions short — they hold a global lock that blocks other writers.
- If something goes wrong mid-transaction, call `abort_content_transaction()` to roll back cleanly.
- The commit message should explain *why* the changes were made, not just *what* changed.

## Pattern: Conflict Resolution via History

**When:** Documents contradict each other. Content seems stale. Need to understand the evolution of a decision.

```
log_content(path)
  → when was this last changed? by whom?
  → compare modification dates between contradicting documents

diff_content(path, ref="HEAD~3")
  → what changed in recent commits?
  → was there a deliberate update or just formatting?

blame_content(path, start_line=X, end_line=Y)
  → who wrote this specific section and when?
  → is it from the same era as the rest of the document?
```

**Why:** The most recently modified document typically reflects current thinking. Blame helps distinguish between a section that was deliberately updated as part of a decision and one that's been untouched since the initial draft.

**Watch for:** Git history tools are only available when git tracking is enabled. Check the tool list before planning a workflow that depends on them.

## Pattern: Safe First Interaction

**When:** First time working with a Stash-MCP content store in a session.

```
read_content(".stash/SKILL.md")
  → load deployment-specific conventions
  → (the SessionStart hook handles this automatically)

list_content(recursive=true)
  → orient to the content store layout

inspect_content_structure_batch([top-level .md files])
  → understand document organization at a glance
```

**Why:** Establishes situational awareness before doing any work. The deployment-specific skill tells you about directory conventions, templates, and naming patterns that are unique to this content store.

## Pattern: Template-Based Creation

**When:** Creating a new document that should follow an established format.

```
list_content("_templates")
  → find available templates (if the store uses a templates directory)

read_content("_templates/appropriate-template.md")
  → get the template content + understand required sections

start_content_transaction()
create_content("target/path/new-document.md", filled_template_content)
commit_content_transaction(message="Create new document from template")
```

**Why:** Templates enforce consistency across documents. Using the store's own templates (rather than inventing a format) means the new document fits with existing conventions.

**Watch for:** Not all stores use templates. Check `list_content` first. If no `_templates` directory exists, inspect similar existing documents to infer the expected format.

## Pattern: Large-Scale Reorganization

**When:** Moving many files, restructuring directories, renaming conventions.

```
list_content(recursive=true)
  → understand current structure

list_content_transactions()
  → ensure no active transaction

start_content_transaction()

move_content_directory("old/path", "new/path")
  → move entire subtrees

move_content_batch([
  {"source_path": "file1.md", "dest_path": "new-location/file1.md"},
  {"source_path": "file2.md", "dest_path": "new-location/file2.md"}
])
  → move individual files that don't fit the directory move

edit_content_batch([... update internal cross-references ...])
  → fix any links or references that point to old paths

commit_content_transaction(message="Reorganize: describe the new structure and why")
```

**Why:** Reorganizations touch many files and are easy to get wrong. The transaction ensures either the entire reorganization succeeds or nothing changes. Updating cross-references in the same transaction keeps everything consistent.

**Watch for:**
- `move_content_directory` requires the destination not to exist
- After moves, internal links and references may break — scan for and fix these
- Large reorganizations deserve a descriptive commit message explaining the rationale
