"""Shared store provisioning/rename/delete operations.

Both the global-admin router (``/admin/tenants/{id}/stores``) and the
tenant-admin router (``/tenants/{id}/stores``) call into this module so
the two surfaces can't drift. Audit rows are written here so the actor
is whoever called us.
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.principal import Principal
from ..db.models import (
    AuditEvent,
    McpServer,
    McpServerMount,
    Store,
    Tenant,
)
from ..db.session import get_sessionmaker as get_session_factory
from ..errors import StoreAlreadyExists, StoreInUse, StoreNotFound
from .layout import store_root
from .registry import StoreAlreadyProvisionedError, get_store_registry

logger = logging.getLogger(__name__)


class StoreCreate(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    display_name: str = Field(..., min_length=1, max_length=255)
    git_remote_url: str | None = Field(default=None)
    git_branch: str = Field(default="main")


class StoreUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    git_remote_url: str | None = Field(default=None)
    git_branch: str | None = Field(default=None)


def _audit(
    session: AsyncSession,
    *,
    actor: Principal,
    action: str,
    target_kind: str,
    target_id: str,
    tenant_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            actor_kind="user",
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            tenant_id=tenant_id,
            detail=json.dumps(detail) if detail else None,
        )
    )


async def provision_store(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant: Tenant,
    body: StoreCreate,
) -> Store:
    """Create the DB row, audit, then call the registry to provision on disk.

    On disk failure, deletes the row before re-raising so the operator
    can retry without a duplicate-slug collision.
    """
    existing = (
        await session.execute(
            select(Store).where(
                Store.tenant_id == tenant.id, Store.slug == body.slug
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise StoreAlreadyExists(
            f"store {tenant.slug}/{body.slug} already exists"
        )

    store = Store(
        tenant_id=tenant.id,
        slug=body.slug,
        display_name=body.display_name,
        git_remote_url=body.git_remote_url,
        git_branch=body.git_branch,
    )
    session.add(store)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise StoreAlreadyExists(
            f"store {tenant.slug}/{body.slug} already exists"
        ) from exc

    _audit(
        session,
        actor=actor,
        action="store.provisioned",
        target_kind="store",
        target_id=str(store.id),
        tenant_id=tenant.id,
        detail={
            "tenant_slug": tenant.slug,
            "slug": store.slug,
            "git_remote_url": body.git_remote_url,
            "git_branch": body.git_branch,
        },
    )
    # Commit so the registry's own session can see the row.
    await session.commit()
    await session.refresh(store)
    store_id = store.id
    tenant_slug = tenant.slug
    store_slug = store.slug

    registry = get_store_registry()
    try:
        await registry.provision(
            tenant_id=tenant.id,
            tenant_slug=tenant_slug,
            store_slug=store_slug,
            git_remote_url=body.git_remote_url,
            git_branch=body.git_branch,
        )
    except StoreAlreadyProvisionedError as exc:
        raise StoreAlreadyExists(
            f"store {tenant_slug}/{store_slug} already provisioned on disk: {exc}"
        ) from exc
    except Exception:
        # Drop the just-created row so the admin can retry.
        async with get_session_factory()() as cleanup:
            row = await cleanup.get(Store, store_id)
            if row is not None:
                await cleanup.delete(row)
                await cleanup.commit()
        raise

    return store


async def rename_store(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant: Tenant,
    store: Store,
    body: StoreUpdate,
) -> Store:
    """Update display_name / git_remote_url / git_branch.

    Slug is not editable — it's part of the mount path. If
    ``git_remote_url`` changes we also run ``git remote set-url`` on the
    live repo so the DB and disk don't silently disagree.
    """
    changes: dict[str, dict[str, Any]] = {}
    if body.display_name is not None and body.display_name != store.display_name:
        changes["display_name"] = {
            "old": store.display_name,
            "new": body.display_name,
        }
        store.display_name = body.display_name
    if body.git_remote_url is not None and body.git_remote_url != store.git_remote_url:
        changes["git_remote_url"] = {
            "old": store.git_remote_url,
            "new": body.git_remote_url,
        }
        store.git_remote_url = body.git_remote_url
    if body.git_branch is not None and body.git_branch != store.git_branch:
        changes["git_branch"] = {
            "old": store.git_branch,
            "new": body.git_branch,
        }
        store.git_branch = body.git_branch

    if not changes:
        return store

    # If the git remote URL changed, attempt to update the on-disk repo's
    # remote so the next sync pulls from the right place.
    if "git_remote_url" in changes:
        root = store_root(str(tenant.id), store.slug)
        git_dir = root / ".git"
        if git_dir.exists():
            from ..git_backend import GitBackend

            try:
                backend = GitBackend(root)
                new_url = changes["git_remote_url"]["new"]
                if new_url:
                    backend.set_remote_url("origin", new_url)
            except Exception as exc:
                logger.warning(
                    "Failed to update on-disk remote for %s/%s: %s",
                    tenant.slug,
                    store.slug,
                    exc,
                )

        # Invalidate the cached LoadedStore so the next request reloads.
        get_store_registry().invalidate(tenant.slug, store.slug)

    _audit(
        session,
        actor=actor,
        action="store.renamed",
        target_kind="store",
        target_id=str(store.id),
        tenant_id=tenant.id,
        detail=changes,
    )
    await session.commit()
    await session.refresh(store)
    return store


async def deprovision_store(
    session: AsyncSession,
    *,
    actor: Principal,
    tenant: Tenant,
    slug: str,
) -> None:
    """Invalidate the registry, rmtree the on-disk repo, audit, delete the row."""
    store = (
        await session.execute(
            select(Store).where(
                Store.tenant_id == tenant.id, Store.slug == slug
            )
        )
    ).scalar_one_or_none()
    if store is None:
        raise StoreNotFound(f"store {tenant.slug}/{slug} not found")

    # Refuse if any MCP-server config mounts this store. The
    # ``mcp_server_mounts.store_id`` FK is RESTRICT so the DB would
    # also refuse, but doing it explicitly lets us name the offending
    # config(s) in the error.
    mount_rows = (
        (
            await session.execute(
                select(McpServer.slug)
                .join(
                    McpServerMount,
                    McpServerMount.mcp_server_id == McpServer.id,
                )
                .where(McpServerMount.store_id == store.id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if mount_rows:
        raise StoreInUse(
            f"store {tenant.slug}/{store.slug} is mounted by the following "
            f"mcp-server config(s): {sorted(set(mount_rows))}"
        )

    registry = get_store_registry()
    registry.invalidate(tenant.slug, store.slug)

    on_disk = store_root(str(tenant.id), store.slug)
    if on_disk.exists():
        try:
            shutil.rmtree(on_disk)
        except OSError as exc:
            logger.error("Failed to remove on-disk store %s: %s", on_disk, exc)
            raise

    _audit(
        session,
        actor=actor,
        action="store.deleted",
        target_kind="store",
        target_id=str(store.id),
        tenant_id=tenant.id,
        detail={"tenant_slug": tenant.slug, "slug": store.slug},
    )
    await session.delete(store)
    await session.commit()


__all__ = [
    "StoreCreate",
    "StoreUpdate",
    "provision_store",
    "rename_store",
    "deprovision_store",
]
