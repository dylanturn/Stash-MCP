"""Implementation of the ``stash-mcp-cli`` subcommands.

Each ``cmd_*`` function takes the parsed ``argparse.Namespace`` and the
:class:`async_sessionmaker` to use. Output is plain text on stdout so the
commands compose with shell pipelines.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from ..db.models import Membership, Store, Tenant, User
from ..stores.layout import store_root
from ..stores.registry import (
    StoreAlreadyProvisionedError,
    get_store_registry,
)


class CliError(RuntimeError):
    """Raised on user-visible CLI failures. The main wrapper prints the
    message and exits non-zero."""


async def cmd_tenant_create(ns: Any, sm: async_sessionmaker) -> str:
    async with sm() as session:
        existing = (
            await session.execute(
                select(Tenant).where(Tenant.slug == ns.slug)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise CliError(f"tenant {ns.slug!r} already exists")
        tenant = Tenant(slug=ns.slug, display_name=ns.name)
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
    return f"created tenant {tenant.slug} ({tenant.id})"


async def cmd_tenant_list(_ns: Any, sm: async_sessionmaker) -> str:
    async with sm() as session:
        rows = (
            (await session.execute(select(Tenant).order_by(Tenant.slug)))
            .scalars()
            .all()
        )
    if not rows:
        return "(no tenants)"
    lines = [f"{t.slug:30} {t.id} {t.display_name}" for t in rows]
    return "\n".join(lines)


async def cmd_store_create(ns: Any, sm: async_sessionmaker) -> str:
    async with sm() as session:
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.slug == ns.tenant)
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise CliError(f"tenant {ns.tenant!r} not found")
        existing = (
            await session.execute(
                select(Store).where(
                    Store.tenant_id == tenant.id, Store.slug == ns.slug
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise CliError(
                f"store {tenant.slug}/{ns.slug} already exists"
            )
        store = Store(
            tenant_id=tenant.id,
            slug=ns.slug,
            display_name=ns.display_name or ns.slug.title(),
            git_remote_url=ns.remote,
            git_branch=ns.branch,
        )
        session.add(store)
        await session.flush()
        tenant_id = tenant.id
        tenant_slug = tenant.slug
        store_id = store.id
        store_slug = store.slug
        await session.commit()

    registry = get_store_registry()
    try:
        await registry.provision(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            store_slug=store_slug,
            git_remote_url=ns.remote,
            git_branch=ns.branch,
        )
    except StoreAlreadyProvisionedError as exc:
        raise CliError(
            f"store row created but on-disk repo at "
            f"{store_root(str(tenant_id), store_slug)} already exists: {exc}"
        ) from exc
    return (
        f"created store {tenant_slug}/{store_slug} ({store_id}) at "
        f"{store_root(str(tenant_id), store_slug)}"
    )


async def cmd_store_list(ns: Any, sm: async_sessionmaker) -> str:
    async with sm() as session:
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.slug == ns.tenant)
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise CliError(f"tenant {ns.tenant!r} not found")
        rows = (
            (
                await session.execute(
                    select(Store)
                    .where(Store.tenant_id == tenant.id)
                    .order_by(Store.slug)
                )
            )
            .scalars()
            .all()
        )
    if not rows:
        return "(no stores)"
    lines = [
        f"{s.slug:30} {s.id} branch={s.git_branch} remote={s.git_remote_url or '-'}"
        for s in rows
    ]
    return "\n".join(lines)


async def cmd_user_list(_ns: Any, sm: async_sessionmaker) -> str:
    async with sm() as session:
        rows = (
            (await session.execute(select(User).order_by(User.email)))
            .scalars()
            .all()
        )
    if not rows:
        return "(no users)"
    lines = [
        f"{u.email:40} {u.id} sub={u.oidc_sub} name={u.display_name!r}"
        for u in rows
    ]
    return "\n".join(lines)


async def cmd_membership_grant(ns: Any, sm: async_sessionmaker) -> str:
    async with sm() as session:
        user = (
            await session.execute(
                select(User)
                .options(selectinload(User.memberships))
                .where(User.email == ns.user_email)
            )
        ).scalar_one_or_none()
        if user is None:
            raise CliError(f"user {ns.user_email!r} not found")
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.slug == ns.tenant)
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise CliError(f"tenant {ns.tenant!r} not found")

        existing = (
            await session.execute(
                select(Membership).where(
                    Membership.user_id == user.id,
                    Membership.tenant_id == tenant.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise CliError(
                f"user {user.email} already has membership on {tenant.slug} "
                f"(source={existing.source!r}, role={existing.role!r})"
            )
        m = Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role=ns.role,
            source="manual",
        )
        session.add(m)
        await session.commit()
        await session.refresh(m)
    return (
        f"granted role={ns.role} to {ns.user_email} on tenant {ns.tenant} "
        f"(membership {m.id})"
    )


async def cmd_membership_revoke(ns: Any, sm: async_sessionmaker) -> str:
    membership_id = UUID(ns.membership_id)
    async with sm() as session:
        m = await session.get(Membership, membership_id)
        if m is None:
            raise CliError(f"membership {membership_id} not found")
        if m.source != "manual":
            raise CliError(
                f"membership {membership_id} has source={m.source!r}; "
                "only manual memberships are revocable via the CLI"
            )
        await session.delete(m)
        await session.commit()
    return f"revoked membership {membership_id}"


COMMANDS: dict[tuple[str, str], Any] = {
    ("tenant", "create"): cmd_tenant_create,
    ("tenant", "list"): cmd_tenant_list,
    ("store", "create"): cmd_store_create,
    ("store", "list"): cmd_store_list,
    ("user", "list"): cmd_user_list,
    ("membership", "grant"): cmd_membership_grant,
    ("membership", "revoke"): cmd_membership_revoke,
}


def run_command(
    cmd: tuple[str, str], ns: Any, sm: async_sessionmaker
) -> int:
    """Resolve and run a CLI subcommand. Returns the process exit code."""
    handler = COMMANDS.get(cmd)
    if handler is None:
        print(f"unknown command: {' '.join(cmd)}", file=sys.stderr)
        return 2
    try:
        output = asyncio.run(handler(ns, sm))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if output:
        print(output)
    return 0


__all__ = ["COMMANDS", "CliError", "run_command"]
