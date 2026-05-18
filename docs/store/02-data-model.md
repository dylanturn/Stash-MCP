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

## EventDescriptor

The caller's input to `commit()` — one descriptor per intended
event. Fields split into **caller-supplied** (what the writer
knows) and **derived** (filled in by the commit machinery). See
[03-commit-protocol.md](./03-commit-protocol.md) for how the
derived fields are computed.

```
EventDescriptor:
  # caller-supplied
  kind                 'created' | 'replaced' | 'patched' | 'renamed' | 'deleted'
  path                 str                       # POSIX-relative; see 01 path grammar
  new_path             str | None                # required iff kind == 'renamed'
  after_bytes          bytes | None              # required for created/replaced/patched
                                                 # and for renamed if content changed
  patch_bytes          bytes | None              # optional; structured patch document
  semantic_summary     str | None                # optional; writer-authored prose
  expected_before_sha  str | None                # optional optimistic-concurrency token;
                                                 # see 01 § Optimistic concurrency

  # derived during commit
  before_sha           str | None                # read from tree_entries in phase 2
  after_sha            str | None                # sha256(after_bytes), phase 1
  patch_sha            str | None                # sha256(patch_bytes), phase 1
```

The shape of a descriptor is checked at the Protocol boundary; an
internally inconsistent descriptor (e.g., `kind='renamed'` with no
`new_path`, or `kind='created'` with `expected_before_sha` set)
raises `InvalidDescriptorError` before any side effects. The
required-field matrix:

| `kind`     | `path` | `new_path` | `after_bytes` | `patch_bytes` | `expected_before_sha` |
| ---------- | ------ | ---------- | ------------- | ------------- | --------------------- |
| `created`  | yes    | —          | yes           | optional      | must be `None`        |
| `replaced` | yes    | —          | yes           | optional      | optional              |
| `patched`  | yes    | —          | yes           | yes           | optional              |
| `renamed`  | yes    | yes        | iff content changes | optional | optional (checked on old path) |
| `deleted`  | yes    | —          | —             | —             | optional              |

`patched` requires both `after_bytes` and `patch_bytes`: the
patch is the intent / auditable record, and the resulting bytes
are stored so reads don't have to replay the patch chain. The
two must be consistent (`apply(before_bytes, patch) == after_bytes`),
but consistency is the writer's responsibility, not the backend's.

## Protocol-exposed types

The Python-level types every backend returns from
`StorageBackend` methods. Defined here so callers can code
against a stable shape without depending on the SQL schema or on
ORM models.

```
Author:
  user_id        UUID | None       # NULL = system / automation;
                                   # matches commits.author_user_id
  display_name   str               # surfaced as "changed_by" on reads;
                                   # "system" when user_id is None

Event:
  # event row, joined with its commit for cheap attribution
  id                 UUID
  store_id           UUID
  commit_id          UUID
  parent_event_id    UUID | None
  kind               str           # see "Event kinds"
  path               str
  new_path           str | None
  before_blob_sha    str | None
  after_blob_sha     str | None
  patch_blob_sha     str | None
  semantic_summary   str | None
  ts                 datetime

  # denormalized from the join on commits
  author             Author
  commit_message     str
  commit_ts          datetime

ReadResult:
  content            bytes
  path               str           # the path read; identical to the request
                                   # unless resolved through a rename chain
  blob_sha           str
  size_bytes         int
  commit_id          UUID          # commit the read resolved against
  last_event_id      UUID          # last event on path at/before commit_id
  last_event_kind    str
  last_changed_at    datetime      # = last event ts
  changed_by         Author        # = last event's commit author
  commit_message     str           # message of the commit that owned that event
  semantic_summary   str | None    # from the last event

EventFilter:
  # all fields optional; AND'd together
  paths              list[str] | None       # exact paths
  path_prefix        str | None             # tree_entries-style prefix
  kinds              list[str] | None       # subset of the event kinds
  authors            list[UUID | None] | None  # None inside list = system
  since              datetime | None        # events.ts >= since
  until              datetime | None        # events.ts <  until
  commit_id          UUID | None
  limit              int | None             # default and max enforced by backend
  cursor             str | None             # opaque pagination token
```

`Author.display_name` is populated by the backend at query time —
the contract guarantees a non-empty string even for system
commits (`"system"` is the canonical placeholder; backends are
free to localise but must not return empty). Callers that need
the raw `user_id` for further joins should use that field, not
parse `display_name`.

`Event` is denormalized for read convenience: every `Event`
returned from the Protocol carries the commit's `author`,
`message`, and `ts` fields, so a `get_path_history` call returns
everything `blame_content` needs without a second round trip.

`ReadResult.path` differs from the request only when a future
read-through-rename mechanism is added (deferred); in v1 the two
are always equal.

`EventFilter.cursor` is opaque — backends choose the encoding
(keyset on `(ts, id)`, page token, etc.). Callers must pass it
back verbatim; comparing or constructing one is undefined
behaviour.

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
