"""mcp server configs (data model)

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-17 00:00:00

Adds four tables for the MCP-server-config feature (spec 02):
``mcp_servers``, ``mcp_server_tools``, ``mcp_server_content_roots``,
``mcp_server_mounts``. All tenant-scoped via ``mcp_servers.tenant_id``.

The ``api_tokens.mcp_server_id`` column lands in 0003.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "timeout_seconds",
            sa.SmallInteger(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "slug", name="uq_mcp_servers_tenant_slug"
        ),
    )

    op.create_table(
        "mcp_server_tools",
        sa.Column(
            "mcp_server_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(length=63), nullable=False),
        sa.PrimaryKeyConstraint(
            "mcp_server_id", "tool_name", name="pk_mcp_server_tools"
        ),
        sa.CheckConstraint(
            "tool_name GLOB '[a-z_]*'",
            name="ck_mcp_server_tools_name",
        ),
    )

    op.create_table(
        "mcp_server_content_roots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "mcp_server_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "sort_order",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "kind IN ('simple','virtual')", name="ck_content_roots_kind"
        ),
    )

    op.create_table(
        "mcp_server_mounts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "content_root_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey(
                "mcp_server_content_roots.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "subpath", sa.Text(), nullable=False, server_default=""
        ),
        sa.Column(
            "virtual_prefix",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "sort_order",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_table("mcp_server_mounts")
    op.drop_table("mcp_server_content_roots")
    op.drop_table("mcp_server_tools")
    op.drop_table("mcp_servers")
