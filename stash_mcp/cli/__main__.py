"""Entry point for ``python -m stash_mcp.cli`` / ``stash-mcp-cli``.

Argparse layout:

    stash-mcp-cli [--database-url URL] <noun> <verb> [args...]

Reading ``STASH_DATABASE_URL`` from env is the default; the
``--database-url`` flag overrides it. All commands run synchronously
against the configured DB — they are admin tooling, not part of the
request path.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..config import Config
from .commands import run_command


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stash-mcp-cli",
        description="Admin tooling for Stash-MCP tenant/store provisioning.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "SQLAlchemy async URL. Defaults to $STASH_DATABASE_URL "
            "(or Config.DATABASE_URL when set in env)."
        ),
    )
    sub = parser.add_subparsers(dest="noun", required=True)

    # tenant
    tenant = sub.add_parser("tenant", help="manage tenants").add_subparsers(
        dest="verb", required=True
    )
    t_create = tenant.add_parser("create", help="create a tenant")
    t_create.add_argument("--slug", required=True)
    t_create.add_argument("--name", required=True, help="display name")
    tenant.add_parser("list", help="list tenants")

    # store
    store = sub.add_parser("store", help="manage stores").add_subparsers(
        dest="verb", required=True
    )
    s_create = store.add_parser("create", help="create a store")
    s_create.add_argument("--tenant", required=True, help="tenant slug")
    s_create.add_argument("--slug", required=True)
    s_create.add_argument("--display-name", default=None)
    s_create.add_argument(
        "--remote",
        default=None,
        help="optional git remote URL to clone for initial content",
    )
    s_create.add_argument("--branch", default="main")
    s_list = store.add_parser("list", help="list stores for a tenant")
    s_list.add_argument("--tenant", required=True)

    # user
    user = sub.add_parser("user", help="inspect users").add_subparsers(
        dest="verb", required=True
    )
    user.add_parser("list", help="list users")

    # membership
    mem = sub.add_parser(
        "membership", help="manage manual tenant memberships"
    ).add_subparsers(dest="verb", required=True)
    m_grant = mem.add_parser("grant", help="grant a manual membership")
    m_grant.add_argument("--user-email", required=True)
    m_grant.add_argument("--tenant", required=True, help="tenant slug")
    m_grant.add_argument(
        "--role", required=True, choices=("admin", "member")
    )
    m_revoke = mem.add_parser("revoke", help="revoke a manual membership")
    m_revoke.add_argument("membership_id")

    return parser


def _resolve_database_url(arg: str | None) -> str:
    if arg:
        return arg
    return Config.DATABASE_URL


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)

    url = _resolve_database_url(ns.database_url)
    engine = create_async_engine(url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return run_command((ns.noun, ns.verb), ns, sm)
    finally:
        # ``engine.dispose()`` is async; we're in a sync main, so just let
        # the connection pool drop on exit. CLI commands are one-shot.
        pass


if __name__ == "__main__":
    sys.exit(main())
