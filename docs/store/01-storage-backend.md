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

The Protocol declares the methods every backend implements:

- `commit(list[EventDescriptor], author, message) -> commit_id`
- `get_events(filter) -> list[Event]`
- `get_path_history(path) -> list[Event]`
- `read(path, at_commit=None, at_event=None) -> bytes`
- `list_paths(prefix) -> list[str]`

Return types carry event-grain fields (`kind`, `semantic_summary`,
`patch_blob_sha`) — every backend produces them. See
[02-data-model.md](./02-data-model.md) for the `Event` and
`EventDescriptor` shapes.

No branch operations in v1; the `refs` table exists in the
schema but the Protocol exposes no methods for creating, listing,
or promoting refs. See [09-open-questions.md](./09-open-questions.md)
for the deferred-branches rationale.

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
