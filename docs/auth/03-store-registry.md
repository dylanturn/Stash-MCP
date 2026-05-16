# 03 — StoreRegistry + per-store content layer

## Goal

Turn the single-`FileSystem`-per-server model into a per-store one. Each
store gets its own `FileSystem`, `GitBackend`, and `TransactionManager`,
all instantiated lazily by a `StoreRegistry` keyed by `(tenant_id,
store_slug)` and hydrated from the `stores` table. Add the startup
invariant that refuses to start if `CONTENT_DIR` shape disagrees with
`STASH_AUTH_ENABLED`.

This chunk is purely the content layer. Routing changes
(`/mcp/<tenant>/<store>/`, `/api/<tenant>/<store>/*`) are in 04. Tools
and route handlers still see a single
`FileSystem` instance — but it's now resolved per-request from the
registry.

## Out of scope

- HTTP routing changes — 04.
- Admin endpoints for store CRUD (creating a store row + initializing its
  repo on disk) — 05. This spec exposes the `StoreRegistry.provision()`
  helper that 05 calls.
- Search index per-store. Search stays scoped to the legacy single-index
  in v1; the index just covers all stores merged together. Splitting the
  index is a future concern.

## Files added

```
stash_mcp/stores/__init__.py
stash_mcp/stores/registry.py        # StoreRegistry
stash_mcp/stores/layout.py          # CONTENT_DIR shape check + path resolver
tests/stores/__init__.py
tests/stores/test_layout.py
tests/stores/test_registry.py
```

## Files modified

```
stash_mcp/main.py                   # call layout check; register Default
                                    # tenant's first store on startup
stash_mcp/config.py                 # add STASH_DEFAULT_STORE_SLUG (default
                                    # "default") — used only when AUTH_ENABLED=False
```

No changes to `filesystem.py`, `git_backend.py`, or `transactions.py` —
the registry composes existing types. This is "wrappers over rewrites" in
action.

## Design

### Layout invariant (`stash_mcp/stores/layout.py`)

Two functions plus one exception type.

```python
from pathlib import Path
from ..config import Config

class ContentLayoutError(SystemExit):
    """Raised at startup when CONTENT_DIR shape disagrees with AUTH_ENABLED."""

def validate_content_layout() -> None:
    """Refuse to start if the directory shape disagrees with AUTH_ENABLED.

    AUTH_ENABLED=True requires CONTENT_DIR to either be empty or contain
    only `<tenant>/<store>/` shaped subdirectories.  Any top-level file or
    a single-level subdirectory triggers refusal.

    AUTH_ENABLED=False requires CONTENT_DIR to NOT contain `<tenant>/<store>/`
    shape — operators flipping AUTH on/off mid-deployment is the bug we're
    catching. Migration path: stand up a fresh content dir, copy content
    into a tenant/store, then enable auth.
    """
    root = Config.CONTENT_DIR
    root.mkdir(parents=True, exist_ok=True)

    children = [p for p in root.iterdir() if not p.name.startswith(".")]
    if not children:
        return  # empty CONTENT_DIR is valid in both modes

    has_tenant_shape = _looks_tenant_shaped(children)

    if Config.AUTH_ENABLED:
        if not has_tenant_shape:
            raise ContentLayoutError(
                f"STASH_AUTH_ENABLED=true but {root} contains content that is "
                f"not in <tenant>/<store>/ layout. Stash refuses to mix layouts; "
                f"see docs/auth/README.md."
            )
    else:
        if has_tenant_shape:
            raise ContentLayoutError(
                f"STASH_AUTH_ENABLED=false but {root} appears to be in "
                f"<tenant>/<store>/ layout. Set STASH_AUTH_ENABLED=true or "
                f"use a different content dir."
            )

def _looks_tenant_shaped(children: list[Path]) -> bool:
    """Heuristic: every visible top-level entry is a directory, and its
    contents (if any) are themselves directories — those are the stores.

    An empty tenant directory IS valid: `tenant create` provisions a row
    but doesn't touch disk, so a freshly-restarted server may also see no
    tenant dirs at all. The on-disk dir is created lazily by the first
    `store provision` for that tenant.

    A `.git` directory or other dotfile at any level is ignored.
    """
    if not children:
        # Empty CONTENT_DIR is valid in both auth-on and auth-off modes;
        # callers distinguish based on AUTH_ENABLED.
        return True
    for tenant_dir in children:
        if not tenant_dir.is_dir():
            return False
        stores = [s for s in tenant_dir.iterdir() if not s.name.startswith(".")]
        # Empty tenant_dir is valid — tenant exists in DB, no stores yet.
        for store_dir in stores:
            if not store_dir.is_dir():
                return False
    return True

def store_root(tenant_id: str, store_slug: str) -> Path:
    """Absolute path to a store's content root."""
    return Config.CONTENT_DIR / tenant_id / store_slug
```

The heuristic is intentionally conservative — it errs toward refusing to
start. If an operator has weird stray files in `CONTENT_DIR`, the error
message points them to docs.

Tenant directories are named by tenant **UUID**, not slug. Slugs can be
renamed; UUIDs can't. The slug is a human label; the on-disk path is
stable.

### `StoreRegistry` (`stash_mcp/stores/registry.py`)

```python
from dataclasses import dataclass
from uuid import UUID
import asyncio
import logging
from sqlalchemy import select

from ..config import Config
from ..filesystem import FileSystem
from ..git_backend import GitBackend
from ..transactions import TransactionManager
from ..db.models import Store, Tenant
from ..db.session import get_sessionmaker
from .layout import store_root

logger = logging.getLogger(__name__)

@dataclass
class LoadedStore:
    tenant_id: UUID
    tenant_slug: str
    store_id: UUID
    store_slug: str
    filesystem: FileSystem            # may be wrapped by transaction_manager
    git_backend: GitBackend | None
    transaction_manager: TransactionManager | None

    @property
    def fs_for_mcp(self) -> FileSystem:
        """The FileSystem instance MCP tools and REST handlers should use —
        same as `filesystem`, but with the transaction manager wrapping in if
        present."""
        return self.transaction_manager or self.filesystem


class StoreRegistry:
    def __init__(self):
        self._stores: dict[tuple[UUID, str], LoadedStore] = {}
        self._lock = asyncio.Lock()

    async def _load(self, tenant_slug: str, store_slug: str) -> LoadedStore:
        async with get_sessionmaker()() as session:
            stmt = (
                select(Store, Tenant)
                .join(Tenant, Tenant.id == Store.tenant_id)
                .where(Tenant.slug == tenant_slug, Store.slug == store_slug)
            )
            row = (await session.execute(stmt)).one_or_none()
            if row is None:
                raise KeyError(f"store {tenant_slug}/{store_slug} not found")
            store, tenant = row

        root = store_root(str(tenant.id), store_slug)
        if not root.exists():
            raise StoreNotProvisionedError(
                f"store {tenant.slug}/{store_slug} has a row but no on-disk repo at {root}"
            )

        fs = FileSystem(root, include_patterns=Config.CONTENT_PATHS)
        git = None
        txn = None
        if (root / ".git").exists():
            git = GitBackend(root, author_default=Config.GIT_AUTHOR_DEFAULT)
            git.validate()
            if not Config.READ_ONLY:
                txn = TransactionManager(fs, git)

        return LoadedStore(
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            store_id=store.id,
            store_slug=store.slug,
            filesystem=fs,
            git_backend=git,
            transaction_manager=txn,
        )

    async def get(self, tenant_slug: str, store_slug: str) -> LoadedStore:
        """Resolve by tenant slug (URL-stable) + store slug. The slug → UUID
        translation happens inside _load(). Caching is keyed by slug pair
        because slug rename invalidates the URL anyway."""
        key = (tenant_slug, store_slug)
        if key not in self._stores:
            async with self._lock:
                if key not in self._stores:
                    self._stores[key] = await self._load(tenant_slug, store_slug)
        return self._stores[key]

    async def provision(
        self,
        *,
        tenant_id: UUID,
        tenant_slug: str,
        store_slug: str,
        git_remote_url: str | None,
        git_branch: str = "main",
    ) -> LoadedStore:
        """Called from the admin API in 05. Creates the on-disk repo,
        clones from remote if given, then loads the store. Caller passes
        both tenant_id (for path) and tenant_slug (for cache key) since
        admin endpoints already have both."""
        root = store_root(str(tenant_id), store_slug)
        if root.exists() and any(root.iterdir()):
            raise StoreAlreadyProvisionedError(str(root))
        root.mkdir(parents=True, exist_ok=True)

        if git_remote_url:
            GitBackend.clone(
                url=git_remote_url,
                target_dir=root,
                branch=git_branch,
                token=Config.GIT_SYNC_TOKEN,
                recursive=Config.GIT_SYNC_RECURSIVE,
            )
        else:
            # init an empty repo so transactions work
            GitBackend.init(root)

        return await self.get(tenant_slug, store_slug)

    def invalidate(self, tenant_slug: str, store_slug: str) -> None:
        """Drop a cached LoadedStore (e.g. after store deletion or remote-URL
        change). Also called after a tenant slug rename — caller invalidates
        every cached store under the old slug."""
        self._stores.pop((tenant_slug, store_slug), None)


class StoreNotProvisionedError(RuntimeError): ...
class StoreAlreadyProvisionedError(RuntimeError): ...


_registry: StoreRegistry | None = None

def get_store_registry() -> StoreRegistry:
    global _registry
    if _registry is None:
        _registry = StoreRegistry()
    return _registry
```

`GitBackend.init()` is new — a class method that runs `git init` and sets
an initial commit. If `git_backend.py` doesn't already have this, add it
as part of this chunk (it's a 10-line addition).

### Auth-disabled mode (single legacy store)

When `AUTH_ENABLED=False`, the existing single-`CONTENT_DIR` behavior is
preserved. The registry never gets consulted — `main.create_app()` builds
the MCP server and the REST API against the legacy `FileSystem(CONTENT_DIR)`
exactly as it does today. Specs 03 and 04 only diverge from current
behavior under AUTH_ENABLED.

This is the "no migration" posture made concrete: a deployment is either in
legacy mode or in auth/multi-store mode, never mixed.

### Wiring in `main.create_app()`

```python
from .stores.layout import validate_content_layout
from .stores.registry import get_store_registry

def create_app():
    validate_content_layout()   # always runs; raises if shape mismatches

    if Config.AUTH_ENABLED:
        Config.validate_auth_config()
        # Don't pre-load any stores here. Stores are loaded lazily by the
        # router (spec 04) when a request resolves a (tenant, store).
        registry = get_store_registry()
        # ...build app with a per-store resolver that's wired in spec 04
    else:
        # legacy path, unchanged
        filesystem = FileSystem(Config.CONTENT_DIR, include_patterns=Config.CONTENT_PATHS)
        ...
```

In this chunk, the AUTH_ENABLED branch in `create_app` is allowed to be
*incomplete* — it can fall through to a 503 ("auth enabled but routing
not wired") for `/api` and `/mcp`. Spec 04 wires the real routes. The UI
redirect-to-login path from 02 still works because it runs at the
middleware layer.

## Test plan

- `tests/stores/test_layout.py`
  - AUTH=False + empty dir → ok.
  - AUTH=False + flat content (current shape) → ok.
  - AUTH=False + tenant-shaped → raises.
  - AUTH=True + empty → ok.
  - AUTH=True + flat content → raises.
  - AUTH=True + tenant-shaped → ok.
  - AUTH=True + tenant dir present but EMPTY (post-`tenant create`,
    pre-store-provision) → ok. **This is B1's regression test.**
  - AUTH=True + mix of empty tenant dirs and tenant dirs with stores → ok.
  - `.git` and other dotfiles at root don't trigger false positives.
- `tests/stores/test_registry.py`
  - `get()` loads a store with a real on-disk repo (use `tmp_path`).
  - Second `get()` returns the cached instance (identity equality).
  - `invalidate()` causes the next `get()` to reload.
  - `provision()` with no remote creates an init'd repo; subsequent `get()`
    returns a LoadedStore with `git_backend` set and `transaction_manager`
    set (READ_ONLY=False).
  - `provision()` on an existing non-empty dir raises.
  - Concurrent `get()` calls for the same key load only once
    (use `asyncio.gather` with a slow `_load` to verify).
  - Loading a store row whose on-disk path is missing → `StoreNotProvisionedError`.

## Acceptance

- `validate_content_layout()` runs on every `create_app()` call.
- Auth-disabled mode behaves identically to current `main`.
- Auth-enabled mode boots, but `/api` and `/mcp` return 503 (will be 200 in
  04). Login flow still 302s in browser (no regression of 02).
- `uv run pytest tests/stores tests/auth` passes.
- Existing `tests/` suite passes.

## Open questions

**Should the search index be per-store?** Current answer: no, v1 keeps one
shared index. The index dir lives outside `CONTENT_DIR`. The single search
engine reads files from whichever store's `FileSystem` is asked. Cross-
tenant search leakage is the risk — the search API in 04 must filter
results to the current principal's accessible stores, or just disable
search outside auth-disabled mode in v1. **Default v1 stance: search is
only available when AUTH_ENABLED=False.** Search-with-auth is a follow-on
chunk after the v1 ships. Worth confirming this is acceptable.

## Notes for the Claude Code session

- Tenant directories on disk are named by **UUID**, not slug. Slugs are for
  URLs and UI; directories use UUIDs so renaming a tenant slug doesn't
  require moving files.
- `tenant create` does NOT create the on-disk tenant directory. The
  directory is created lazily by the first `store provision` for that
  tenant — `mkdir(parents=True)` in `provision()` will create the
  `<tenant_uuid>/` along the way. An empty tenant therefore has zero
  on-disk footprint. (The layout validator accepts empty tenant dirs
  too, for cases where stores were provisioned and later removed.)
- `StoreRegistry` is process-wide. In a multi-pod deployment (stateless HTTP
  mode), each pod has its own registry instance — that's fine, since the
  DB is the source of truth and each pod lazy-loads what it needs.
- Don't add a `list_stores()` method to the registry yet. Listing happens
  via SQL queries in 05's admin endpoints, not via the in-memory cache.
- The TransactionManager is *only* wrapped in when `READ_ONLY=False` and
  `git_backend` exists, matching the current `main.py` logic.
