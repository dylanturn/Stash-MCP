"""Per-store :class:`FileSystem` / :class:`GitBackend` / :class:`TransactionManager`
bundle, resolved lazily by ``(tenant_slug, store_slug)``.

The registry is process-wide. In a multi-pod deployment each pod has
its own instance and lazy-loads what it needs — the DB is the source of
truth.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from ..config import Config
from ..db.models import Store, Tenant
from ..db.session import get_sessionmaker
from ..filesystem import FileSystem
from ..git_backend import GitBackend
from ..transactions import TransactionManager
from .layout import store_root

logger = logging.getLogger(__name__)


class StoreNotProvisionedError(RuntimeError):
    """Store row exists but the on-disk repo is missing."""


class StoreAlreadyProvisionedError(RuntimeError):
    """``provision()`` called against a path that already has content."""


@dataclass
class LoadedStore:
    tenant_id: UUID
    tenant_slug: str
    store_id: UUID
    store_slug: str
    filesystem: FileSystem
    git_backend: GitBackend | None
    transaction_manager: TransactionManager | None

    @property
    def fs_for_mcp(self) -> FileSystem | TransactionManager:
        """The FileSystem MCP tools and REST handlers should use — the
        transaction-wrapped form when writes are enabled, otherwise the
        bare filesystem."""
        return self.transaction_manager or self.filesystem


class StoreRegistry:
    def __init__(self) -> None:
        self._stores: dict[tuple[str, str], LoadedStore] = {}
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
                f"store {tenant.slug}/{store_slug} has a row but no on-disk "
                f"repo at {root}"
            )

        fs = FileSystem(root, include_patterns=Config.CONTENT_PATHS)
        git: GitBackend | None = None
        txn: TransactionManager | None = None
        if (root / ".git").exists():
            git = GitBackend(root, author_default=Config.GIT_AUTHOR_DEFAULT)
            git.validate()
            if not Config.READ_ONLY:
                txn = TransactionManager(fs, git)

        logger.info(
            "Loaded store %s/%s from %s (git=%s, txn=%s)",
            tenant_slug,
            store_slug,
            root,
            git is not None,
            txn is not None,
        )
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
        """Resolve by ``(tenant_slug, store_slug)``. Caches the result.

        The slug → UUID translation happens inside ``_load``. Cache is
        keyed by slug because a slug rename invalidates the URL anyway
        — callers in 05 invalidate the entry on rename.
        """
        key = (tenant_slug, store_slug)
        cached = self._stores.get(key)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._stores.get(key)
            if cached is not None:
                return cached
            loaded = await self._load(tenant_slug, store_slug)
            self._stores[key] = loaded
            return loaded

    async def provision(
        self,
        *,
        tenant_id: UUID,
        tenant_slug: str,
        store_slug: str,
        git_remote_url: str | None,
        git_branch: str = "main",
    ) -> LoadedStore:
        """Create the on-disk repo for a store row (called by admin API in 05).

        Either clones from ``git_remote_url`` or runs ``git init``. Caller
        passes both ``tenant_id`` (for the on-disk path) and
        ``tenant_slug`` (for the cache key) — admin endpoints already
        have both, so we don't re-query.
        """
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
            GitBackend.init(root, author_default=Config.GIT_AUTHOR_DEFAULT)

        return await self.get(tenant_slug, store_slug)

    def invalidate(self, tenant_slug: str, store_slug: str) -> None:
        """Drop a cached :class:`LoadedStore`. Used after store deletion,
        a remote-URL change, or a tenant-slug rename (callers invalidate
        every cached store under the old slug)."""
        self._stores.pop((tenant_slug, store_slug), None)


_registry: StoreRegistry | None = None


def get_store_registry() -> StoreRegistry:
    global _registry
    if _registry is None:
        _registry = StoreRegistry()
    return _registry


def reset_store_registry() -> None:
    """Drop the process-wide registry. Test-only."""
    global _registry
    _registry = None
