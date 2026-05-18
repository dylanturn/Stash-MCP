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

## Lease tools

Agents that don't want to risk wasting reasoning tokens on a
write that loses a race acquire a **path lease** before reading.
While the lease is held, other agents trying to commit to that
path get back `PathLeased` and back off. The full mechanism is
specified in
[03-commit-protocol.md § Path leases](./03-commit-protocol.md#path-leases);
the tools that drive it:

| Tool                       | Implementation                                                                                                                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `lease_path(path, ttl_seconds)` | Acquire or extend a lease. Returns `LeaseInfo { path, holder, acquired_at, expires_at, ttl_seconds }` on success. Returns `Locked { held_by, expires_at }` if a different principal already holds an active lease on this path. Idempotent — calling against your own lease serves as an explicit extension. |
| `release_path_lease(path)`      | Release a lease held by the caller. Idempotent: releasing a lease you don't hold (because it never existed, expired, or belongs to someone else) returns `NOT_HELD`, not an error. Does **not** require a pending commit — read-then-decide-not-to-write is a valid path. |

A commit does **not** auto-release the lease — agents commonly
make several commits in one editing session. Release is the
explicit "I'm done with this file" signal.

## Activity-driven lease extension

Read and write tools that target a specific path **bump the
lease's `expires_at` to `now() + ttl_seconds`** if the caller is
the holder *and* the remaining TTL is below half-life. This
applies to:

- All read tools whose argument names a single path:
  `read_content`, `read_content_batch` (per-path), `log_content`,
  `blame_content`, `diff_content`, `get_path_history`,
  `inspect_content_structure`.
- All write tools that include the leased path in their event
  descriptors.

It does **not** apply to scans across many paths
(`list_content`, `get_change_events`) — those don't single out a
particular path, so it'd be unclear which lease to extend, and
hot-path bulk queries shouldn't be writing to `path_leases`.

Agents are bad at estimating how long they'll take. Activity-
driven extension means a holder that's still actively working
won't have their lease expire under them; a holder that's gone
silent for longer than the TTL releases the path for everyone
else.

## Metadata fields

The metadata fields each tool surfaces (`last_changed_at`,
`changed_by`, `commit_message`, `semantic_summary`) come from
direct columns on `events` and `commits` — strictly faster than
parsing `git blame --porcelain`, and considerably richer. See
[02-data-model.md](./02-data-model.md) for the underlying schema.
