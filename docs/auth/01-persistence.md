# 01 — Persistence layer + auth types

## Goal

Stand up the SQL persistence layer (SQLAlchemy 2.x async + Alembic) and the
auth value objects (`Principal`, `AuthProvider` Protocol, token hashing
helpers). After this lands, the codebase has a working DB connection and a
typed surface for auth — but nothing actually uses it yet. No middleware, no
request routing changes, no behavior change for existing deployments.

This chunk is intentionally small and self-contained so it can land
cleanly on `main` without any feature flag.

## Out of scope

- ASGI middleware (lands in 02).
- OIDC discovery, JWT validation, JWKS caching (lands in 02).
- API token issuance/validation logic (token *hashing* is here; the lookup
  flow lives in 02).
- `STASH_AUTH_ENABLED` flag (lands in 02 with the middleware).
- `CONTENT_DIR` shape invariant (lands in 03 with the store registry).

## Files added

```
stash_mcp/db/__init__.py
stash_mcp/db/engine.py          # async engine factory + DATABASE_URL plumbing
stash_mcp/db/session.py         # async_sessionmaker + FastAPI dependency
stash_mcp/db/models.py          # SQLAlchemy 2.x ORM models (Base, all tables)
stash_mcp/auth/__init__.py
stash_mcp/auth/principal.py     # Principal value object
stash_mcp/auth/provider.py      # AuthProvider Protocol
stash_mcp/auth/tokens.py        # HMAC-SHA256 token hashing + verification
alembic.ini
alembic/env.py
alembic/script.py.mako
alembic/versions/0001_initial_auth_schema.py
tests/auth/__init__.py
tests/auth/test_token_hashing.py
tests/db/__init__.py
tests/db/test_models_roundtrip.py
```

## Files modified

```
stash_mcp/config.py             # add DATABASE_URL, AUTH_TOKEN_HMAC_KEY
pyproject.toml                  # add deps
```

## Design

### Dependencies

Add to `[project.dependencies]` in `pyproject.toml`:

```
"sqlalchemy[asyncio]>=2.0.30",
"alembic>=1.13.0",
"aiosqlite>=0.20.0",
"authlib>=1.3.0",
```

Add to `[project.optional-dependencies.dev]`:

```
"asyncpg>=0.29.0",   # for testing the Postgres dialect; not required at runtime
```

Postgres support is dialect-only — `asyncpg` is not pinned at runtime so
SQLite-only deployments don't pull the C extension. Operators opting into
Postgres install `stash-mcp[postgres]` (add that extras group too).

Add `[project.optional-dependencies.postgres]`:

```
"asyncpg>=0.29.0",
```

### Config additions

In `stash_mcp/config.py`, add two new class attributes:

```python
# Auth / persistence — defaults assume same `/data` layout as content + metrics.
# Connection string accepts sqlite+aiosqlite:// or postgresql+asyncpg://.
DATABASE_URL: str = os.getenv(
    "STASH_DATABASE_URL",
    "sqlite+aiosqlite:////data/stash-auth.db",
)

# HMAC key used to hash API tokens at rest. Required when AUTH is enabled
# (validated in 02). Read it here so it's available to db/auth modules
# regardless of whether middleware has been wired up yet.
AUTH_TOKEN_HMAC_KEY: str | None = os.getenv("STASH_AUTH_TOKEN_HMAC_KEY")
```

No runtime validation in this chunk — 02 will fail-fast if AUTH is on without
the HMAC key set.

### Schema

UUIDs as primary keys (TEXT in SQLite, native UUID in Postgres). Timestamps
are TZ-aware. Slugs follow the convention `[a-z0-9][a-z0-9-]{0,62}`.

```
tenants
  id            UUID PK
  slug          TEXT UNIQUE NOT NULL
  display_name  TEXT NOT NULL
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()

users
  id              UUID PK
  oidc_sub        TEXT UNIQUE NOT NULL          -- JWT 'sub' claim
  email           TEXT NOT NULL
  display_name    TEXT NOT NULL
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
  last_login_at   TIMESTAMPTZ

memberships
  id            UUID PK
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE
  role          TEXT NOT NULL CHECK (role IN ('admin','member'))
  source        TEXT NOT NULL CHECK (source IN ('oidc_group','manual'))
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (user_id, tenant_id)

stores
  id             UUID PK
  tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE
  slug           TEXT NOT NULL
  display_name   TEXT NOT NULL
  git_remote_url TEXT           -- nullable: not all stores have a remote
  git_branch     TEXT NOT NULL DEFAULT 'main'
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
  UNIQUE (tenant_id, slug)

api_tokens
  id            UUID PK
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
  token_hash    TEXT UNIQUE NOT NULL    -- HMAC-SHA256 of the secret part
  name          TEXT NOT NULL           -- human label
  scopes        TEXT NOT NULL           -- comma-joined; v1 just "read,write,admin"
  expires_at    TIMESTAMPTZ
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
  last_used_at  TIMESTAMPTZ
  revoked_at    TIMESTAMPTZ
```

Notes:

- `memberships.source` distinguishes group-claim-derived rows (refreshed on
  every OIDC login) from manually granted rows (used for users who don't
  match any OIDC group but were added via admin API). v1 only writes
  `oidc_group`, but the column is in the schema so 05 can add manual grants
  without a migration.
- `stores.git_remote_url` is nullable because the on-disk repo may be local-
  only. When the registry initializes a store with no remote, it creates a
  bare init (no clone).
- `api_tokens.scopes` is a flat comma-joined string for v1 simplicity. If
  we need richer scopes later we can swap to a JSON column without a data
  migration (SQLite TEXT and Postgres JSONB both round-trip strings fine).

### `stash_mcp/db/engine.py`

```python
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from ..config import Config

_engine: AsyncEngine | None = None

def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            Config.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            future=True,
        )
    return _engine

async def dispose_engine() -> None:
    """Disposed on FastAPI shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
```

### `stash_mcp/db/session.py`

```python
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from .engine import get_engine

_sessionmaker: async_sessionmaker[AsyncSession] | None = None

def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker

async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields an AsyncSession scoped to the request."""
    async with get_sessionmaker()() as session:
        yield session
```

### `stash_mcp/db/models.py`

SQLAlchemy 2.x declarative style with `Mapped`/`mapped_column`. One
`DeclarativeBase` subclass `Base`. Use `sqlalchemy.Uuid(as_uuid=True)` for
UUID columns, `DateTime(timezone=True)` for timestamps. UUIDs are generated
in Python (`uuid.uuid4`) so SQLite gets stable IDs without server-side
defaults.

### `stash_mcp/auth/principal.py`

```python
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

AuthMethod = Literal["oidc", "api_token"]
Role = Literal["admin", "member"]

@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    oidc_sub: str
    email: str
    display_name: str
    auth_method: AuthMethod
    # Tenant -> role mapping, populated from `memberships` at auth time.
    tenant_roles: dict[UUID, Role] = field(default_factory=dict)
    # Raw provider claims for audit/debug; never trusted for authz decisions.
    claims: dict[str, object] = field(default_factory=dict)

    def has_role_on(self, tenant_id: UUID, role: Role) -> bool:
        current = self.tenant_roles.get(tenant_id)
        if current is None:
            return False
        if role == "member":
            return current in ("admin", "member")
        return current == role
```

`has_role_on` is the only authz helper here. Route handlers and the MCP
tool wrapper call this — they never read `tenant_roles` directly.

### `stash_mcp/auth/provider.py`

```python
from typing import Protocol, runtime_checkable
from starlette.requests import Request
from .principal import Principal

@runtime_checkable
class AuthProvider(Protocol):
    """Authenticates a request. Returns None if this provider can't handle it
    (e.g. wrong scheme on the Authorization header) — the middleware will try
    the next provider. Raises AuthError to actively reject (signals 401)."""

    name: str

    async def authenticate(self, request: Request) -> Principal | None: ...


class AuthError(Exception):
    """Raised when a provider claims a request but rejects it.
    Middleware translates this to 401 with a WWW-Authenticate header."""

    def __init__(self, message: str, *, www_authenticate: str | None = None):
        super().__init__(message)
        self.www_authenticate = www_authenticate
```

### `stash_mcp/auth/tokens.py`

```python
import hashlib
import hmac
import secrets

# Stash API tokens are prefixed so we can identify them on sight in logs.
# Format: "stash_pat_" + 32 url-safe chars. The prefix is included in the
# value the user sees and in the HMAC input — there's nothing to gain by
# excluding it.
TOKEN_PREFIX = "stash_pat_"
TOKEN_RANDOM_BYTES = 24  # ~32 chars base64-url

def generate_token() -> str:
    """Generate a new opaque API token. Show this to the user once; never log."""
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)

def hash_token(token: str, *, key: str) -> str:
    """HMAC-SHA256 of the token using the deployment's HMAC key.
    Returns hex digest. The key is never persisted with the hash."""
    return hmac.new(key.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()

def verify_token(token: str, expected_hash: str, *, key: str) -> bool:
    """Constant-time comparison."""
    return hmac.compare_digest(hash_token(token, key=key), expected_hash)

def looks_like_stash_token(value: str) -> bool:
    """Cheap prefix check so the ApiTokenAuthProvider can skip JWT-shaped values."""
    return value.startswith(TOKEN_PREFIX)
```

### Alembic baseline

`alembic.ini` uses `sqlalchemy.url = ` left blank — `env.py` reads
`Config.DATABASE_URL` at runtime. `env.py` uses async migration mode
(`run_async_migrations`). Baseline migration creates all five tables in a
single `upgrade()`.

Add a `stash-mcp-migrate` console script entry to `pyproject.toml`:

```
[project.scripts]
stash-mcp-migrate = "alembic.config:main"
```

Or document `alembic upgrade head` in the spec for 06.

## Test plan

- `tests/auth/test_token_hashing.py`
  - Round-trip: generate → hash → verify true with same key.
  - Wrong key → verify false.
  - Tampered token → verify false.
  - Constant-time comparison doesn't short-circuit (smoke test).
  - `looks_like_stash_token` true/false on shaped/unshaped values.
- `tests/db/test_models_roundtrip.py`
  - Spin up an in-memory SQLite engine (`sqlite+aiosqlite:///:memory:`).
  - Run Alembic upgrade head against it.
  - Insert one of each entity and read it back; verify FK constraints
    reject orphaned memberships.
  - `UNIQUE (tenant_id, slug)` on `stores` rejects duplicates.

No tests for the Principal class — it's a dataclass; `has_role_on` is
exercised in 02's middleware tests.

## Acceptance

- `uv run alembic upgrade head` against a fresh sqlite file produces the
  five tables with all constraints.
- `uv run pytest tests/auth tests/db` passes.
- `ruff check stash_mcp/auth stash_mcp/db` clean.
- Importing `stash_mcp.main` still works (no eager DB connections — engine
  is lazy).
- Existing `tests/` suite still passes (no behavior changes elsewhere).

## Open questions

None. Everything in this chunk is mechanical given the locked decisions in
`README.md`.

## Notes for the Claude Code session

- Do **not** wire up `Depends(get_session)` in any existing route in this
  chunk. The DB is reachable but unused.
- Do **not** add `STASH_AUTH_ENABLED` here. It belongs in 02.
- When generating the Alembic baseline, hand-write it from `models.py`
  rather than autogenerating — autogeneration's diff output is noisy and
  this is the first migration, so we want it readable.
- `Config.AUTH_TOKEN_HMAC_KEY` is `str | None` here on purpose. 02 will
  validate it's set when auth is on.
