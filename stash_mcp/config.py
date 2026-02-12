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
    SERVER_NAME: str = "stash-mcp"
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

    @classmethod
    def ensure_content_dir(cls) -> None:
        """Ensure content directory exists."""
        cls.CONTENT_DIR.mkdir(parents=True, exist_ok=True)
