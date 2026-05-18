# 09 — Open questions and future directions

The questions and ideas in this spec are intentionally outside
the v1 ship surface — they're decisions to revisit once real
deployment data is available, or pieces of speculative scope
that were cut from v1 and might be added back later. Nothing in
here is a v1 deliverable.

## Future directions

Five ideas that the events redesign enables but doesn't commit
to. Each is *additive* over the v1 schema — no migration, no
breaking change — and worth revisiting once we have real
deployment data.

**Sub-file ("section") grain attribution.** v1 events are
file-grain: `blame_content` answers "who last touched this
file." Adding section grain means populating `events.section_id`
(reserved as a nullable column for this purpose), introducing a
section-identity mechanism (markers in markdown, or some
file-type-specific equivalent), and adding section-grain locks +
optimistic-version checks. The tradeoffs — invasive marker
insertion, section identity for non-markdown content,
splits/renames — were the reason this didn't ship in v1.
Revisit if usage shows agents serializing heavily on
shared-file edits, or if "what changed in section X" becomes a
common query.

**Branches.** v1 ships a single timeline per store. The `refs`
table and `commits.branch_ref` column are reserved as nullable
forward-compat schema (always `'main'` in v1). Bringing branches
back means adding the branch CRUD endpoints
(`POST/GET/DELETE /api/<t>/<s>/refs`), threading a `ref`
parameter through every read and write tool, and designing the
promote operation — replay-based with conflict surfacing, no
auto-merge. Revisit if usage shows agents wanting isolation for
risky multi-step edits, or if "draft and discard / draft and
merge" becomes a common workflow. Until then, the same effect
can be approximated with a path convention (e.g., write drafts
under `drafts/<id>/`, promote by rename, discard by delete).

**Time-travel-by-criteria reads.** Today reads accept
`at_commit`. Once we have query patterns from real agents, it'd
be cheap to add `as_of_time`, `as_of_event_kind`, or "the last
commit by author X." All translate to the same `tree_entries`
lookup keyed by a different commit-resolution rule. Adding them
prematurely risks shipping query shapes nobody uses; deferring
costs nothing.

**Audit log split from version history.** The current design
treats `commits` + `events` as both the version-control record
and the audit log. They have different shapes: audit events
(reads, auth checks, permission grants) are append-only and
never queried for state reconstruction, while version events
power reads. Splitting into a separate `audit_events` table
keeps each hot in cache for its actual access pattern. Worth
doing once audit-log query volume is measurable; premature
otherwise.

**Drop "commit" as the user-facing unit.** Agents don't think in
commits — they think in sessions, tasks, or requests. The
`commits` table could be reframed as "change groups" of
arbitrary duration: an agent's 20-minute editing session lands
as one change group with N events, rather than N commits each
with one event. Schema-compatible — `commits` already groups
events — but the UX, defaults, and CLI/API naming would all
shift. Wait for usage signal before pulling this in: if agents
naturally emit one event per commit, the rename buys nothing;
if they batch heavily, "change group" stops feeling like a
euphemism.

## Open questions

- **Which Postgres SKU.** Two load patterns to size for: the
  copy-forward-per-commit step in `tree_entries` materialization
  (write-heavy at commit time, with all paths copied forward
  into the new commit's snapshot) and the `events` table's
  unbounded growth plus its three indexes (read-heavy across
  path, kind, and commit dimensions). Worth measuring on a
  representative store before committing to managed Postgres
  tier sizing. Events partitioning by `store_id` may become
  attractive past some threshold; defer until profiling
  indicates.
- **Diff algorithm at scale.** `difflib` is fine for sub-megabyte
  text. For larger files, `diff-match-patch` or a Rust binding
  (`similar` via PyO3) becomes worth it. Decide after profiling.
  The structured-patch path (Phase 3) sidesteps this for writes
  that supply a patch; it only matters for fallback byte-diffs.
- **Read-after-write within a request.** A writer who commits
  and then immediately reads should see their own write. S3 is
  read-after-write consistent for new keys; the worry is the
  metadata side. Solved by reading through the same Postgres
  connection (or a serialisable txn) within a request, but
  should be made explicit in the `StorageBackend` contract.
- **What "the current commit" means for HTTP read fanout.**
  Stateless HTTP across pods means each read resolves the `main`
  ref from Postgres at request time. That's fine, but a fast
  succession of writes can serve different reads from different
  commits — caller-visible. Document the semantics; the
  existing optional `at_commit` / `at_event` parameters on the
  read tools cover the "I need stable reads across multiple
  calls" use case.
- **Event retention policy.** Events are durable forever in the
  v1 design. At some scale we'll want to prune — but pruning an
  event the `tree_entries` snapshot doesn't reference is safe;
  pruning one the snapshot still depends on is not. A "compact
  events older than N months into a single synthetic event"
  pass is conceivable but premature. Revisit once we have
  growth data.
- **Single-region vs. multi-region S3.** Out of scope for v1,
  but the design accommodates either — blob keys are
  content-addressed, so cross-region replication can be
  S3-level, not application-level. The `events` and
  `tree_entries` tables would still be region-pinned to a
  Postgres primary; multi-region writes would need a different
  design entirely.
