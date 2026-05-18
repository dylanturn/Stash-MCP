# 00 — Overview

This spec series describes the change-tracking layer for
Stash-MCP that replaces the current git-backed storage with a
Postgres-metadata + S3-blob design. It's a code-and-storage
replacement, not a wrapper around the existing implementation.

The series is split across the following docs in this directory:

- [00-overview.md](./00-overview.md) — this file: motivation, out
  of scope, why-not-alternatives.
- [01-storage-backend.md](./01-storage-backend.md) —
  `StorageBackend` Protocol, `S3CASBackend` production
  implementation, `InMemoryBackend` test fake.
- [02-data-model.md](./02-data-model.md) — Postgres schema, S3
  layout, event kinds, `tree_entries` materialization.
- [03-commit-protocol.md](./03-commit-protocol.md) — Two-phase
  commit, concurrency, dedup strategy.
- [04-tool-surface.md](./04-tool-surface.md) — MCP tools mapping
  onto the new backend, plus the new event-grain query tools.
- [05-import.md](./05-import.md) — Bulk import from `.zip` /
  `.tar.gz` archives.
- [06-garbage-collection.md](./06-garbage-collection.md) —
  Periodic GC for orphan blobs.
- [07-local-dev.md](./07-local-dev.md) — RustFS in docker-compose,
  S3 implementation matrix.
- [08-phasing.md](./08-phasing.md) — Rollout phases 1–4.
- [09-open-questions.md](./09-open-questions.md) — Open questions
  and future-direction notes.

## Goal

Replace git as Stash-MCP's authoritative change tracker with a
backend that works on S3-compatible object storage *and* upgrades
the change-tracking model to something agents can actually reason
about. The replacement must keep the four capabilities git gave
us, redesigned around what makes sense for prose-and-content
stores rather than what made sense for source code:

- **History.** Read any document at any past version.
- **Attribution.** "Who last changed this file, when, with what
  intent" — file-grain, not line-grain, with optional
  writer-supplied semantic summaries.
- **Diff.** Bytes diff *and* structured patch when the writer
  supplied one, between any two points.
- **Atomic multi-file commits.** A bundle of typed change events
  lands as one commit, with a single message tying them together,
  or none of them land.

The design also has to support multi-writer concurrency with
**file-level locking** — not the merge/rebase model git
encourages — and scale past where a single git repo gets
unwieldy (hundreds of thousands of files per tenant store, with
the events table growing unbounded over time). Branching is
**out of scope for v1**; v1 ships with a single timeline per
store (see "Out of scope" below and
[09-open-questions.md](./09-open-questions.md)).

The unit of change is the **typed event**, not the commit. A
commit is a bundle of events. This flip is the lever that makes
"show me every rename last week" or "what did agent X edit in
the auth docs over the past hour" cheap index lookups instead of
recomputation from diffs. Sub-file ("section") grain attribution
is **deferred** — see
[09-open-questions.md](./09-open-questions.md); v1 events are
file-grain.

## Out of scope

- **Distributed replication / federation.** This is a server-side
  store, not a peer-to-peer system. Postgres is the source of
  truth.
- **Branches.** v1 ships with a single timeline per store
  (`main`). No branch CRUD endpoints, no `ref` parameter on
  read/write tools, no promote/merge logic. The `refs` table and
  `commits.branch_ref` column exist as nullable forward-compat
  schema (always `'main'` in v1 writes) so branches can be added
  later additively without a schema migration. Speculative
  scoping that didn't earn its way in — see
  [09-open-questions.md](./09-open-questions.md) for the
  bring-back path.
- **Sub-file ("section") grain attribution and locking.** v1
  events are file-grain. `events.section_id` is reserved as a
  nullable column for future use but always NULL in v1 writes.
- **Data migration from the current git-backed deployment.** This
  spec ships an empty-store-capable backend; moving existing
  content into it is the operator's problem, not this design's.
  Consistent with the auth design ("make migration impossible"),
  there is no in-tree migration tool, no extract-from-git script,
  and no live adapter. The import-from-archive feature (see
  [05-import.md](./05-import.md)) ingests a snapshot, not a
  commit history — operators wanting history-preserving
  migration write their own walker against their existing git
  repo and feed events through the commit protocol or the
  import pipeline.
- **Working trees / checkouts.** There's no on-disk workspace to
  check out into — readers fetch directly from Postgres + S3.

## Why not the obvious alternatives

**S3 object versioning alone.** Every PUT creates a new version,
so "history" is free — but there is no atomic multi-key commit,
no diff, no blame, and partial writes leak (an observer reading
two files directly during a write sees half-updated state).
Versioning is a useful belt-and-braces feature on the bucket, but
it can't be the primary mechanism.

**Git's object model reimplemented on S3.** Treat S3 as a
key-value store and lay out `objects/<sha>` for
blobs/trees/commits, with refs as small files. Elegant — the
data model is genuinely substrate-independent — but the moment
you need real locks, you're inventing a lock service on top of
S3. And blame/log become recursive object-graph walks instead of
indexed queries. Loses the operational advantages we picked S3
for.

**Pure event log.** Append events ("CreateFile", "EditSection",
"Delete") to a per-store log; state = replay. Clean mental
model, but point reads ("current contents of path X") force you
to either replay the log on every read or materialise an index —
and once you've materialised the index, you've built half of the
proposed design anyway.

**The pick.** Postgres holds the change-tracking metadata; S3
holds content-addressable blobs. Postgres gives ACID multi-row
commits, advisory locks, and indexed queries; S3 gives cheap
durable dedup'd blob storage. The two have a clean
responsibility split, and the direction aligns with the auth
initiative which already brings Postgres + SQLAlchemy 2.x async
into the stack.

## Cross-references

- [`docs/auth/01-persistence.md`](../auth/01-persistence.md) —
  Postgres + SQLAlchemy 2.x async foundation this design
  extends.
- [`docs-design-admin-ui.md`](../../docs-design-admin-ui.md)
  (top-level spec 07) — admin surface that will grow a per-store
  **Import** action driving
  `POST /api/<tenant>/<store>/import` (modal with file picker,
  mode radio, prefix input, progress polling), plus the "path
  history" timeline view consuming `get_path_history`. Both land
  in spec 07's follow-ups, not in this series.
- The current `TransactionManager` + `FileSystem` +
  git-directory stack in `dylanturn/Stash-MCP` is what this
  design replaces. Not wrapped or adapted — replaced. Phase 1
  ships a code-only refactor against `InMemoryBackend`; Phase 2
  ships the production `S3CASBackend`. Data handling for the
  transition is out of scope and owned by the operator.
