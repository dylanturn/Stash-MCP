"""api_tokens.mcp_server_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-17 00:00:01

Adds a nullable ``mcp_server_id`` FK on ``api_tokens`` so tokens can be
scoped to a specific MCP-server config (spec 03). NULL = legacy /
unscoped. ON DELETE SET NULL — deleting a config does not cascade-revoke
tokens; they just become unscoped.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_tokens") as batch:
        batch.add_column(
            sa.Column(
                "mcp_server_id",
                sa.Uuid(as_uuid=True),
                nullable=True,
            )
        )
        batch.create_foreign_key(
            "fk_api_tokens_mcp_server_id",
            "mcp_servers",
            ["mcp_server_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_api_tokens_mcp_server_id",
        "api_tokens",
        ["mcp_server_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_tokens_mcp_server_id", table_name="api_tokens")
    with op.batch_alter_table("api_tokens") as batch:
        batch.drop_constraint(
            "fk_api_tokens_mcp_server_id", type_="foreignkey"
        )
        batch.drop_column("mcp_server_id")
