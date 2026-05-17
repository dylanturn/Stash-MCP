"""Tests for ``broadcast_catalog_changed`` — the admin-side fanout
that pushes ``tools/list_changed`` + ``resources/list_changed`` to
connected MCP sessions when a config is edited.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from stash_mcp.mcp_listing import (
    _active_sessions,
    broadcast_catalog_changed,
)


class _FakeSession:
    """Stand-in for ``mcp.server.session.ServerSession`` — weakly
    referenceable, with the two notification methods the broadcast
    calls."""

    def __init__(self) -> None:
        self.send_tool_list_changed = AsyncMock()
        self.send_resource_list_changed = AsyncMock()


@pytest.fixture(autouse=True)
def _empty_session_registry():
    """Ensure each test starts with no registered sessions."""
    _active_sessions.clear()
    yield
    _active_sessions.clear()


async def test_broadcast_with_no_sessions_is_a_noop():
    # No exceptions, no DB hits — just returns.
    await broadcast_catalog_changed()


async def test_broadcast_notifies_every_session():
    s1 = _FakeSession()
    s2 = _FakeSession()
    _active_sessions.add(s1)
    _active_sessions.add(s2)

    await broadcast_catalog_changed()

    s1.send_tool_list_changed.assert_awaited_once()
    s1.send_resource_list_changed.assert_awaited_once()
    s2.send_tool_list_changed.assert_awaited_once()
    s2.send_resource_list_changed.assert_awaited_once()


async def test_broadcast_swallows_per_session_errors():
    """One failing session must not block the others."""
    bad = _FakeSession()
    bad.send_tool_list_changed.side_effect = RuntimeError("closed transport")
    good = _FakeSession()
    _active_sessions.add(bad)
    _active_sessions.add(good)

    await broadcast_catalog_changed()  # must not raise

    good.send_tool_list_changed.assert_awaited_once()


async def test_dead_sessions_are_gc_collected():
    """The registry is a WeakSet — once a session has no other
    references, it should drop out automatically."""
    sess = _FakeSession()
    _active_sessions.add(sess)
    assert len(_active_sessions) == 1

    del sess
    import gc

    gc.collect()
    assert len(_active_sessions) == 0
