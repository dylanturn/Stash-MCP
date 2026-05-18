# 04 — Tool surface

This spec describes how the MCP tools that Stash-MCP exposes to
agents map onto the storage backend. The schema being queried is
in [02-data-model.md](./02-data-model.md); the protocol for
writes is in [03-commit-protocol.md](./03-commit-protocol.md).

Existing MCP tools keep their names and inputs but gain richer
return shapes — the events redesign exposes structure that the
old git-backed implementations couldn't return cheaply. New tools
land alongside the existing ones to expose event-grain queries
directly. All reads resolve against the `main` ref (the only ref
in v1); historical reads use `at_commit` / `at_event`.

## Existing tools

| Tool                       | Implementation                                                                                                                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `read_content`             | `SELECT blob_sha FROM tree_entries WHERE commit_id = refs[main].commit_id AND path = $p`, then `s3.get(blob_key(sha))`. Optional `at_commit` pins to a historical commit; optional `at_event` pins to the state immediately after a given event. |
| `read_content_batch`       | One Postgres query joining `tree_entries` with the paths array; parallel S3 GETs.                                                                                                                                                                |
| `list_content`             | `SELECT path FROM tree_entries WHERE commit_id = refs[main].commit_id AND path LIKE $prefix \|\| '%'`.                                                                                                                                           |
| `log_content`              | `SELECT events.*, commits.author_user_id, commits.message FROM events JOIN commits ON commits.id = events.commit_id WHERE events.path = $p AND commits.store_id = $store ORDER BY events.ts DESC`. Returns per-event rows, grouped by commit.    |
| `blame_content`            | `SELECT * FROM events WHERE store_id = $s AND path = $p ORDER BY ts DESC LIMIT 1`. Returns the last event that touched the file — author, ts, kind, semantic_summary. **File-grain, not line-grain.**                                            |
| `diff_content(p, a, b)`    | Two `tree_entries` lookups → two `s3.get`s → bytes diff (`difflib` / `diff-match-patch`). Additionally returns any `semantic_summary` and `patch_blob_sha` from events between `a` and `b` on path `p`.                                          |
| `inspect_content_structure`| Pure Postgres (paths, sizes from `tree_entries`).                                                                                                                                                                                                |
| `create_content` / `edit_content` | Build `EventDescriptor`s (`kind` inferred from intent: `created` if path absent, `replaced` for whole-file rewrite, `patched` if a structured patch is supplied). Call the commit protocol. Optional params: `semantic_summary`, `patch`. |
| `move_content`             | One `renamed` event. `tree_entries` loses the old path and gains the new; `blob_sha` is unchanged so no S3 traffic.                                                                                                                              |

## New tools, event-grain queries

| Tool                       | Implementation                                                                                                                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `get_change_events`        | `SELECT * FROM events WHERE store_id = $s [AND kind IN (...)] [AND path LIKE ...] [AND ts BETWEEN ...] [AND author = ...] ORDER BY ts DESC`. The filter set is the headline payoff of the events redesign — "show me all renames last week," "show me every `replaced` by agent X," "show me deletions in `docs/` since the release." |
| `get_path_history`         | `SELECT * FROM events WHERE store_id = $s AND path = $p ORDER BY ts DESC`. Returns the per-file event timeline, including the writer's `semantic_summary` per event.                                                                             |
| `get_event`                | Fetch a single event by id, including before/after blobs (on demand) and the structured patch if present.                                                                                                                                        |

## Metadata fields

The metadata fields each tool surfaces (`last_changed_at`,
`changed_by`, `commit_message`, `semantic_summary`) come from
direct columns on `events` and `commits` — strictly faster than
parsing `git blame --porcelain`, and considerably richer. See
[02-data-model.md](./02-data-model.md) for the underlying schema.
