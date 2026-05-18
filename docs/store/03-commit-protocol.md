# 03 — Commit protocol

This spec defines how writes land. A commit is the atomic
transition that adds a bundle of events to a store and advances
the `main` ref. The schema the protocol writes into is described
in [02-data-model.md](./02-data-model.md); the MCP tools that
build event descriptors and call this protocol are in
[04-tool-surface.md](./04-tool-surface.md).

A commit lands in **two phases**. Phase 1 stages content to S3
(best-effort, idempotent). Phase 2 writes events, materializes
`tree_entries`, and advances the `main` ref — atomically.

The caller submits a list of typed **event descriptors** rather
than raw file changes. Each event descriptor carries `kind`,
`path`, the new content (if any), an optional `semantic_summary`,
and an optional `patch_blob_sha`. All v1 events are file-grain.

## The protocol

```python
async def commit(
    store_id: UUID,
    event_descriptors: list[EventDescriptor],
    author: Principal,
    message: str,
) -> UUID:

    # PHASE 1 — content to S3 (no locks, idempotent)
    # Dedup is decided in Postgres, not S3 — see "Dedup strategy" below.
    for e in event_descriptors:
        for blob_bytes in [e.after_bytes, e.patch_bytes]:
            if blob_bytes is None:
                continue
            sha = sha256(blob_bytes).hexdigest()
            e.attach_sha(blob_bytes, sha)

            # 1a. Cheap dedup check against the blobs index.
            if await db.blob_exists(store_id, sha):
                continue

            # 1b. PUT to S3. IfNoneMatch="*" is defense-in-depth.
            await s3.put_object(
                Key=blob_key(store_id, sha),
                Body=blob_bytes,
                IfNoneMatch="*",          # 412 here means index/S3 drift
            )

            # 1c. Record the blob outside the phase-2 txn. Orphans
            #     from a phase-2 failure are reclaimed by GC.
            await db.insert_blob(store_id, sha, len(blob_bytes), now())

    # PHASE 2 — events + materialized tree in one Postgres txn
    async with db.begin() as txn:
        # 2a. File-grain advisory locks. Two events on the same
        #     (store, path) serialize; events on different paths don't.
        for e in event_descriptors:
            await db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))",
                k=f"{store_id}:{e.path}",
            )

        # 2b. Lock and read the 'main' ref (the only ref in v1).
        parent_commit_id = await db.fetch_ref_for_update(store_id, 'main')

        # 2c. Create the commit row.
        commit_id = uuid4()
        await db.insert_commit(
            commit_id, store_id, parent_commit_id,
            branch_ref='main',
            author_user_id=author.user_id,
            ts=now(), message=message,
        )

        # 2d. For each descriptor, find the parent event on the same
        #     path and insert the event row.
        for e in event_descriptors:
            parent_event = await db.latest_event_for(store_id, e.path)
            await db.insert_event(
                event_id=uuid4(),
                store_id=store_id,
                commit_id=commit_id,
                parent_event_id=parent_event.id if parent_event else None,
                kind=e.kind,
                path=e.path,
                new_path=e.new_path,
                section_id=None,                          # reserved for future use
                before_blob_sha=e.before_sha,
                after_blob_sha=e.after_sha,
                patch_blob_sha=e.patch_sha,
                semantic_summary=e.semantic_summary,
                ts=now(),
            )

        # 2e. Materialize tree_entries: copy forward from parent,
        #     then apply the events in this commit.
        await db.copy_tree_entries(
            new_commit=commit_id,
            from_commit=parent_commit_id,
            except_paths=[e.path for e in event_descriptors if e.kind != 'renamed']
                         + [e.new_path for e in event_descriptors if e.kind == 'renamed'],
        )
        for e in event_descriptors:
            apply_event_to_tree_entries(commit_id, e)
            # created / replaced / patched:
            #     INSERT (commit_id, e.path, e.after_sha, len(e.after_bytes))
            # deleted:
            #     no row at e.path
            # renamed:
            #     INSERT at e.new_path with the carried-forward sha
            #     (or e.after_sha if content also changed)

        # 2f. Advance the 'main' ref — THIS IS THE COMMIT POINT.
        await db.update_ref(store_id, 'main', commit_id)

    return commit_id
```

## Failure handling

Anything before 2f that throws aborts the transaction; the only
externally-visible side effect is the S3 objects and `blobs` rows
written in phase 1, both of which become unreferenced and are
reclaimed together by the GC pass (see
[06-garbage-collection.md](./06-garbage-collection.md)). No
`events` rows leak — they live inside the same txn as the ref
update. Phase 1 is idempotent — a retry hits the `blob_exists`
check and skips both the PUT and the insert.

## Why two phases and not one

S3 PUTs are not transactional with Postgres. By writing content
first (phase 1, idempotent) and metadata second (phase 2,
atomic), the metadata transaction is the only thing that has to
be atomic — and Postgres already gives us that.

## Dedup strategy

Postgres is the authority on which blobs exist; S3 is the
storage. Concretely:

- `blobs` is the dedup index. A
  `SELECT 1 FROM blobs WHERE store_id = $1 AND sha = $2` is one
  local query — cheaper than a network round trip to S3, and
  works identically across every S3 implementation we might
  target (RustFS, AWS S3, R2) regardless of conditional-PUT
  support.
- The `IfNoneMatch="*"` header on the PUT is **defense in
  depth**, not the primary mechanism. RustFS supports conditional
  PUT as of its s3s v0.12.0-rc.5 upgrade, and AWS S3 has
  supported it since November 2024 — but we don't *rely* on it.
  If Postgres ever drifts from S3 reality (corruption, restore
  from backup, manual intervention), the 412 stops us silently
  overwriting.
- Per-store (rather than global) dedup is intentional: it keeps
  tenant content cryptographically isolated. Two tenants storing
  the same file produce two S3 objects under their own prefixes.
  Cross-tenant dedup would be a separate, opt-in feature with
  different security tradeoffs.

## Concurrency

Locks are file-grain and uniform: every event takes
`pg_advisory_xact_lock(hashtextextended("store_id:path", 0))`.
Imports and other bulk ops additionally take a store-grain lock
keyed on `"store_id"` so two store-wide operations serialize.

Two events on different paths don't contend. Two events on the
same path serialize on the advisory lock — the second writer
waits for the first to commit, then sees the new
`tree_entries` / `events` state on its next read.

Locks are held only for the duration of the metadata transaction
in phase 2 — short, a handful of inserts plus the ref update.
They are not held during phase 1 (S3 PUTs), so payload size
doesn't widen contention windows.

Sub-file ("section") locking is **out of scope for v1**. Two
agents editing different parts of the same file will serialize.
If usage patterns later show that's expensive, sections come back
— additively, since `events.section_id` is reserved for it. See
[09-open-questions.md](./09-open-questions.md).

## Path leases

The file-grain advisory locks above hold for the duration of one
phase-2 transaction — milliseconds. They prevent torn writes but
do **nothing** to protect an agent from the wasted-reasoning
race:

```
Agent A: read_content("docs/auth.md")          # sees state at event E1
Agent A: (thinks for 30 seconds, costs N tokens)
Agent B: edit_content("docs/auth.md", ...)     # commits E2
Agent A: edit_content("docs/auth.md", ...)     # commits E3, silently overwriting B
```

Path leases give agents a tool to opt into pessimistic isolation
across the multi-tool-call work that produces a write. An agent
that knows it's going to take time to read, reason, and decide
acquires a lease on the path before reading; other agents trying
to write that path back off until the lease is released, cancelled,
or expires.

### What a lease is

A row in `path_leases` (schema in
[02-data-model.md](./02-data-model.md)) keyed by
`(store_id, path)`. The row carries:

- `holder_id` — the principal that owns the lease
- `acquired_at` — when the lease was first taken
- `expires_at` — current TTL deadline; bumped by holder activity
- `ttl_seconds` — the per-extension TTL, used to recompute
  `expires_at` when the holder does work against the path

While the lease is held and unexpired, **only the holder may
commit events on that path**. Reads are unaffected — any agent
may read the path at any time.

### Acquisition and extension

`lease_path(path, ttl_seconds)`:

```python
async def lease_path(store_id, path, holder, ttl_seconds) -> LeaseInfo | Locked:
    async with db.begin():
        # Brief advisory lock so two acquisitions don't race.
        await db.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))",
            k=f"lease:{store_id}:{path}",
        )

        existing = await db.fetch_lease(store_id, path)

        # Treat an expired lease as absent (lazy GC).
        if existing and existing.expires_at <= now():
            await db.delete_lease(store_id, path)
            existing = None

        if existing is None:
            # Fresh acquisition.
            new = await db.insert_lease(
                store_id=store_id,
                path=path,
                holder_id=holder.user_id,
                acquired_at=now(),
                expires_at=now() + ttl_seconds,
                ttl_seconds=ttl_seconds,
            )
            return LeaseInfo.from_row(new)

        if existing.holder_id == holder.user_id:
            # Same holder reacquiring → extend.
            new_expires = now() + ttl_seconds
            await db.update_lease(
                store_id, path,
                expires_at=new_expires,
                ttl_seconds=ttl_seconds,
            )
            return LeaseInfo(...)

        # Someone else holds it.
        return Locked(
            held_by=existing.holder_id,
            expires_at=existing.expires_at,
        )
```

Calling `lease_path` against a lease the caller already holds is
idempotent and serves as an explicit extension — the holder can
re-set the TTL deliberately ("I'm about to think for 5 minutes,
don't let this expire"). If the TTL passed is different from the
stored value, the new value takes over for subsequent
activity-extensions.

### Activity-driven extension

Agents are bad at estimating how long they'll take. To avoid
making them micro-manage TTLs, **any read or write the holder
performs on the leased path extends the lease**, provided the
remaining TTL is below half-life. Concretely, at the entry of
every read or write tool:

```python
async def maybe_extend_lease(store_id, path, principal):
    lease = await db.fetch_lease(store_id, path)
    if lease is None:
        return
    if lease.holder_id != principal.user_id:
        return
    if lease.expires_at <= now():
        return  # expired; another agent will likely take it next
    remaining = (lease.expires_at - now()).total_seconds()
    if remaining < lease.ttl_seconds / 2:
        await db.update_lease_expires_at(
            store_id, path, now() + lease.ttl_seconds,
        )
```

Below-half-life is the trigger so we don't write to `path_leases`
on every read — most reads are no-ops. A burst of activity from
the holder keeps the lease alive indefinitely; silence for longer
than the TTL lets it expire.

Activity that counts:

- `read_content(path)`, `read_content_batch(paths)`,
  `log_content(path)`, `blame_content(path)`,
  `diff_content(path, ...)`, `get_path_history(path)`,
  `inspect_content_structure(path)` — any tool whose argument
  *names* the leased path.
- Any write through `commit()` whose event descriptors include
  the leased path.

Activity that does **not** count:

- `list_content(prefix)` even if the leased path is under the
  prefix — the call doesn't single out the leased path.
- `get_change_events(filter)` — filtered scans across many
  paths.
- Reads from other principals — only the holder's activity
  extends.

### Release

`release_path_lease(path)`:

```python
async def release_path_lease(store_id, path, holder):
    lease = await db.fetch_lease(store_id, path)
    if lease is None or lease.holder_id != holder.user_id:
        return ReleaseResult.NOT_HELD   # idempotent no-op
    await db.delete_lease(store_id, path)
    return ReleaseResult.RELEASED
```

Releasing a lease the caller doesn't hold is a no-op, not an
error. Agents can call this defensively in cleanup paths.

Releasing does **not** require there to be a pending commit; an
agent that read, leased, and then decided not to write should
still release. The lease holding past usefulness is a
correctness-irrelevant but throughput-relevant cost — other
agents are blocked until the explicit release, TTL expiry, or
forced cancellation.

A commit does **not** automatically release the lease. Agents
often want to make several commits during one editing session;
release is an explicit signal that the work is done. If the
agent forgets to release, the lease holds until TTL or until
activity stops.

### How the commit protocol checks leases

Phase 2 of `commit()` (see "The protocol" above) gains one new
check, between step 2a and step 2b:

```python
# 2a-bis. Reject if any path is leased by a different principal.
for e in event_descriptors:
    lease = await db.fetch_lease(store_id, e.path)
    if lease is None or lease.expires_at <= now():
        continue                          # no active lease — fine
    if lease.holder_id != author.user_id:
        raise PathLeased(
            path=e.path,
            held_by=lease.holder_id,
            expires_at=lease.expires_at,
        )
    # Holder is committing on their own leased path — extend.
    if (lease.expires_at - now()).total_seconds() < lease.ttl_seconds / 2:
        await db.update_lease_expires_at(
            store_id, e.path, now() + lease.ttl_seconds,
        )
```

`PathLeased` is the new failure mode. Callers see it instead of
silently overwriting another agent's work in progress. The agent
that loses the race can: wait until `expires_at`, work on a
different path, fail back to the user, or — if they have a real
reason — escalate to an admin who can forcibly release the lease.

### Janitor

Expired leases get cleaned up by a periodic job:

```sql
DELETE FROM path_leases WHERE expires_at < now();
```

Lazy cleanup also happens on every `lease_path` call (the
expired-treat-as-absent step). The janitor is a backstop for
paths that nobody happens to be acquiring leases on. It runs
per-store, like GC.

### Admin override

An admin endpoint
(`DELETE /api/<tenant>/<store>/leases/<path>?force=true`,
tenant-admin auth) forcibly releases a lease regardless of
holder. Useful for unsticking a tenant where an agent crashed
holding a lease and the TTL hasn't expired yet. Logged as an
audit event so the original holder can see what happened on its
next read.
