"""SQLAlchemy 2.x ORM models for the auth/persistence layer.

All primary keys are UUIDs generated in Python so SQLite gets stable IDs
without relying on a server-side default. Timestamps are TZ-aware and
default to the database's ``now()``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True
    )
    stores: Mapped[list[Store]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", passive_deletes=True
    )
    mcp_servers: Mapped[list[McpServer]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    oidc_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    api_tokens: Mapped[list[ApiToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
        CheckConstraint("role IN ('admin','member')", name="ck_memberships_role"),
        CheckConstraint(
            "source IN ('oidc_group','manual')", name="ck_memberships_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_stores_tenant_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    git_remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_branch: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="main"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="stores")


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Nullable FK to the MCP-server config this token is scoped to.
    # NULL = legacy / unscoped (today's behaviour). Not NULL = scoped to
    # the named config. ON DELETE SET NULL so deleting a config does NOT
    # cascade-revoke tokens — they just become unscoped, which is
    # noticeable but not destructive.
    mcp_server_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="api_tokens")
    mcp_server: Mapped[McpServer | None] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user','system','api_token')",
            name="ck_audit_events_actor_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class McpServer(Base):
    """A named MCP-server configuration scoped to a single tenant.

    Defines a slice of the tenant's content (composed from one or more
    mounts) and an allowlist of MCP tools that callers see. Tokens are
    bound to a config via :attr:`ApiToken.mcp_server_id` (spec 03).

    ``kind='simple'`` means a single mount at the agent's filesystem root
    (the mount has an empty ``virtual_prefix``). ``kind='virtual'`` means
    one or more mounts under distinct non-overlapping prefixes.
    """

    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_mcp_servers_tenant_slug"),
        CheckConstraint(
            "kind IN ('simple','virtual')", name="ck_mcp_servers_kind"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="simple"
    )
    timeout_seconds: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="60"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tenant: Mapped[Tenant] = relationship(back_populates="mcp_servers")
    tools: Mapped[list[McpServerTool]] = relationship(
        back_populates="mcp_server",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    mounts: Mapped[list[McpServerMount]] = relationship(
        back_populates="mcp_server",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="McpServerMount.sort_order",
    )


class McpServerTool(Base):
    """One row per (mcp_server, tool_name) pair — the per-config allowlist."""

    __tablename__ = "mcp_server_tools"
    __table_args__ = (
        PrimaryKeyConstraint("mcp_server_id", "tool_name"),
        CheckConstraint(
            "tool_name GLOB '[a-z_]*'",
            name="ck_mcp_server_tools_name",
        ),
    )

    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(63), nullable=False)

    mcp_server: Mapped[McpServer] = relationship(back_populates="tools")


class McpServerMount(Base):
    """One physical store-subpath mounted at a virtual prefix.

    A ``simple`` server has exactly one mount with empty virtual_prefix;
    a ``virtual`` server has 1+ mounts with distinct non-overlapping
    prefixes.

    ``store_id`` uses RESTRICT so a tenant admin can't delete a store
    that some config still mounts — they see a clear error and can fix
    the config first.
    """

    __tablename__ = "mcp_server_mounts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mcp_servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subpath: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    virtual_prefix: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )

    mcp_server: Mapped[McpServer] = relationship(back_populates="mounts")
    store: Mapped[Store] = relationship()
