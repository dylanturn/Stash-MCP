"""``/tenants/{tenant_id}/mcp-servers/*`` HTTP handlers.

CRUD for the per-tenant MCP-server configuration metadata defined in
``db.models`` (``McpServer``, ``McpServerTool``, ``McpServerMount``).
Configs live inert until spec 03 wires tokens to them and spec 04 turns
them on at runtime.

Validation rules enforced here (defense-in-depth — the UI also
prevents these):

- ``kind='simple'`` servers have at most one mount (zero or one) and
  its ``virtual_prefix`` must be empty; ``kind='virtual'`` must have
  at least one mount.
- All mounted stores must belong to the config's tenant (no
  cross-tenant mounts).
- Mount ``virtual_prefix`` and ``subpath`` are normalized; ``..``
  segments are rejected.
- Within one server, no two mounts may share a ``virtual_prefix`` or
  have one as a prefix of another (path-collision rule).
- Tool names must be in ``REGISTERED_TOOL_NAMES``.
- A config that spans more than one underlying store cannot enable any
  of the git/transaction tools (``_MULTI_STORE_DISALLOWED_TOOLS``).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..admin.dependencies import require_tenant_admin
from ..auth.principal import Principal
from ..db.models import (
    AuditEvent,
    McpServer,
    McpServerMount,
    McpServerTool,
    Store,
    Tenant,
)
from ..db.session import get_session
from ..errors import (
    ConfirmationRequired,
    McpServerAlreadyExists,
    McpServerMultiStoreGitForbidden,
    McpServerNotFound,
    MountConflict,
    MountCrossTenant,
    MountInvalid,
    StoreNotFound,
    TenantNotFound,
    ToolNameInvalid,
    ValidationError,
)
from ..mcp_listing import broadcast_catalog_changed
from ..mcp_server import _MULTI_STORE_DISALLOWED_TOOLS, REGISTERED_TOOL_NAMES

# --- request models ---------------------------------------------------------


class MountInput(BaseModel):
    store_slug: str = Field(..., min_length=1)
    subpath: str = ""
    virtual_prefix: str = ""


class McpServerCreate(BaseModel):
    slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    enabled: bool = True
    tools: list[str] = Field(default_factory=list)
    kind: Literal["simple", "virtual"] = "simple"
    mounts: list[MountInput] = Field(default_factory=list)


class McpServerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    enabled: bool | None = None
    tools: list[str] | None = None
    kind: Literal["simple", "virtual"] | None = None
    mounts: list[MountInput] | None = None


# --- response models --------------------------------------------------------


class MountInfo(BaseModel):
    id: UUID
    store_id: UUID
    store_slug: str
    subpath: str
    virtual_prefix: str
    sort_order: int


class McpServerInfo(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_slug: str
    slug: str
    name: str
    description: str | None
    kind: str
    timeout_seconds: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    tools: list[str]
    mounts: list[MountInfo]


# --- helpers ---------------------------------------------------------------


def _normalize_path_segment(raw: str, *, field: str) -> str:
    """Trim leading/trailing slashes, refuse ``..`` segments.

    Used for both ``subpath`` and ``virtual_prefix``. Empty string is
    canonical for "root."
    """
    p = (raw or "").strip("/")
    if not p:
        return ""
    parts = p.split("/")
    if any(part in ("", "..") for part in parts):
        raise MountInvalid(
            f"{field} must not contain empty or '..' segments (got {raw!r})"
        )
    return "/".join(parts)


def _validate_no_prefix_overlap(prefixes: list[str]) -> None:
    """Refuse two mounts whose virtual_prefixes overlap.

    No two prefixes may be equal, and no prefix may be a path-prefix of
    another (so ``docs`` and ``docs/team-a`` overlap and are rejected).
    The empty string is allowed at most once.
    """
    seen: set[str] = set()
    for p in prefixes:
        if p in seen:
            raise MountConflict(
                f"two mounts share virtual_prefix {p!r}"
            )
        seen.add(p)
    sorted_prefixes = sorted(prefixes, key=len)
    for i, short in enumerate(sorted_prefixes):
        if not short:
            continue  # root mount only overlaps via equality (handled above)
        for j in range(i + 1, len(sorted_prefixes)):
            longer = sorted_prefixes[j]
            # Equality already rejected by the dedup loop above, so this
            # is strictly the path-prefix-overlap case.
            if longer.startswith(short + "/"):
                raise MountConflict(
                    f"virtual_prefix {short!r} is a path-prefix of {longer!r}"
                )


async def _resolve_stores(
    session: AsyncSession,
    tenant: Tenant,
    mounts: list[MountInput],
) -> dict[str, Store]:
    """Map every distinct store_slug in the inputs to a Store row.

    Resolution is tenant-scoped: a slug that exists in a *different*
    tenant is treated as a cross-tenant attempt
    (:class:`MountCrossTenant`); a slug that exists in no tenant is
    :class:`StoreNotFound`. Tenant scoping matters because slugs are
    only unique within a tenant — two tenants can each have a ``docs``
    store, and a global query would non-deterministically pick one.
    """
    needed = {m.store_slug for m in mounts}
    if not needed:
        return {}
    in_tenant = (
        (
            await session.execute(
                select(Store).where(
                    Store.tenant_id == tenant.id,
                    Store.slug.in_(needed),
                )
            )
        )
        .scalars()
        .all()
    )
    by_slug = {s.slug: s for s in in_tenant}
    missing = needed - set(by_slug.keys())
    if missing:
        # Distinguish "exists in another tenant" (cross-tenant) from
        # "doesn't exist anywhere" (not found). Both are 400s but the
        # Problem Details type lets the caller fix the right thing.
        elsewhere = (
            (
                await session.execute(
                    select(Store.slug).where(Store.slug.in_(missing))
                )
            )
            .scalars()
            .all()
        )
        cross = sorted(set(elsewhere))
        if cross:
            raise MountCrossTenant(
                "the following store slug(s) belong to a different tenant: "
                f"{cross}"
            )
        raise StoreNotFound(
            f"store slug(s) not found in tenant {tenant.slug!r}: "
            f"{sorted(missing)}"
        )
    return by_slug


def _validate_tools(tools: list[str]) -> list[str]:
    if not tools:
        return []
    # Dedupe while preserving first-seen order.
    seen: set[str] = set()
    out: list[str] = []
    for t in tools:
        if t in seen:
            continue
        if t not in REGISTERED_TOOL_NAMES:
            raise ToolNameInvalid(
                f"tool {t!r} is not a registered MCP tool name"
            )
        seen.add(t)
        out.append(t)
    return out


def _validate_runtime_compatibility(
    *,
    tools: list[str],
    mounts: list[MountInput],
    stores: dict[str, Store],
) -> None:
    """Refuse multi-store configs that enable git/transaction tools.

    Defense-in-depth — spec 04 also re-checks at runtime, but
    catching it at config-author time gives a clear error before any
    agent connects.
    """
    underlying = {stores[m.store_slug].id for m in mounts}
    if len(underlying) <= 1:
        return
    overlap = set(tools) & _MULTI_STORE_DISALLOWED_TOOLS
    if overlap:
        raise McpServerMultiStoreGitForbidden(
            "config spans multiple stores but enables tools that require "
            f"a single store: {sorted(overlap)}"
        )


def _validate_mounts(
    kind: str, mounts: list[MountInput]
) -> list[MountInput]:
    """Per-server validation: kind matches mount count, mounts have
    normalized paths, no prefix overlap.

    ``simple`` allows zero or one mount — zero means the server is
    inert (the runtime resolver will refuse calls with a clear error)
    and one is the active shape. ``virtual`` requires at least one
    mount with no overlapping prefixes; an empty mount list with
    ``kind='virtual'`` is incoherent (a virtual server with nothing to
    virtualize) and rejected here so it can't reach the runtime.
    """
    if kind == "virtual" and not mounts:
        raise ValidationError(
            "virtual servers must have at least one mount"
        )
    if not mounts:
        return []
    if kind == "simple" and len(mounts) != 1:
        raise ValidationError(
            f"simple servers must have exactly one mount (got {len(mounts)})"
        )
    normalized: list[MountInput] = []
    for m in mounts:
        normalized.append(
            MountInput(
                store_slug=m.store_slug,
                subpath=_normalize_path_segment(m.subpath, field="subpath"),
                virtual_prefix=_normalize_path_segment(
                    m.virtual_prefix, field="virtual_prefix"
                ),
            )
        )
    if kind == "simple" and normalized[0].virtual_prefix:
        raise ValidationError(
            "simple servers must have an empty virtual_prefix"
        )
    if kind == "virtual":
        _validate_no_prefix_overlap(
            [m.virtual_prefix for m in normalized]
        )
    return normalized


def _audit(
    session: AsyncSession,
    *,
    actor: Principal,
    action: str,
    target_id: str,
    tenant_id: UUID,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            actor_kind="user",
            action=action,
            target_kind="mcp_server",
            target_id=target_id,
            tenant_id=tenant_id,
            detail=json.dumps(detail) if detail else None,
        )
    )


def _server_to_info(
    server: McpServer, tenant_slug: str, stores_by_id: dict[UUID, Store]
) -> McpServerInfo:
    return McpServerInfo(
        id=server.id,
        tenant_id=server.tenant_id,
        tenant_slug=tenant_slug,
        slug=server.slug,
        name=server.name,
        description=server.description,
        kind=server.kind,
        timeout_seconds=server.timeout_seconds,
        enabled=server.enabled,
        created_at=server.created_at,
        updated_at=server.updated_at,
        tools=sorted(t.tool_name for t in server.tools),
        mounts=[
            MountInfo(
                id=m.id,
                store_id=m.store_id,
                store_slug=stores_by_id[m.store_id].slug
                if m.store_id in stores_by_id
                else "",
                subpath=m.subpath,
                virtual_prefix=m.virtual_prefix,
                sort_order=m.sort_order,
            )
            for m in server.mounts
        ],
    )


async def _get_tenant_or_404(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound(f"tenant {tenant_id} not found")
    return tenant


async def _load_full_server(
    session: AsyncSession, server_id: UUID
) -> McpServer | None:
    return (
        await session.execute(
            select(McpServer)
            .options(
                selectinload(McpServer.tools),
                selectinload(McpServer.mounts),
            )
            .where(McpServer.id == server_id)
        )
    ).scalar_one_or_none()


async def _stores_by_id_for_server(
    session: AsyncSession, server: McpServer
) -> dict[UUID, Store]:
    store_ids = {m.store_id for m in server.mounts}
    if not store_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(Store).where(Store.id.in_(store_ids))
            )
        )
        .scalars()
        .all()
    )
    return {s.id: s for s in rows}


# --- router ----------------------------------------------------------------


router = APIRouter(prefix="/tenants", tags=["tenant-admin-mcp-servers"])


@router.get(
    "/{tenant_id}/mcp-servers",
    response_model=list[McpServerInfo],
)
async def list_mcp_servers(
    tenant_id: UUID,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> list[McpServerInfo]:
    tenant = await _get_tenant_or_404(session, tenant_id)
    rows = (
        (
            await session.execute(
                select(McpServer)
                .options(
                    selectinload(McpServer.tools),
                    selectinload(McpServer.mounts),
                )
                .where(McpServer.tenant_id == tenant.id)
                .order_by(McpServer.slug)
            )
        )
        .scalars()
        .all()
    )
    result = []
    for s in rows:
        stores_by_id = await _stores_by_id_for_server(session, s)
        result.append(_server_to_info(s, tenant.slug, stores_by_id))
    return result


@router.post(
    "/{tenant_id}/mcp-servers",
    response_model=McpServerInfo,
    status_code=201,
)
async def create_mcp_server(
    tenant_id: UUID,
    body: McpServerCreate,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> McpServerInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)

    existing = (
        await session.execute(
            select(McpServer).where(
                McpServer.tenant_id == tenant.id,
                McpServer.slug == body.slug,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise McpServerAlreadyExists(
            f"mcp-server {tenant.slug}/{body.slug} already exists"
        )

    tools = _validate_tools(body.tools)
    mounts = _validate_mounts(body.kind, body.mounts)
    stores_by_slug = await _resolve_stores(session, tenant, mounts)
    _validate_runtime_compatibility(
        tools=tools, mounts=mounts, stores=stores_by_slug
    )

    server = McpServer(
        tenant_id=tenant.id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        kind=body.kind,
        timeout_seconds=body.timeout_seconds,
        enabled=body.enabled,
    )
    session.add(server)
    await session.flush()

    for name in tools:
        session.add(
            McpServerTool(mcp_server_id=server.id, tool_name=name)
        )

    for midx, m in enumerate(mounts):
        session.add(
            McpServerMount(
                mcp_server_id=server.id,
                store_id=stores_by_slug[m.store_slug].id,
                subpath=m.subpath,
                virtual_prefix=m.virtual_prefix,
                sort_order=midx,
            )
        )

    _audit(
        session,
        actor=actor,
        action="mcp_server.created",
        target_id=str(server.id),
        tenant_id=tenant.id,
        detail={
            "tenant_slug": tenant.slug,
            "slug": server.slug,
            "name": server.name,
        },
    )

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise McpServerAlreadyExists(
            f"mcp-server {tenant.slug}/{body.slug} already exists"
        ) from exc

    await broadcast_catalog_changed()
    fresh = await _load_full_server(session, server.id)
    assert fresh is not None
    stores_by_id = await _stores_by_id_for_server(session, fresh)
    return _server_to_info(fresh, tenant.slug, stores_by_id)


@router.get(
    "/{tenant_id}/mcp-servers/{slug}",
    response_model=McpServerInfo,
)
async def get_mcp_server(
    tenant_id: UUID,
    slug: str,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> McpServerInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)
    server = (
        await session.execute(
            select(McpServer)
            .options(
                selectinload(McpServer.tools),
                selectinload(McpServer.mounts),
            )
            .where(
                McpServer.tenant_id == tenant.id,
                McpServer.slug == slug,
            )
        )
    ).scalar_one_or_none()
    if server is None:
        raise McpServerNotFound(
            f"mcp-server {tenant.slug}/{slug} not found"
        )
    stores_by_id = await _stores_by_id_for_server(session, server)
    return _server_to_info(server, tenant.slug, stores_by_id)


@router.patch(
    "/{tenant_id}/mcp-servers/{slug}",
    response_model=McpServerInfo,
)
async def update_mcp_server(
    tenant_id: UUID,
    slug: str,
    body: McpServerUpdate,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
) -> McpServerInfo:
    tenant = await _get_tenant_or_404(session, tenant_id)
    server = (
        await session.execute(
            select(McpServer)
            .options(
                selectinload(McpServer.tools),
                selectinload(McpServer.mounts),
            )
            .where(
                McpServer.tenant_id == tenant.id,
                McpServer.slug == slug,
            )
        )
    ).scalar_one_or_none()
    if server is None:
        raise McpServerNotFound(
            f"mcp-server {tenant.slug}/{slug} not found"
        )

    changed_fields: list[str] = []
    if body.name is not None and body.name != server.name:
        server.name = body.name
        changed_fields.append("name")
    if body.description is not None and body.description != server.description:
        server.description = body.description
        changed_fields.append("description")
    if (
        body.timeout_seconds is not None
        and body.timeout_seconds != server.timeout_seconds
    ):
        server.timeout_seconds = body.timeout_seconds
        changed_fields.append("timeout_seconds")
    if body.enabled is not None and body.enabled != server.enabled:
        server.enabled = body.enabled
        changed_fields.append("enabled")

    # For the joint validate-multi-store check we need the resolved
    # post-patch set of tools and mounts.
    next_tools: list[str] = (
        _validate_tools(body.tools)
        if body.tools is not None
        else [t.tool_name for t in server.tools]
    )
    # kind and mounts move in lockstep: validating mounts depends on
    # the post-patch kind, so if either is in the body we re-validate
    # both against the merged state.
    next_kind: str = (
        body.kind if body.kind is not None else server.kind
    )
    next_mounts_input: list[MountInput] | None = None
    next_stores_by_slug: dict[str, Store] = {}
    if body.mounts is not None or body.kind is not None:
        if body.mounts is not None:
            source_mounts = body.mounts
        else:
            # Kind-only patch: rehydrate MountInput from the existing
            # rows. We can't fabricate placeholder ``store_slug=""``
            # values here — MountInput enforces ``min_length=1`` at
            # construction time, so the request would 422 before we
            # ever reach _validate_mounts. Resolve the real slugs
            # first, then build the inputs.
            existing_store_ids = [m.store_id for m in server.mounts]
            existing_stores = (
                (
                    await session.execute(
                        select(Store).where(
                            Store.id.in_(existing_store_ids or {None})
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_id = {s.id: s for s in existing_stores}
            source_mounts = [
                MountInput(
                    store_slug=by_id[m.store_id].slug,
                    subpath=m.subpath,
                    virtual_prefix=m.virtual_prefix,
                )
                for m in server.mounts
                if m.store_id in by_id
            ]
        next_mounts_input = _validate_mounts(next_kind, source_mounts)
        next_stores_by_slug = await _resolve_stores(
            session, tenant, next_mounts_input
        )
    else:
        # Neither kind nor mounts changed; build the existing-mounts
        # view for the multi-store check.
        existing_store_ids = [m.store_id for m in server.mounts]
        stores = (
            (
                await session.execute(
                    select(Store).where(
                        Store.id.in_(existing_store_ids or {None})
                    )
                )
            )
            .scalars()
            .all()
        )
        next_stores_by_slug = {s.slug: s for s in stores}
        by_id = {s.id: s for s in stores}
        next_mounts_input = [
            MountInput(
                store_slug=by_id[m.store_id].slug,
                subpath=m.subpath,
                virtual_prefix=m.virtual_prefix,
            )
            for m in server.mounts
            if m.store_id in by_id
        ]

    _validate_runtime_compatibility(
        tools=next_tools,
        mounts=next_mounts_input,
        stores=next_stores_by_slug,
    )

    # Whole-list replace for tools.
    if body.tools is not None:
        await session.execute(
            McpServerTool.__table__.delete().where(
                McpServerTool.mcp_server_id == server.id
            )
        )
        for name in next_tools:
            session.add(
                McpServerTool(mcp_server_id=server.id, tool_name=name)
            )
        changed_fields.append("tools")

    if body.kind is not None and body.kind != server.kind:
        server.kind = body.kind
        changed_fields.append("kind")

    # Whole-list replace for mounts.
    if body.mounts is not None:
        for m in list(server.mounts):
            await session.delete(m)
        await session.flush()
        for midx, m_in in enumerate(next_mounts_input):
            session.add(
                McpServerMount(
                    mcp_server_id=server.id,
                    store_id=next_stores_by_slug[m_in.store_slug].id,
                    subpath=m_in.subpath,
                    virtual_prefix=m_in.virtual_prefix,
                    sort_order=midx,
                )
            )
        changed_fields.append("mounts")

    if changed_fields:
        _audit(
            session,
            actor=actor,
            action="mcp_server.updated",
            target_id=str(server.id),
            tenant_id=tenant.id,
            detail={"changed_fields": sorted(set(changed_fields))},
        )
    server_id = server.id
    await session.commit()
    if changed_fields:
        await broadcast_catalog_changed()
    # Drop the cached `server` (and its now-stale relationship
    # collections) from the identity map so the re-read sees post-commit
    # truth. `expire_all` would also work but would trigger lazy reload
    # in the wrong (sync) context; `expunge_all` keeps re-loads async.
    session.expunge_all()

    fresh = await _load_full_server(session, server_id)
    assert fresh is not None
    stores_by_id = await _stores_by_id_for_server(session, fresh)
    return _server_to_info(fresh, tenant.slug, stores_by_id)


@router.delete(
    "/{tenant_id}/mcp-servers/{slug}",
    status_code=204,
)
async def delete_mcp_server(
    tenant_id: UUID,
    slug: str,
    actor: Principal = Depends(require_tenant_admin),
    session: AsyncSession = Depends(get_session),
    confirm: bool = Query(default=False),
) -> None:
    tenant = await _get_tenant_or_404(session, tenant_id)
    if not confirm:
        raise ConfirmationRequired(
            "mcp-server deletion is destructive (tokens bound to this "
            "config will become unscoped); retry with ?confirm=true"
        )
    server = (
        await session.execute(
            select(McpServer).where(
                McpServer.tenant_id == tenant.id,
                McpServer.slug == slug,
            )
        )
    ).scalar_one_or_none()
    if server is None:
        raise McpServerNotFound(
            f"mcp-server {tenant.slug}/{slug} not found"
        )
    _audit(
        session,
        actor=actor,
        action="mcp_server.deleted",
        target_id=str(server.id),
        tenant_id=tenant.id,
        detail={"tenant_slug": tenant.slug, "slug": server.slug},
    )
    await session.delete(server)
    await session.commit()
    await broadcast_catalog_changed()


__all__ = [
    "router",
    "MountInput",
    "McpServerCreate",
    "McpServerUpdate",
    "McpServerInfo",
    "MountInfo",
]
