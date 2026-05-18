# 08 — Phasing

The rollout for this design across four phases plus a 2.5 sub-
phase. Each phase is independently shippable and dogfoodable on
ReasonFlow.

## Phase 1 — Storage backend protocol + in-memory fake

Define `StorageBackend` with the methods listed in
[01-storage-backend.md](./01-storage-backend.md). Write
`InMemoryBackend` against it — Python dicts and lists, no
Postgres, no S3, deterministic in tests. Migrate every caller in
the codebase (MCP tools, search indexer, admin endpoints) from
reaching directly into the git directory to calling
`StorageBackend` methods. After Phase 1, the codebase talks to an
abstract backend; the data side is empty until an operator
populates it.

This phase ships **no production data path** — it's a code-only
refactor. Existing tests are rewritten to run against
`InMemoryBackend`; new tests run against it directly. How the
current git-backed deployment continues to operate during Phase 1
(parallel deploy, isolation, etc.) is an operator decision, not a
spec deliverable.

## Phase 2 — `S3CASBackend`: events on a single timeline

Postgres schema migration (`commits`, `events`, `tree_entries`,
`blobs`, `refs` — see [02-data-model.md](./02-data-model.md)), S3
wiring, full commit protocol (see
[03-commit-protocol.md](./03-commit-protocol.md)), and
`get_change_events` / `get_path_history` / `get_event` (see
[04-tool-surface.md](./04-tool-surface.md)). `S3CASBackend` slots
in behind the same `StorageBackend` Protocol Phase 1 stood up —
caller code does not change. All events are file-grain in v1;
sub-file grain and branches are both deferred (see
[09-open-questions.md](./09-open-questions.md)).

Bringing existing content (ReasonFlow or anyone else's) into
`S3CASBackend` stores is out of scope for this design — see
[00-overview.md § Out of scope](./00-overview.md#out-of-scope).
Phase 2 ships an empty-store-capable backend; how operators
populate their stores is their decision (the import endpoint from
Phase 2.5 covers the common path of "drop a tarball in").

## Phase 2.5 — Import from archive

Ship the `imports` table, the REST endpoint, the streaming
pipeline (emitting events per entry plus per-`replace`-mode
deletions), and the admin-UI modal. See
[05-import.md](./05-import.md) for the full design.

Lands after Phase 2 stabilizes on ReasonFlow so we have a real
backend to import into. The first real exercise of the import
endpoint is also the migration story for any operator moving
content into the S3CAS backend from outside.

## Phase 3 — Semantic patches and structured diff UX

Add the structured-patch column workflow: writers (especially
agents) attach a typed patch alongside the bytes diff.
`diff_content` surfaces the patch when present. Build the
admin-UI "path history" timeline that consumes `get_path_history`
and `semantic_summary` for human-readable change logs.

## Phase 4 — Performance

Switch `tree_entries` materialization from "full snapshot per
commit" to "snapshot every N commits + deltas" (see
[02-data-model.md § tree_entries materialization](./02-data-model.md#tree_entries-materialization-full-snapshot-vs-delta)).
Add the GC job (see
[06-garbage-collection.md](./06-garbage-collection.md)) for
unreferenced blobs and orphaned events. Add the optional
`snapshots/<commit_id>.json` manifest in S3 if read fanout
becomes a bottleneck. Tune events indexes once real query
patterns are visible.
