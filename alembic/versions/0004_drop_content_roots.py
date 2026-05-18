"""drop content_roots; hoist kind/mounts onto mcp_servers

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18 00:00:00

Collapses the two-level (server → content_roots → mounts) shape to a
flat (server → mounts) one. ``kind`` moves up onto ``mcp_servers``;
``mcp_server_mounts.content_root_id`` is repointed at
``mcp_server_id``; the intermediate ``mcp_server_content_roots`` table
is dropped.

If a server had more than one content root, the migration keeps only
the first by ``sort_order`` and discards the rest (with their mounts).
This was a single-tenant developer feature — there's no production
data to preserve, and the multi-root case was always degenerate (the
UI never surfaced more than one in practice).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add the new columns on mcp_servers and mcp_server_mounts.
    #    SQLite can't add a NOT NULL column without a default, so we
    #    give kind a server_default of 'simple'.
    with op.batch_alter_table("mcp_servers") as batch:
        batch.add_column(
            sa.Column(
                "kind",
                sa.String(length=16),
                nullable=False,
                server_default="simple",
            )
        )
        batch.create_check_constraint(
            "ck_mcp_servers_kind", "kind IN ('simple','virtual')"
        )

    with op.batch_alter_table("mcp_server_mounts") as batch:
        batch.add_column(
            sa.Column(
                "mcp_server_id",
                sa.Uuid(as_uuid=True),
                nullable=True,
            )
        )

    # 2. Copy kind from the first content root onto its server.
    bind.execute(
        sa.text(
            """
            UPDATE mcp_servers
               SET kind = (
                   SELECT kind FROM mcp_server_content_roots
                    WHERE mcp_server_content_roots.mcp_server_id = mcp_servers.id
                    ORDER BY sort_order
                    LIMIT 1
               )
             WHERE id IN (
                 SELECT mcp_server_id FROM mcp_server_content_roots
             )
            """
        )
    )

    # 3. Repoint each mount at its server, then drop mounts that
    #    belonged to non-first roots (if any).
    bind.execute(
        sa.text(
            """
            UPDATE mcp_server_mounts
               SET mcp_server_id = (
                   SELECT mcp_server_id FROM mcp_server_content_roots
                    WHERE mcp_server_content_roots.id
                          = mcp_server_mounts.content_root_id
               )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM mcp_server_mounts
             WHERE content_root_id NOT IN (
                 SELECT id FROM mcp_server_content_roots cr1
                  WHERE cr1.sort_order = (
                      SELECT MIN(sort_order)
                        FROM mcp_server_content_roots cr2
                       WHERE cr2.mcp_server_id = cr1.mcp_server_id
                  )
             )
            """
        )
    )

    # 4. Replace the nullable mcp_server_id with a NOT NULL FK and drop
    #    content_root_id. batch_alter_table handles SQLite's lack of
    #    ALTER COLUMN by recreating the table.
    with op.batch_alter_table("mcp_server_mounts") as batch:
        batch.alter_column(
            "mcp_server_id",
            existing_type=sa.Uuid(as_uuid=True),
            nullable=False,
        )
        batch.create_foreign_key(
            "fk_mcp_server_mounts_server",
            "mcp_servers",
            ["mcp_server_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_column("content_root_id")

    # 5. Drop the now-empty content roots table.
    op.drop_table("mcp_server_content_roots")


def downgrade() -> None:
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

    # Recreate one content root per server, carrying its kind.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO mcp_server_content_roots
                (id, mcp_server_id, name, description, kind, sort_order)
            SELECT
                lower(hex(randomblob(16))), id, slug, description, kind, 0
              FROM mcp_servers
            """
        )
    )

    with op.batch_alter_table("mcp_server_mounts") as batch:
        batch.add_column(
            sa.Column(
                "content_root_id",
                sa.Uuid(as_uuid=True),
                nullable=True,
            )
        )

    bind.execute(
        sa.text(
            """
            UPDATE mcp_server_mounts
               SET content_root_id = (
                   SELECT id FROM mcp_server_content_roots
                    WHERE mcp_server_content_roots.mcp_server_id
                          = mcp_server_mounts.mcp_server_id
               )
            """
        )
    )

    with op.batch_alter_table("mcp_server_mounts") as batch:
        batch.alter_column(
            "content_root_id",
            existing_type=sa.Uuid(as_uuid=True),
            nullable=False,
        )
        batch.create_foreign_key(
            "fk_mcp_server_mounts_root",
            "mcp_server_content_roots",
            ["content_root_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.drop_constraint(
            "fk_mcp_server_mounts_server", type_="foreignkey"
        )
        batch.drop_column("mcp_server_id")

    with op.batch_alter_table("mcp_servers") as batch:
        batch.drop_constraint("ck_mcp_servers_kind", type_="check")
        batch.drop_column("kind")
