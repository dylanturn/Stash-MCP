"""Configuration for Stash-MCP server."""

import os
from pathlib import Path


def _parse_content_paths(raw: str | None) -> list[str] | None:
    """Parse STASH_CONTENT_PATHS env var into a list of glob patterns.

    Returns None if raw is None, empty, or yields no patterns.
    Normalizes trailing '/' to '/**'.
    """
    if not raw:
        return None
    patterns = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        if p.endswith("/"):
            p += "**"
        patterns.append(p)
    return patterns if patterns else None


class Config:
    """Server configuration."""

    # Content directory - where files are stored
    # STASH_CONTENT_ROOT is the canonical env var; STASH_CONTENT_DIR is kept for backward compat
    CONTENT_DIR: Path = Path(
        os.getenv("STASH_CONTENT_ROOT", os.getenv("STASH_CONTENT_DIR", "/data/content"))
    )

    # Server settings
    HOST: str = os.getenv("STASH_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("STASH_PORT", "8000"))
    LOG_LEVEL: str = os.getenv("STASH_LOG_LEVEL", "info")

    # Content path patterns - glob-based filtering for file discovery
    CONTENT_PATHS: list[str] | None = _parse_content_paths(
        os.getenv("STASH_CONTENT_PATHS")
    )

    # MCP settings
    SERVER_NAME: str = os.getenv("STASH_SERVER_NAME", "stash-mcp")
    READ_ONLY: bool = os.getenv("STASH_READ_ONLY", "false").lower() == "true"
    SERVER_VERSION: str = "0.1.0"

    # Search settings
    SEARCH_ENABLED: bool = os.getenv("STASH_SEARCH_ENABLED", "false").lower() == "true"
    SEARCH_INDEX_DIR: Path = Path(
        os.getenv("STASH_SEARCH_INDEX_DIR", "/data/.stash-index")
    )
    SEARCH_EMBEDDER_MODEL: str = os.getenv(
        "STASH_SEARCH_EMBEDDER_MODEL", "sentence-transformers:all-MiniLM-L6-v2"
    )
    CONTEXTUAL_RETRIEVAL: bool = (
        os.getenv("STASH_CONTEXTUAL_RETRIEVAL", "false").lower() == "true"
    )
    CONTEXTUAL_MODEL: str = os.getenv(
        "STASH_CONTEXTUAL_MODEL", "claude-haiku-4-5-20251001"
    )
    SEARCH_CHUNK_SIZE: int = int(os.getenv("STASH_SEARCH_CHUNK_SIZE", "1000"))
    SEARCH_CHUNK_OVERLAP: int = int(os.getenv("STASH_SEARCH_CHUNK_OVERLAP", "100"))

    # Model cache directory (for HuggingFace/sentence-transformers weights)
    MODEL_CACHE_DIR: Path = Path(
        os.getenv("STASH_MODEL_CACHE_DIR", "/data/models")
    )

    # Git clone-on-startup
    GIT_CLONE_URL: str | None = os.getenv("STASH_GIT_CLONE_URL")
    GIT_CLONE_BRANCH: str = os.getenv("STASH_GIT_CLONE_BRANCH", "main")
    GIT_CLONE_TOKEN: str | None = os.getenv(
        "STASH_GIT_CLONE_TOKEN", os.getenv("STASH_GIT_SYNC_TOKEN")
    )

    # Git tracking
    GIT_TRACKING: bool = os.getenv("STASH_GIT_TRACKING", "false").lower() == "true"

    # Git sync (requires GIT_TRACKING=true)
    GIT_SYNC_ENABLED: bool = os.getenv("STASH_GIT_SYNC_ENABLED", "false").lower() == "true"
    GIT_SYNC_URL: str | None = os.getenv("STASH_GIT_SYNC_URL")
    GIT_SYNC_REMOTE: str = os.getenv("STASH_GIT_SYNC_REMOTE", "origin")
    GIT_SYNC_BRANCH: str = os.getenv("STASH_GIT_SYNC_BRANCH", "main")
    GIT_SYNC_INTERVAL: int = int(os.getenv("STASH_GIT_SYNC_INTERVAL", "60"))
    GIT_SYNC_RECURSIVE: bool = os.getenv("STASH_GIT_SYNC_RECURSIVE", "false").lower() == "true"
    GIT_SYNC_TOKEN: str | None = os.getenv("STASH_GIT_SYNC_TOKEN")
    GIT_AUTHOR_DEFAULT: str = os.getenv("STASH_GIT_AUTHOR_DEFAULT", "stash-mcp <stash@local>")

    # Git overview (UI comparison target)
    GIT_OVERVIEW_REMOTE: str = os.getenv("STASH_GIT_OVERVIEW_REMOTE", "")
    GIT_OVERVIEW_BRANCH: str = os.getenv("STASH_GIT_OVERVIEW_BRANCH", "")

    # Transaction settings (only relevant when GIT_TRACKING=true and READ_ONLY=false)
    TRANSACTION_TIMEOUT: int = int(os.getenv("STASH_TRANSACTION_TIMEOUT", "300"))
    TRANSACTION_LOCK_WAIT: int = int(os.getenv("STASH_TRANSACTION_LOCK_WAIT", "120"))

    # Metrics settings
    METRICS_ENABLED: bool = os.getenv("STASH_METRICS_ENABLED", "true").lower() == "true"
    METRICS_PATH: Path = Path(
        os.getenv(
            "STASH_METRICS_PATH",
            str(
                Path(
                    os.getenv("STASH_CONTENT_ROOT", os.getenv("STASH_CONTENT_DIR", "/data/content"))
                ).parent
                / "metrics.csv"
            ),
        )
    )
    METRICS_RETENTION_DAYS: int = int(os.getenv("STASH_METRICS_RETENTION_DAYS", "90"))

    # Auth / persistence — defaults assume same `/data` layout as content + metrics.
    # Connection string accepts sqlite+aiosqlite:// or postgresql+asyncpg://.
    DATABASE_URL: str = os.getenv(
        "STASH_DATABASE_URL",
        "sqlite+aiosqlite:////data/stash-auth.db",
    )

    # HMAC keys for API tokens. Comma-separated list — the FIRST entry is the
    # active signer; the rest are accepted on verify so an operator can rotate
    # without invalidating live tokens. Each api_tokens row records which key
    # index hashed it (key_version column) so verification can route to the
    # right key directly instead of trying all of them.
    AUTH_TOKEN_HMAC_KEYS: list[str] = [
        k.strip()
        for k in os.getenv("STASH_AUTH_TOKEN_HMAC_KEYS", "").split(",")
        if k.strip()
    ]

    # Auth toggle. When False, the middleware does nothing and existing
    # behavior is preserved. When True, the middleware enforces auth on every
    # request and the rest of the auth env (OIDC + HMAC + session) must be set.
    AUTH_ENABLED: bool = os.getenv("STASH_AUTH_ENABLED", "false").lower() == "true"

    # Slug used for the implicit single store when AUTH_ENABLED=False. The
    # legacy single-CONTENT_DIR layout is exposed under this slug so that
    # URLs and admin tooling can refer to it uniformly once auth is flipped on.
    DEFAULT_STORE_SLUG: str = os.getenv("STASH_DEFAULT_STORE_SLUG", "default")

    # OIDC config. Discovery URL is the only required entry — everything else
    # (authorize/token/jwks/userinfo URLs) is read from the well-known doc.
    OIDC_DISCOVERY_URL: str | None = os.getenv("STASH_OIDC_DISCOVERY_URL")
    OIDC_CLIENT_ID: str | None = os.getenv("STASH_OIDC_CLIENT_ID")
    OIDC_CLIENT_SECRET: str | None = os.getenv("STASH_OIDC_CLIENT_SECRET")
    # Optional; defaults to OIDC_CLIENT_ID at validation time.
    OIDC_AUDIENCE: str | None = os.getenv("STASH_OIDC_AUDIENCE")
    OIDC_SCOPES: str = os.getenv("STASH_OIDC_SCOPES", "openid profile email groups")

    # Group claim → role mapping (locked in design doc).
    OIDC_GROUPS_CLAIM: str = os.getenv("STASH_OIDC_GROUPS_CLAIM", "groups")
    OIDC_ADMIN_GROUP: str | None = os.getenv("STASH_OIDC_ADMIN_GROUP")

    # Session cookies (browser UI). The secret signs cookies; rotating it
    # invalidates every active session. Cookie is httpOnly, Secure,
    # SameSite=Lax.
    SESSION_SECRET: str | None = os.getenv("STASH_SESSION_SECRET")
    SESSION_COOKIE_NAME: str = os.getenv("STASH_SESSION_COOKIE_NAME", "stash_session")
    SESSION_MAX_AGE_SECONDS: int = int(os.getenv("STASH_SESSION_MAX_AGE", "43200"))

    @classmethod
    def validate_auth_config(cls) -> None:
        """Fail fast when AUTH_ENABLED=true but required vars are missing.

        Called from ``main.create_app`` after env is loaded. Raises
        ``SystemExit(1)`` with a clear message so the server doesn't come up
        in a half-configured state.
        """
        if not cls.AUTH_ENABLED:
            return

        missing: list[str] = []
        if not cls.DATABASE_URL:
            missing.append("STASH_DATABASE_URL")
        if not cls.AUTH_TOKEN_HMAC_KEYS:
            missing.append("STASH_AUTH_TOKEN_HMAC_KEYS")
        if not cls.OIDC_DISCOVERY_URL:
            missing.append("STASH_OIDC_DISCOVERY_URL")
        if not cls.OIDC_CLIENT_ID:
            missing.append("STASH_OIDC_CLIENT_ID")
        if not cls.OIDC_CLIENT_SECRET:
            missing.append("STASH_OIDC_CLIENT_SECRET")
        if not cls.SESSION_SECRET:
            missing.append("STASH_SESSION_SECRET")
        if not cls.OIDC_ADMIN_GROUP:
            missing.append("STASH_OIDC_ADMIN_GROUP")

        if missing:
            msg = (
                "STASH_AUTH_ENABLED=true but required env vars are unset: "
                + ", ".join(missing)
            )
            raise SystemExit(msg)

    @classmethod
    def get_effective_metrics_enabled(cls) -> bool:
        """Return whether metrics collection is effectively enabled.

        In read-only (stateless) mode the default flips to disabled to avoid
        file corruption when multiple pods write to the same CSV concurrently.
        Users can still explicitly opt in by setting STASH_METRICS_ENABLED=true.
        """
        if cls.READ_ONLY:
            return os.getenv("STASH_METRICS_ENABLED", "false").lower() == "true"
        return cls.METRICS_ENABLED

    @classmethod
    def ensure_content_dir(cls) -> None:
        """Ensure content directory exists."""
        cls.CONTENT_DIR.mkdir(parents=True, exist_ok=True)
