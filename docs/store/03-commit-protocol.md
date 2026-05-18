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
than raw file changes. The descriptor fields and per-kind
requirements are in
[02-data-model.md § EventDescriptor](./02-data-model.md#eventdescriptor);
the contract behaviour (atomicity, conflict detection, lock
granularity, errors) is in
[01-storage-backend.md § Contract](./01-storage-backend.md#contract).
All v1 events are file-grain.

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

        # 2b-bis. Preconditions: per-kind path existence and optional
        #         expected_before_sha. Any mismatch aborts the whole bundle.
        #         See 01 § Contract for the typed errors raised here.
        for e in event_descriptors:
            current = await db.tree_entry_at(parent_commit_id, e.path)
            if e.kind == 'created' and current is not None:
                raise PathExistsError(e.path)
            if e.kind in ('replaced', 'patched', 'deleted', 'renamed') and current is None:
                raise PathNotFoundError(e.path, parent_commit_id)
            if e.kind == 'renamed':
                if await db.tree_entry_at(parent_commit_id, e.new_path) is not None:
                    raise PathExistsError(e.new_path)
            if e.expected_before_sha is not None:
                if current is None or current.blob_sha != e.expected_before_sha:
                    raise ConflictError(e.path, e.expected_before_sha,
                                        current.blob_sha if current else None)
            e.before_sha = current.blob_sha if current else None

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

The precondition errors raised in step 2b-bis
(`PathNotFoundError`, `PathExistsError`, `ConflictError`) are
caller-visible — they propagate out of `commit()` unwrapped, so
the MCP write tools and HTTP handlers can translate them to
domain-appropriate responses. Other aborts (transient Postgres
errors, lock acquisition failures, etc.) surface as
`CommitAbortedError` with the underlying exception in its cause
chain. See
[01-storage-backend.md § Errors](./01-storage-backend.md#errors).

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
