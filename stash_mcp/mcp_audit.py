"""Audit writer for MCP tool calls (spec 04 follow-up).

Each tool invocation under ``AUTH_ENABLED=true`` writes one
:class:`AuditEvent` row with:

- ``actor_kind``: ``api_token`` for scoped-token / PAT principals,
  ``user`` for session-cookie principals.
- ``action``: ``mcp.tool.<tool_name>``.
- ``target_kind`` / ``target_id``: ``mcp_server`` + config id when a
  scoped token is in flight; ``store`` + store id for unscoped
  cookie requests via ``/mcp/<tenant>/<store>/...``.
- ``tenant_id``: the tenant the call ran under.
- ``detail`` (JSON): outcome (``success``/``error``), duration in
  milliseconds, error class name on failure, and the active scopes.

The writer is best-effort — failures are logged at WARNING level and
swallowed so audit instability never breaks tool calls. Each write
runs in its own session to avoid entangling with whatever
transaction the tool itself opened.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .config import Config
from .db.models import AuditEvent
from .db.session import get_sessionmaker

logger = logging.getLogger(__name__)


async def audit_tool_call(
    tool_name: str,
    duration_ms: float,
    success: bool,
    error_type: str | None = None,
) -> None:
    """Write one audit row describing a tool call.

    Reads ``current_principal()``, ``current_mcp_server()`` and
    ``current_store()`` from contextvars to derive actor and target.
    No-op when ``AUTH_ENABLED=false`` (no DB session is configured)
    or when no principal is in scope (defensive — shouldn't happen
    once the auth middleware has run).
    """
    if not Config.AUTH_ENABLED:
        return

    from .auth.context import current_principal
    from .routing.context import current_store
    from .routing.mcp_server_resolver import current_mcp_server

    principal = current_principal()
    if principal is None:
        return

    config = current_mcp_server()
    store = current_store()

    detail: dict[str, Any] = {
        "outcome": "success" if success else "error",
        "duration_ms": round(duration_ms, 2),
    }
    if error_type:
        detail["error_type"] = error_type
    scopes = principal.claims.get("scopes") if principal.claims else None
    if scopes:
        detail["scopes"] = scopes

    if config is not None:
        target_kind: str | None = "mcp_server"
        target_id: str | None = str(config.id)
        tenant_id = config.tenant_id
    elif store is not None:
        target_kind = "store"
        target_id = str(getattr(store, "store_id", "")) or None
        tenant_id = getattr(store, "tenant_id", None)
    else:
        target_kind = None
        target_id = None
        tenant_id = None

    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            session.add(
                AuditEvent(
                    actor_user_id=principal.user_id,
                    actor_kind=(
                        "api_token"
                        if principal.auth_method == "api_token"
                        else "user"
                    ),
                    action=f"mcp.tool.{tool_name}",
                    target_kind=target_kind,
                    target_id=target_id,
                    tenant_id=tenant_id,
                    detail=json.dumps(detail),
                )
            )
            await session.commit()
    except Exception as exc:
        # Audit failures must not break tool calls. Log and move on.
        logger.warning(
            "Failed to write audit row for tool %s: %s",
            tool_name,
            exc,
            exc_info=True,
        )


__all__ = ["audit_tool_call"]
