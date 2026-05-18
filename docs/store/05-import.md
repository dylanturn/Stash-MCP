# 05 — Import from archive

Bulk-load a `.zip` or `.tar.gz` into a store as a single atomic
commit. This is the bootstrap path for a new store (drop a
tarball of existing docs and turn the server on against it) and
the ongoing path for periodic snapshot ingest from external
sources.

The commit produced by an import goes through the same protocol
as any other commit — see
[03-commit-protocol.md](./03-commit-protocol.md) — just with the
event descriptors built from archive entries instead of from MCP
write tools.

## Schema addition

The `imports` table tracks async import job state, added with
this feature:

```
imports(
  id                   UUID PK,
  store_id             UUID REF stores,
  requested_by         UUID REF users,
  mode                 TEXT NOT NULL,        -- 'merge' | 'replace' | 'subtree'
  prefix               TEXT NULL,            -- only for mode = 'subtree'
  archive_name         TEXT NOT NULL,
  archive_size_bytes   BIGINT NOT NULL,
  archive_sha256       CHAR(64) NOT NULL,    -- hash of the uploaded archive itself
  status               TEXT NOT NULL,        -- 'queued' | 'running' | 'committed' | 'failed' | 'cancelled'
  files_processed      INT NOT NULL DEFAULT 0,
  bytes_processed      BIGINT NOT NULL DEFAULT 0,
  started_at           TIMESTAMPTZ NULL,
  finished_at          TIMESTAMPTZ NULL,
  error                TEXT NULL,
  resulting_commit_id  UUID REF commits NULL  -- set on status = 'committed'
)
CREATE INDEX imports_store_recent_idx
  ON imports (store_id, started_at DESC);
```

## Surface

```
POST   /api/<tenant>/<store>/import
GET    /api/<tenant>/<store>/import/<job_id>
DELETE /api/<tenant>/<store>/import/<job_id>      # cancel a queued/running job
```

**`POST`** — multipart upload. Form fields:

| Field      | Required             | Description                                                                |
| ---------- | -------------------- | -------------------------------------------------------------------------- |
| `archive`  | yes                  | The `.zip` or `.tar.gz` file. Type sniffed from magic bytes, not filename. |
| `mode`     | yes                  | `merge` \| `replace` \| `subtree`. Caller picks per-import.                |
| `prefix`   | iff `mode = subtree` | Path prefix to extract under. Must be a valid relative path with no `..` segments. |
| `message`  | no                   | Commit message. Default: `Import: <archive_name> (<N> files)`.             |

Returns `202 Accepted` with
`{"job_id": "<uuid>", "status": "queued"}` and a `Location`
header pointing at the GET endpoint.

**`GET`** — returns the `imports` row as JSON, plus the resulting
commit id once `status = 'committed'`. Callers poll this for
progress (`files_processed`, `bytes_processed`).

**UI integration.** The admin UI (top-level spec 07) grows a
per-store **Import** action that opens a modal: file picker, mode
radio, prefix input (shown only for `subtree`), optional message.
Submit hits the POST endpoint; the modal then polls GET and shows
a progress bar until terminal state.

## Authorization

Importing requires the caller to hold the **`admin` role on the
tenant containing the target store**. Not write — admin.

The reasoning: an import in `replace` mode can wipe a store, and
even in `merge` or `subtree` mode it can overwrite arbitrary
paths in bulk. The blast radius justifies tenant-admin gating
even though the underlying primitive (the commit protocol) is
accessible to writers.

Auth check happens in middleware before the upload body is read.
Anonymous, unauthenticated, or write-only callers get `403` with
a Problem-Details body before any bytes are streamed.

## Modes

Each mode produces exactly **one commit** with one parent (the
current head of `main`). The difference between modes is which
**events** the commit contains and what `tree_entries` ends up
looking like after materialization.

- **`merge`** — for each archive path, emit either a `created`
  event (path absent in parent) or `replaced` event (path exists
  in parent with different content). Paths in the parent that
  aren't in the archive get no event — they copy forward
  unchanged. Default least-destructive behaviour.

- **`replace`** — same `created` / `replaced` events for the
  paths in the archive, **plus** a `deleted` event for every
  path present in the parent but absent from the archive. After
  materialization, `tree_entries` for the new commit contains
  exactly the paths in the archive. The deleted paths' blobs
  remain referenced by historical commits, so history isn't lost
  — the dropped content is still readable at the parent commit
  and surfaces in `log_content` / `get_change_events` as
  `deleted` events.

- **`subtree`** — same as `merge`, but every archive path is
  rewritten as `<prefix>/<path>` before being applied. Events
  carry the rewritten path. `prefix` is validated for `..`
  segments and absolute paths and rejected if it would escape
  the store root.

The commit's bundle `message` is the user-supplied message (or
the default `Import: <archive_name> (<N> files)`). Each event
also gets a per-event `semantic_summary` of the form
`Imported from <archive_name>:<entry_path>`, so per-file
attribution in `blame_content` and `log_content` shows the
provenance of imported content rather than just "this was part
of import job X."

## Streaming pipeline

The whole import is one commit, but the *processing* is streamed
— a 5 GB archive is never buffered in memory or on disk in full.

```
1. Validate (synchronous, before 202):
   - Caller has tenant-admin role on the target tenant
   - Archive size ≤ MAX_IMPORT_BYTES (default 5 GB, configurable)
   - mode + prefix are coherent

2. Persist the upload to a staging key:
   - s3://<bucket>/<tenant>/<store>/staging/imports/<job_id>.zip
   - Streamed via multipart; archive_sha256 computed while streaming.
   - The staging copy is what the worker reads; the upload connection
     can close as soon as the upload completes.

3. Insert imports row (status = 'queued'); return 202.

4. Worker picks up the job:
   - status → 'running', started_at = now()
   - Open archive from staging key as a stream:
     - zipfile.ZipFile with a streaming wrapper, or
     - tarfile.open(mode='r|gz', fileobj=...) for tar.gz
   - For each entry, build an `EventDescriptor` (don't commit yet):
       a. Reject if entry is a symlink, device node, or special file.
       b. Normalize the path; reject if it escapes the import root
          (zip-slip protection: any '..' or absolute path).
       c. If mode = 'subtree', prepend the prefix.
       d. Skip directory entries (we don't store directories).
       e. Stream the entry's content through a sha256 hasher into S3:
            - If the running sha (computed at the end of the stream)
              already exists in `blobs`, discard the in-progress
              multipart upload — content already stored.
            - Otherwise commit the multipart upload as the blob key.
            - Insert the blobs row.
       f. Determine the event kind:
            - `created` if no tree_entries row exists at the final
              path on the parent commit.
            - `replaced` if a row exists with a different blob_sha.
            - skip the entry entirely if the row exists with the same
              blob_sha (already-present content, nothing to record).
          Build the EventDescriptor with kind, path, before/after
          shas, and a `semantic_summary` of "Imported from
          <archive_name>:<entry_path>".
       g. Bump files_processed / bytes_processed every N entries
          (e.g., every 100) so the GET endpoint shows progress.
   - All entries processed.
       - If mode = 'replace': diff the archive path set against the
         parent commit's tree_entries; emit a `deleted` event for
         each parent path not in the archive.
       - If mode = 'merge' or 'subtree': no deletions; non-archive
         paths copy forward.
   - Call the commit protocol with the accumulated EventDescriptor
     list. The protocol writes all events under one commit_id and
     materializes tree_entries atomically.

5. On success:
   - status → 'committed'
   - resulting_commit_id = the new commit
   - finished_at = now()
   - Delete the staging archive (cleanup; not part of the commit).

6. On failure (mid-stream or commit txn aborts):
   - status → 'failed', error = <message>, finished_at = now()
   - Orphan blobs in S3 and `blobs` rows are reclaimed by GC
     (see [06-garbage-collection.md](./06-garbage-collection.md)).
   - Staging archive is retained until GC quarantine expires
     (lets the operator inspect what failed).
```

## Safety controls

Imports run code on adversary-influenced content. The safeguards
are not optional.

- **Zip slip.** Every entry path is normalized
  (`os.path.normpath` equivalent in Python's
  `pathlib.PurePosixPath`) and checked to ensure it does not
  start with `/` or contain `..` segments after normalization.
  Failing entries abort the whole import, not just skipped —
  partial imports would be surprising.
- **Symlinks and special files.** Refused outright. Stash-MCP
  has no symlink semantics, and `tar`'s symlink targets are a
  classic exploit vector.
- **Decompression bombs.** Cap the *expanded* size at
  `MAX_EXPANDED_BYTES` (default 50 GB) and the *ratio* of
  expanded to compressed size at `MAX_EXPANSION_RATIO` (default
  100). Either trip → abort with
  `error = "expansion limit exceeded"`.
- **File count.** Cap entries at `MAX_FILES_PER_IMPORT` (default
  100 000). Above this, callers should split the import.
- **Per-file size.** Cap individual files at `MAX_FILE_BYTES`
  (default 1 GB). Files above this are skipped with a per-file
  error appended to the job, but don't abort the whole import —
  outlier-tolerant, deliberately.
- **Filename encoding.** Zip's encoding metadata is unreliable.
  Decode filenames as UTF-8 strict, with a fallback to CP437
  (the zip spec's legacy default). Anything that fails both is
  rejected with the entry name reported as hex bytes in the
  error.
- **Concurrent imports.** Two imports against the same store
  serialize on a per-store advisory lock acquired at job start,
  not at the phase-2 commit. This avoids the case where two
  concurrent `replace` imports interleave their phase-2 commits
  and produce a deterministic but counter-intuitive winner.

## Failure model

An import is *one* commit or *zero* commits. There is no
partial-import state. Mid-stream failure leaves the staging
archive (for post-mortem) and a `failed` row in `imports`, plus
orphan blobs in S3 + `blobs` that GC reclaims after the
quarantine. The store contents from the caller's perspective
are unchanged from the pre-import state until the phase-2 commit
lands atomically.

This matters because the commit row only appears on success — log
/ blame / read tools never see a half-imported state.

## Out of scope (for v1)

- **Resumable uploads.** A failed 5 GB import has to be retried
  in full. The staging-key indirection sets us up to add resume
  semantics later, but the v1 ships without them.
- **Streaming export.** The inverse — dumping a store to a
  `.tar.gz` for backup or migration — is its own design with
  overlapping concerns (per-commit vs. current-tree, blob
  streaming, auth). Worth a follow-up spec.
- **Format auto-detection beyond `.zip` / `.tar.gz`.** No `.7z`,
  no `.rar`, no `.tar.xz`. Adding a format means adding a parser
  and a fuzzing target; do it deliberately.
- **Importing into a non-empty store via `replace`** *without
  warning the caller.* The endpoint's contract is "you asked,
  you get what you asked for" — the UI's responsibility to show
  the confirmation modal, not the API's.
