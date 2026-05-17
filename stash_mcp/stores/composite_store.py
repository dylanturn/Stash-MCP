"""``CompositeLoadedStore`` — masquerades as a single LoadedStore
that's actually composed from multiple underlying stores.

Returned by :class:`McpServerResolverMiddleware` (spec 04) when a
scoped token's MCP-server config has been resolved. Downstream code
(``_fs()``, ``_bare_fs()``, tool handlers) treats it identically to a
single-store ``LoadedStore``.

The composite's ``git_backend`` and ``transaction_manager`` are
non-None only when the config references exactly one underlying store
— those primitives bind to a single git repo / single TX context.
Multi-store composites set both to None and the runtime allowlist
check (spec 04's ``_instrumented_tool``) refuses git/tx tools on them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .composite_filesystem import CompositeFileSystem


@dataclass
class CompositeLoadedStore:
    tenant_id: uuid.UUID
    tenant_slug: str
    store_id: uuid.UUID  # synthetic — composite has no single store_id
    store_slug: str       # use the config slug for display purposes
    filesystem: CompositeFileSystem
    git_backend: object | None
    transaction_manager: object | None
    underlying_store_ids: frozenset[uuid.UUID]
    mcp_server_id: uuid.UUID
    display_name: str

    @property
    def is_single_store(self) -> bool:
        return len(self.underlying_store_ids) == 1

    @property
    def fs_for_mcp(self) -> CompositeFileSystem:
        """The FileSystem MCP tools should use.

        For multi-store composites this is always the composite itself
        (no transaction wrapping — transactions are single-store-only).
        For single-store composites the underlying transaction-wrapped
        FS is already woven into the composite at construction time.
        """
        return self.filesystem
