"""Round-trip tests for the ``stash-mcp-cli`` subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from stash_mcp.cli.__main__ import _build_parser
from stash_mcp.cli.commands import (
    cmd_membership_grant,
    cmd_membership_revoke,
    cmd_store_create,
    cmd_store_list,
    cmd_tenant_create,
    cmd_tenant_list,
    cmd_user_list,
)
from stash_mcp.db.models import Membership, Tenant, User


def _parse(argv: list[str]):
    parser = _build_parser()
    return parser.parse_args(argv)


async def test_tenant_create_and_list(
    auth_db: async_sessionmaker, content_dir: Path
):
    ns = _parse(["tenant", "create", "--slug", "acme", "--name", "Acme Inc"])
    output = await cmd_tenant_create(ns, auth_db)
    assert "acme" in output

    out = await cmd_tenant_list(_parse(["tenant", "list"]), auth_db)
    assert "acme" in out


async def test_tenant_create_duplicate_raises(
    auth_db, content_dir: Path
):
    from stash_mcp.cli.commands import CliError

    ns = _parse(["tenant", "create", "--slug", "acme", "--name", "A"])
    await cmd_tenant_create(ns, auth_db)
    with pytest.raises(CliError):
        await cmd_tenant_create(ns, auth_db)


async def test_store_create_provisions_repo(
    auth_db, content_dir: Path
):
    await cmd_tenant_create(
        _parse(["tenant", "create", "--slug", "acme", "--name", "A"]), auth_db
    )
    ns = _parse(
        ["store", "create", "--tenant", "acme", "--slug", "docs"]
    )
    output = await cmd_store_create(ns, auth_db)
    assert "docs" in output

    async with auth_db() as session:
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.slug == "acme")
            )
        ).scalar_one()
    on_disk = content_dir / str(tenant.id) / "docs"
    assert on_disk.exists()
    assert (on_disk / ".git").exists()


async def test_store_list(auth_db, content_dir: Path):
    await cmd_tenant_create(
        _parse(["tenant", "create", "--slug", "acme", "--name", "A"]), auth_db
    )
    await cmd_store_create(
        _parse(
            ["store", "create", "--tenant", "acme", "--slug", "docs"]
        ),
        auth_db,
    )
    out = await cmd_store_list(
        _parse(["store", "list", "--tenant", "acme"]), auth_db
    )
    assert "docs" in out


async def test_store_create_missing_tenant(
    auth_db, content_dir: Path
):
    from stash_mcp.cli.commands import CliError

    ns = _parse(
        ["store", "create", "--tenant", "ghost", "--slug", "docs"]
    )
    with pytest.raises(CliError):
        await cmd_store_create(ns, auth_db)


async def test_user_list_returns_empty_when_no_users(
    auth_db, content_dir: Path
):
    out = await cmd_user_list(_parse(["user", "list"]), auth_db)
    assert "(no users)" in out


async def test_membership_grant_and_revoke(
    auth_db, content_dir: Path
):
    await cmd_tenant_create(
        _parse(["tenant", "create", "--slug", "acme", "--name", "A"]), auth_db
    )
    async with auth_db() as session:
        user = User(oidc_sub="alice", email="alice@example.com", display_name="A")
        session.add(user)
        await session.commit()

    ns = _parse(
        [
            "membership",
            "grant",
            "--user-email",
            "alice@example.com",
            "--tenant",
            "acme",
            "--role",
            "member",
        ]
    )
    output = await cmd_membership_grant(ns, auth_db)
    assert "alice@example.com" in output

    async with auth_db() as session:
        row = (
            await session.execute(select(Membership))
        ).scalar_one()
    assert row.role == "member"
    assert row.source == "manual"

    revoke_ns = _parse(["membership", "revoke", str(row.id)])
    out = await cmd_membership_revoke(revoke_ns, auth_db)
    assert "revoked" in out

    async with auth_db() as session:
        remaining = (
            (await session.execute(select(Membership))).scalars().all()
        )
    assert remaining == []


async def test_membership_grant_unknown_user(
    auth_db, content_dir: Path
):
    from stash_mcp.cli.commands import CliError

    await cmd_tenant_create(
        _parse(["tenant", "create", "--slug", "acme", "--name", "A"]), auth_db
    )
    ns = _parse(
        [
            "membership",
            "grant",
            "--user-email",
            "ghost@example.com",
            "--tenant",
            "acme",
            "--role",
            "member",
        ]
    )
    with pytest.raises(CliError):
        await cmd_membership_grant(ns, auth_db)


async def test_membership_revoke_refuses_non_manual(
    auth_db, content_dir: Path
):
    from stash_mcp.cli.commands import CliError

    await cmd_tenant_create(
        _parse(["tenant", "create", "--slug", "acme", "--name", "A"]), auth_db
    )
    async with auth_db() as session:
        user = User(
            oidc_sub="alice", email="alice@example.com", display_name="A"
        )
        session.add(user)
        await session.flush()
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.slug == "acme")
            )
        ).scalar_one()
        m = Membership(
            user_id=user.id,
            tenant_id=tenant.id,
            role="admin",
            source="oidc_group",
        )
        session.add(m)
        await session.commit()
        await session.refresh(m)
        target_id = str(m.id)

    ns = _parse(["membership", "revoke", target_id])
    with pytest.raises(CliError):
        await cmd_membership_revoke(ns, auth_db)
