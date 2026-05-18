# 01 — Storage backend

This spec defines the abstract `StorageBackend` Protocol that all
storage callers in the codebase talk to. The Protocol has two
concrete implementations: `S3CASBackend` for production (described
in [02-data-model.md](./02-data-model.md) and
[03-commit-protocol.md](./03-commit-protocol.md)) and
`InMemoryBackend` for tests.

There is no `GitBackend`. The current git-backed implementation is
replaced wholesale, not wrapped behind an adapter — see
[00-overview.md](./00-overview.md) and
[08-phasing.md](./08-phasing.md).

## The Protocol

```
StorageBackend (Protocol)
├── S3CASBackend          (production — Postgres + S3)
└── InMemoryBackend       (test fake — Python dicts and lists)
```

The Protocol declares the methods every backend implements.
Every method takes `store_id` — the backend is multi-tenant and
exposes no cross-store operations.

- `commit(store_id, descriptors, author, message) -> commit_id`
- `read(store_id, path, at_commit=None, at_event=None) -> ReadResult`
- `list_paths(store_id, prefix, at_commit=None) -> list[str]`
- `get_events(store_id, filter) -> list[Event]`
- `get_path_history(store_id, path) -> list[Event]`
- `get_event(store_id, event_id) -> Event | None`
- `current_commit(store_id) -> UUID | None`

`ReadResult` carries the content plus the event-grain metadata
the MCP read tools surface (`blob_sha`, `last_changed_at`,
`changed_by`, `commit_message`, `semantic_summary`) so callers
don't pay a second round trip for blame. See
[02-data-model.md](./02-data-model.md) for the `Event`,
`EventDescriptor`, and `ReadResult` shapes.

`current_commit` exists so callers can pin a sequence of reads to
a single commit (pass the returned id as `at_commit` on
subsequent calls). Without it, two reads back-to-back may resolve
against different commits — see "Consistency" below.

No branch operations in v1; the `refs` table exists in the
schema but the Protocol exposes no methods for creating, listing,
or promoting refs. See [09-open-questions.md](./09-open-questions.md)
for the deferred-branches rationale.

## Contract

The behaviour every backend must implement, independent of
storage substrate. `InMemoryBackend` and `S3CASBackend` are both
held to this contract; tests in the layers above the Protocol
should pass identically against either.

### Atomicity

`commit()` is all-or-nothing. Either every descriptor in the
bundle lands as an event row under one `commit_id` with the ref
advanced, or no events land and the ref is unchanged. Phase 1's
S3 blobs and `blobs` rows may persist on phase-2 failure — they
are reclaimed by GC and never observable to readers
(`tree_entries` never references them). See
[03-commit-protocol.md](./03-commit-protocol.md) for the staging
mechanism.

### Consistency

**Read-after-write within a caller scope.** A caller that
awaits `commit()` and then issues a read against the same backend
instance observes the just-committed state on that read. The
backend is responsible for the mechanism (transaction reuse,
connection affinity, in-memory cache invalidation); the contract
is the observability, not the implementation.

**Across caller scopes**, reads resolve the `main` ref at request
time. Two HTTP reads served by different pods around a write may
see different commits — this is the cost of stateless fanout, not
a bug. Callers that need a stable snapshot across multiple reads
must pin via `current_commit()` + `at_commit=` and pass the same
commit id to every subsequent read.

### Optimistic concurrency

`EventDescriptor` carries an optional `expected_before_sha` field
that the backend checks against the path's current `blob_sha`
inside the commit transaction, after acquiring the per-path lock.
A mismatch raises `ConflictError` and the whole bundle aborts
— including any other descriptors that would have succeeded.

The kind itself also imposes a precondition:

| Descriptor `kind`   | Path precondition | `expected_before_sha` permitted |
| ------------------- | ----------------- | ------------------------------- |
| `created`           | must be absent    | must be `None` (kind enforces absence) |
| `replaced`          | must exist        | optional; if set, must match    |
| `patched`           | must exist        | optional; if set, must match    |
| `renamed`           | old path exists, new path absent | optional on old path |
| `deleted`           | must exist        | optional; if set, must match    |

Violating the kind precondition is a separate error from the sha
mismatch — see "Errors" below. The MCP write tools translate
their existing `expected_sha256` parameter to this field one-for-
one.

### Lock granularity

Writes serialize per `(store_id, path)`. Two `commit()` calls
touching disjoint path sets do not contend. Two `commit()` calls
that share at least one path serialize on that path; on the same
path, the second commit observes the first's result before its
precondition check runs.

Bulk operations (import) additionally take a per-store lock at
job start. This serializes whole-store rewrites without blocking
per-path writes during the bulk job's streaming phase.

The backend chooses how to acquire multiple per-path locks within
a single commit; for `S3CASBackend` the locks are acquired in
sorted-path order to avoid deadlock between concurrent multi-path
commits. `InMemoryBackend` uses a single asyncio lock per path
and the same ordering.

### Path grammar

Paths are POSIX-style, store-relative strings. The backend
rejects with `InvalidPathError`:

- empty strings
- leading `/`
- any `..` segment after normalization
- any segment containing NUL (`\0`)
- non-UTF-8 bytes

The backend does **not** enforce a maximum path length, content
type, or filename character set beyond the above — those are
higher-layer concerns (the import pipeline has its own rules; the
MCP write tools may impose more).

### Errors

The Protocol defines a typed error hierarchy that every backend
raises:

- `PathNotFoundError(path, at_commit)` — read or write of an
  absent path that the operation requires to exist.
- `PathExistsError(path)` — `created` event on an existing path,
  or `renamed` event whose new path already exists.
- `ConflictError(path, expected_sha, actual_sha)` —
  `expected_before_sha` did not match the actual current
  `blob_sha`.
- `InvalidPathError(path, reason)` — path grammar violation.
- `InvalidDescriptorError(reason)` — descriptor fields are
  internally inconsistent (e.g., `kind='renamed'` with no
  `new_path`).
- `CommitAbortedError(reason, cause)` — phase-2 transaction
  aborted for a reason not covered above (e.g., underlying
  Postgres error). The `cause` chain carries the underlying
  exception.

All six are `BackendError` subclasses. Callers above the
Protocol may catch the base class to convert to HTTP responses
or MCP error payloads.

### What the Protocol does not do

- **It does not enforce auth.** The caller is responsible for
  authorising the operation against the principal *before*
  calling `commit()`. The backend takes `author: Principal` for
  attribution, not authorisation.
- **It does not validate content type.** Bytes in, bytes out.
  Markdown structure, JSON validity, etc. are higher-layer
  concerns.
- **It does not emit events to subscribers.** The existing
  `events.py` pub/sub bus is a separate concern that wraps
  `commit()` at a higher layer.

## Why keep the abstraction at all

Three reasons, all independent of having a second production
backend:

- **Test ergonomics.** `InMemoryBackend` is ~100 lines of Python
  dicts and lists implementing the same surface as
  `S3CASBackend`. Unit tests run against it in milliseconds with
  no Postgres or S3 in the picture. Integration tests still hit
  `S3CASBackend` via testcontainers, but the unit-test fast path
  matters for everyday development.
- **Architectural firewall.** MCP tools, search indexer, admin
  endpoints can only call `StorageBackend` methods. They can't
  reach into S3CAS-internal things (table names, SQL queries, S3
  key formats). Without the firewall, those leaks accumulate and
  turn into refactoring debt years later.
- **Future optionality, cheap.** If a future use case needs a
  different backend (e.g., a `LocalFsBackend` for single-user
  Stash without Postgres), the surface is already defined. Costs
  nothing now.

The cost — one Protocol file plus the `InMemoryBackend` test fake
— is small enough that the test-ergonomics benefit alone
justifies it.

## InMemoryBackend

A pure-Python implementation backed by dicts and lists. No
Postgres connection, no S3 client, no docker. Tests against it
run in milliseconds.

The fake holds the same conceptual state as production:

```python
class InMemoryBackend:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}                       # sha -> bytes
        self.commits: list[Commit] = []
        self.events: list[Event] = []
        self.tree_entries: dict[str, dict[str, str]] = {}       # commit_id -> {path -> sha}
        self.refs: dict[str, str | None] = {"main": None}       # ref name -> commit_id
```

Reads resolve through `refs["main"]` and `tree_entries`, identical
to the Postgres-backed path. Writes follow the same commit protocol
as [03-commit-protocol.md](./03-commit-protocol.md) but skip the
S3 layer entirely — blobs are stored inline in the dict.

The fake is **not** a durable backend. It exists for unit tests
of the layers above the Protocol. It does not load from or save
to the filesystem; restarting the test process loses all state.
That's the point.

## S3CASBackend

The production implementation. See:

- [02-data-model.md](./02-data-model.md) for the Postgres schema
  and S3 layout.
- [03-commit-protocol.md](./03-commit-protocol.md) for the
  two-phase commit, concurrency, and dedup strategy.
- [04-tool-surface.md](./04-tool-surface.md) for how MCP tools
  map onto the backend.
- [06-garbage-collection.md](./06-garbage-collection.md) for the
  GC pass.
