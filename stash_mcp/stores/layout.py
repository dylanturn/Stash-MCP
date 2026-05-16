"""CONTENT_DIR shape invariant + path resolver for the per-store layout."""

from __future__ import annotations

from pathlib import Path

from ..config import Config


class ContentLayoutError(SystemExit):
    """Raised at startup when CONTENT_DIR shape disagrees with AUTH_ENABLED."""


def validate_content_layout() -> None:
    """Refuse to start if the directory shape disagrees with AUTH_ENABLED.

    AUTH_ENABLED=True requires CONTENT_DIR to either be empty or contain
    only ``<tenant>/<store>/``-shaped subdirectories. Any top-level file
    or a single-level subdirectory triggers refusal.

    AUTH_ENABLED=False requires CONTENT_DIR to NOT be in
    ``<tenant>/<store>/`` shape — operators flipping AUTH on/off
    mid-deployment is the bug we're catching. Migration path: stand up a
    fresh content dir, copy content into a tenant/store, then enable
    auth.
    """
    root = Config.CONTENT_DIR
    root.mkdir(parents=True, exist_ok=True)

    children = [p for p in root.iterdir() if not p.name.startswith(".")]
    if not children:
        return

    has_tenant_shape = _looks_tenant_shaped(children)

    if Config.AUTH_ENABLED:
        if not has_tenant_shape:
            raise ContentLayoutError(
                f"STASH_AUTH_ENABLED=true but {root} contains content that is "
                "not in <tenant>/<store>/ layout. Stash refuses to mix layouts; "
                "see docs/auth/README.md."
            )
    else:
        if has_tenant_shape:
            raise ContentLayoutError(
                f"STASH_AUTH_ENABLED=false but {root} appears to be in "
                "<tenant>/<store>/ layout. Set STASH_AUTH_ENABLED=true or "
                "use a different content dir."
            )


def _looks_tenant_shaped(children: list[Path]) -> bool:
    """Heuristic: every visible top-level entry is a directory, and any
    contents inside it are themselves directories — those are the stores.

    An empty tenant directory IS valid: ``tenant create`` provisions a
    row but doesn't touch disk, so a freshly-restarted server may also
    see no tenant dirs at all. The on-disk dir is created lazily by the
    first ``store provision`` for that tenant.

    Dotfiles (``.git``, ``.DS_Store``, etc.) at any level are ignored by
    the caller before we get here.
    """
    if not children:
        return True
    for tenant_dir in children:
        if not tenant_dir.is_dir():
            return False
        stores = [s for s in tenant_dir.iterdir() if not s.name.startswith(".")]
        for store_dir in stores:
            if not store_dir.is_dir():
                return False
    return True


def store_root(tenant_id: str, store_slug: str) -> Path:
    """Absolute path to a store's content root.

    ``tenant_id`` is the tenant UUID (as a string) — directory names are
    UUIDs, not slugs, so renaming a tenant slug doesn't require moving
    files. ``store_slug`` is the store's slug; renaming a store DOES
    move the directory (callers in 05 handle that).
    """
    return Config.CONTENT_DIR / tenant_id / store_slug
