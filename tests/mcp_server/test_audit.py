"""Tests for MCP tool-call auditing (spec 04:550-555)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.auth.principal import Principal
from stash_mcp.db.models import AuditEvent, User
from stash_mcp.errors import McpServerToolNotAllowed
from stash_mcp.mcp_server import USE_CURRENT_STORE, create_mcp_server
from stash_mcp.routing.context import reset_current_store, set_current_store
from stash_mcp.routing.mcp_server_resolver import (
    reset_current_mcp_server,
    set_current_mcp_server,
)

from .test_runtime_tool_allowlist import _seed_single_store


async def _seed_user(auth_db) -> User:
    """Audit rows have an FK on actor_user_id → users.id, so tests
    that actually persist an audit row need a real user."""
    async with auth_db() as session:
        user = User(
            oidc_sub="audit-test-sub",
            email="audit@example.test",
            display_name="Audit Tester",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _principal_for(user: User, tenant_id, scopes: str = "read,write") -> Principal:
    return Principal(
        user_id=user.id,
        oidc_sub=user.oidc_sub,
        email=user.email,
        display_name=user.display_name,
        auth_method="api_token",
        tenant_roles={tenant_id: "member"},
        claims={"scopes": scopes},
    )


async def _audit_rows(auth_db) -> list[AuditEvent]:
    async with auth_db() as session:
        return list(
            (await session.execute(select(AuditEvent))).scalars().all()
        )


async def test_successful_tool_call_writes_audit_row(
    auth_db, content_dir: Path, mock_context
):
    user = await _seed_user(auth_db)
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    read = await mcp.get_tool("read_content")

    p_tok = set_current_principal(_principal_for(user, tenant.id))
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(composite)
    try:
        await read.run({"path": "hello.md"})
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)

    rows = await _audit_rows(auth_db)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "mcp.tool.read_content"
    assert row.actor_kind == "api_token"
    assert row.target_kind == "mcp_server"
    assert row.target_id == str(config.id)
    assert row.tenant_id == tenant.id
    detail = json.loads(row.detail)
    assert detail["outcome"] == "success"
    assert isinstance(detail["duration_ms"], (int, float))
    assert detail["scopes"] == "read,write"


async def test_failed_tool_call_writes_audit_row_with_error_type(
    auth_db, content_dir: Path, mock_context
):
    """Tools that raise — including the call-time allowlist check —
    still get audited, with outcome=error and the exception class name."""
    user = await _seed_user(auth_db)
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content"]  # create_content NOT allowed
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    create = await mcp.get_tool("create_content")

    p_tok = set_current_principal(_principal_for(user, tenant.id))
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(composite)
    try:
        with pytest.raises(McpServerToolNotAllowed):
            await create.run({"path": "x.md", "content": "x"})
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)

    rows = await _audit_rows(auth_db)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "mcp.tool.create_content"
    detail = json.loads(row.detail)
    assert detail["outcome"] == "error"
    assert detail["error_type"] == "McpServerToolNotAllowed"


async def test_unscoped_call_uses_store_target(
    auth_db, content_dir: Path, mock_context
):
    """Cookie-authenticated requests (no MCP-server config in scope)
    get target_kind=store + the loaded store's id."""
    user = await _seed_user(auth_db)
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    read = await mcp.get_tool("read_content")

    p_tok = set_current_principal(_principal_for(user, tenant.id))
    # No set_current_mcp_server — unscoped.
    s_tok = set_current_store(composite)
    try:
        await read.run({"path": "hello.md"})
    finally:
        reset_current_store(s_tok)
        reset_current_principal(p_tok)

    rows = await _audit_rows(auth_db)
    assert len(rows) == 1
    assert rows[0].target_kind == "store"
    # The composite seeded by _seed_single_store uses config.id as its
    # store_id — both happen to point at the same thing here.
    assert rows[0].target_id == str(composite.store_id)


async def test_multiple_calls_produce_multiple_rows(
    auth_db, content_dir: Path, mock_context
):
    user = await _seed_user(auth_db)
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content", "list_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)
    read = await mcp.get_tool("read_content")
    list_tool = await mcp.get_tool("list_content")

    p_tok = set_current_principal(_principal_for(user, tenant.id))
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(composite)
    try:
        await read.run({"path": "hello.md"})
        await list_tool.run({})
        await read.run({"path": "hello.md"})
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)

    rows = await _audit_rows(auth_db)
    actions = sorted(r.action for r in rows)
    assert actions == [
        "mcp.tool.list_content",
        "mcp.tool.read_content",
        "mcp.tool.read_content",
    ]
