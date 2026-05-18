# 06 — Garbage collection

Orphan blobs accumulate from failed-phase-2 commits (see
[03-commit-protocol.md](./03-commit-protocol.md)) and eventually
from pruned history. Two kinds of orphan exist — rows in the
`blobs` index and objects in S3 — and the GC pass cleans both.

## The query

```sql
-- referenced shas: anything a tree_entry currently points at
WITH live AS (
  SELECT DISTINCT te.blob_sha
  FROM tree_entries te
  JOIN commits c ON c.id = te.commit_id
  WHERE c.store_id = $store
),
-- candidates: blob rows older than the quarantine that nothing
-- live references
orphans AS (
  SELECT b.sha
  FROM blobs b
  WHERE b.store_id = $store
    AND b.created_at < now() - interval '$quarantine'
    AND b.sha NOT IN (SELECT blob_sha FROM live)
)
DELETE FROM blobs WHERE store_id = $store AND sha IN (SELECT sha FROM orphans);
```

After the Postgres-side delete, issue S3 DELETEs for the same
shas. **Order matters:** drop the index row first, then the S3
object. The reverse leaves a `blobs` row pointing at a missing
object — a worse inconsistency than the converse.

## Quarantine

`GC_QUARANTINE_HOURS` defaults to 168 (7 days) to avoid racing
in-flight commits. A blob written 6 days ago by a still-running
import that hasn't yet reached phase 2 would otherwise look like
an orphan; the quarantine gives writes time to complete.

## Belt-and-braces reconciliation

As a belt-and-braces check, run a periodic `s3:ListObjectsV2`
against the blob prefix and reconcile against `blobs` — any S3
object with no `blobs` row older than the quarantine is an
orphan from a crash between phase 1b (PUT) and 1c (insert). See
[03-commit-protocol.md](./03-commit-protocol.md) for the phase 1
steps.

## Per-store scope

GC runs per-store, not globally, so a stuck tenant doesn't block
everyone else. A single-tenant pause (e.g., long-running
restore, paused worker) only delays that tenant's GC; other
tenants' garbage continues to be reclaimed.
