"""Tests for ``AuthListingMiddleware`` — the list-time filter that
pairs with the call-time allowlist (spec 04 follow-up).

Covers:
- ``tools/list`` hides tools not on the per-config allowlist
- ``tools/list`` hides git/transaction tools on multi-store composites
- ``tools/list`` is untouched when the request is unscoped
- ``resources/list`` enumerates ``README.md`` files from the active
  composite filesystem (the static enumeration in ``create_mcp_server``
  skips this in auth mode)
"""

from __future__ import annotations

from pathlib import Path

from stash_mcp.auth.context import (
    reset_current_principal,
    set_current_principal,
)
from stash_mcp.mcp_server import USE_CURRENT_STORE, create_mcp_server
from stash_mcp.routing.context import reset_current_store, set_current_store
from stash_mcp.routing.mcp_server_resolver import (
    reset_current_mcp_server,
    set_current_mcp_server,
)

from .test_runtime_tool_allowlist import (
    _principal,
    _seed_multi_store,
    _seed_single_store,
)


async def _list_tool_names(mcp) -> list[str]:
    tools = await mcp._list_tools_middleware()
    return sorted(t.name for t in tools)


async def _list_resource_uris(mcp) -> list[str]:
    resources = await mcp._list_resources_middleware()
    return sorted(str(r.uri) for r in resources)


async def test_list_tools_filters_to_allowlist(
    auth_db, content_dir: Path
):
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content", "list_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)

    p_tok = set_current_principal(_principal(tenant.id))
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(composite)
    try:
        names = await _list_tool_names(mcp)
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)

    assert names == ["list_content", "read_content"]


async def test_list_tools_hides_git_tools_on_multi_store(
    auth_db, content_dir: Path
):
    tenant, config, composite = await _seed_multi_store(
        auth_db,
        content_dir,
        ["read_content", "log_content", "diff_content", "blame_content"],
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)

    p_tok = set_current_principal(_principal(tenant.id))
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(composite)
    try:
        names = await _list_tool_names(mcp)
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)

    # Git tools allowlisted but composite spans 2 stores → filtered out.
    assert "log_content" not in names
    assert "diff_content" not in names
    assert "blame_content" not in names
    # Non-git allowlisted tools survive.
    assert "read_content" in names


async def test_list_tools_unscoped_keeps_full_catalog(
    auth_db, content_dir: Path
):
    """Cookie-authenticated requests (no MCP-server config in scope)
    should see the full tool catalog — same as the call-time check's
    no-op behaviour."""
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content"]
    )
    mcp = create_mcp_server(USE_CURRENT_STORE)

    p_tok = set_current_principal(_principal(tenant.id))
    # Deliberately don't set current_mcp_server — unscoped.
    s_tok = set_current_store(composite)
    try:
        names = await _list_tool_names(mcp)
    finally:
        reset_current_store(s_tok)
        reset_current_principal(p_tok)

    # The full registered catalog is large; just assert that tools
    # which would be filtered out by an allowlist are still present.
    assert "create_content" in names
    assert "log_content" in names


async def test_list_resources_enumerates_readmes(
    auth_db, content_dir: Path
):
    tenant, store, config, composite = await _seed_single_store(
        auth_db, content_dir, ["read_content"]
    )
    # _seed_single_store seeded hello.md; add a README at root and one
    # in a subdirectory.
    on_disk = content_dir / str(tenant.id) / "docs"
    (on_disk / "README.md").write_text("# Top\n")
    (on_disk / "subdir").mkdir()
    (on_disk / "subdir" / "README.md").write_text("# Sub\n")
    (on_disk / "not-a-readme.md").write_text("ignored")

    mcp = create_mcp_server(USE_CURRENT_STORE)

    p_tok = set_current_principal(_principal(tenant.id))
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(composite)
    try:
        uris = await _list_resource_uris(mcp)
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)

    assert "stash://README.md" in uris
    assert "stash://subdir/README.md" in uris
    # Non-README markdown files are not exposed as resources.
    assert "stash://not-a-readme.md" not in uris
    assert "stash://hello.md" not in uris


async def test_list_resources_multi_store_enumerates_under_virtual_prefixes(
    auth_db, content_dir: Path
):
    tenant, config, composite = await _seed_multi_store(
        auth_db, content_dir, ["read_content"]
    )
    (content_dir / str(tenant.id) / "docs" / "README.md").write_text("# eng")
    (content_dir / str(tenant.id) / "ops" / "README.md").write_text("# ops")

    mcp = create_mcp_server(USE_CURRENT_STORE)

    p_tok = set_current_principal(_principal(tenant.id))
    c_tok = set_current_mcp_server(config)
    s_tok = set_current_store(composite)
    try:
        uris = await _list_resource_uris(mcp)
    finally:
        reset_current_store(s_tok)
        reset_current_mcp_server(c_tok)
        reset_current_principal(p_tok)

    assert "stash://engineering/README.md" in uris
    assert "stash://ops/README.md" in uris
