# 02 — Data model

This spec defines the Postgres schema, S3 layout, and event-kind
enum that the storage layer is built on. The commit protocol that
writes into these tables is described in
[03-commit-protocol.md](./03-commit-protocol.md); the MCP tools
that read from them are described in
[04-tool-surface.md](./04-tool-surface.md).

## Primary unit: events, not commits

The change-tracking unit is the **event**, not the commit. An
event records *what changed*, *at what granularity*, *by whom*,
*with what intent* — typed and queryable. A commit is a *bundle*
of events that landed together with a shared message and parent;
useful as a transactional boundary, not as the place where
semantics live.

This flips the framing inherited from git, where commits are the
unit and "what changed within a commit" is something you recompute
by diffing. Here, "what changed" is a column, and questions like
"show me every rename in the last week" or "what files did agent
X edit in `docs/auth/` since the release" are index lookups, not
graph walks.

`tree_entries` survives as a **materialized current-state view**
— the resolved `(commit_id, path) → blob_sha` snapshot at each
commit — but it's *derived from* the events, not the primary
record. If you dropped `tree_entries` and rebuilt it from
`events`, you'd get the same answer; you can't do that the other
way around.

## Postgres schema (additions)

These tables sit alongside the auth tables (`tenants`, `users`,
`stores`, …) defined in
[`docs/auth/01-persistence.md`](../auth/01-persistence.md). The
`stores` table is unchanged — "the current commit" is now
resolved through `refs` (defaulting to the `main` row), not
stored on the store itself.

```
commits(
  id              UUID PK,
  store_id        UUID REF stores,
  parent_id       UUID REF commits NULL,    -- linear timeline in v1
  branch_ref      TEXT NOT NULL DEFAULT 'main',
                                            -- always 'main' in v1; reserved for future branch use
  author_user_id  UUID REF users NULL,      -- NULL = system/automation
  ts              TIMESTAMPTZ NOT NULL,
  message         TEXT NOT NULL             -- bundle-level message;
                                            -- per-event prose lives on events.semantic_summary
)

events(
  id                UUID PK,
  store_id          UUID REF stores,
  commit_id         UUID REF commits,         -- the bundle this event was part of
  parent_event_id   UUID REF events NULL,     -- previous event on the SAME path
  kind              TEXT NOT NULL,            -- see "Event kinds" below
  path              TEXT NOT NULL,
  new_path          TEXT NULL,                -- only for kind = 'renamed'
  section_id        TEXT NULL,                -- always NULL in v1; reserved for future sub-file grain
  before_blob_sha   CHAR(64) NULL,            -- NULL for 'created'
  after_blob_sha    CHAR(64) NULL,            -- NULL for 'deleted'
  patch_blob_sha    CHAR(64) NULL,            -- optional structured patch
  semantic_summary  TEXT NULL,                -- writer-supplied prose
  ts                TIMESTAMPTZ NOT NULL
)
CREATE INDEX events_path_idx     ON events (store_id, path, ts DESC);
CREATE INDEX events_commit_idx   ON events (commit_id);
CREATE INDEX events_kind_idx     ON events (store_id, kind, ts DESC);

tree_entries(
  commit_id   UUID REF commits,
  path        TEXT,
  blob_sha    CHAR(64) NOT NULL,            -- S3 key suffix, joins blobs.sha
  size_bytes  BIGINT NOT NULL,
  PRIMARY KEY (commit_id, path)
)
CREATE INDEX tree_entries_path_idx
  ON tree_entries (path, commit_id DESC);
-- Materialized at commit time: for each commit, the resolved
-- (path -> blob_sha) snapshot. Derived from the events in that
-- commit plus the parent commit's tree_entries. Reads go here;
-- writes update it as the last step of the commit protocol.

blobs(
  store_id    UUID REF stores,
  sha         CHAR(64),                     -- sha256 of content, S3 key suffix
  size_bytes  BIGINT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (store_id, sha)
)
-- Purpose: dedup check before S3 PUT, GC inventory, per-store storage
-- accounting. A blob lives in S3 iff its row exists here. The
-- absence of a row is authoritative: never assume an S3 object
-- exists just because something in Postgres references its sha.

refs(
  store_id   UUID REF stores,
  name       TEXT,                          -- exactly one row per store in v1: name = 'main'
  commit_id  UUID REF commits,
  PRIMARY KEY (store_id, name)
)
```

No `sections` table in v1. Sub-file grain attribution is deferred
— `events.section_id` is a nullable column reserved for that
future use but always NULL in v1 writes. See
[09-open-questions.md](./09-open-questions.md) for the
bring-back path.

The `imports` table — used by the import endpoint — is defined in
[05-import.md](./05-import.md) alongside the rest of the import
design.

## Event kinds

```
created   — path did not exist; after_blob_sha is the initial content.
            before_blob_sha NULL.
replaced  — path existed; whole-file rewrite.
            Both blob_shas set.
patched   — change expressed as a structured patch (not bytes).
            patch_blob_sha set; after_blob_sha is the resulting file.
renamed   — path changed; new_path set.
            Content may or may not change; if it does, after_blob_sha differs.
deleted   — path removed; before_blob_sha set; after_blob_sha NULL.
```

`patch_blob_sha`, when set, points at a structured patch document
(tree-diff for markdown, JSON Patch for structured docs, etc.)
stored as a blob in S3 like any other. Readers can use it instead
of byte-diffing the before/after blobs. The format is open-ended
per content type; the only contract is "this blob describes the
delta in a way agents can read."

`semantic_summary` is writer-authored prose describing the change
intent — "added two paragraphs about the new retry behaviour,"
"renamed config keys to match v2 schema." Optional but encouraged;
the MCP write tools surface it as an explicit parameter (see
[04-tool-surface.md](./04-tool-surface.md)).

## tree_entries materialization: full snapshot vs. delta

The simple model writes one `tree_entries` row per (commit, path)
for every path — full snapshot per commit, materialized from
`events` + the parent commit's `tree_entries` at commit time. At
~100k files and frequent commits this is wasteful storage even if
it's fast to read.

The phase-4 optimisation (see [08-phasing.md](./08-phasing.md)):

- Every Nth commit writes a **full snapshot** to `tree_entries`.
- Intermediate commits write only **changed paths** (the paths
  named by their own events).
- Reads union the latest snapshot with the deltas since (also
  recoverable directly from `events` if `tree_entries` is dropped
  — `tree_entries` is a cache, not the source of truth).

The `events` table never participates in this compaction. Every
event is durable forever (subject to whatever pruning policy
lands later — see [09-open-questions.md](./09-open-questions.md)).
That's the whole point: the history of *what changed* is the
load-bearing record. `tree_entries` exists for read perf.

No `line_blame` table. The per-line attribution that table would
have stored is replaced by file-grain attribution: "what last
event touched this file" — answered by an index lookup on
`events_path_idx`, not a materialization. See
[04-tool-surface.md](./04-tool-surface.md) for how
`blame_content` resolves this.

## S3 layout

```
s3://<bucket>/<tenant>/<store>/blobs/<sha[0:2]>/<sha>
s3://<bucket>/<tenant>/<store>/snapshots/<commit_id>.json   # optional, perf phase
```

- Sharded by first two hex chars of the sha to spread S3
  partition load.
- Blobs are written with `If-None-Match: *` for idempotent dedup
  — a re-uploaded identical file is a no-op.
- The bucket should have **object versioning enabled** as a
  backstop (recovery from accidental deletes), but Stash-MCP does
  **not** use S3 versions as the change-tracking mechanism.
  Version IDs are not surfaced to callers.
