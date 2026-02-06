"""Configuration for Stash-MCP server."""

import os
from pathlib import Path


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

    # MCP settings
    SERVER_NAME: str = "stash-mcp"
    SERVER_VERSION: str = "0.1.0"

    @classmethod
    def ensure_content_dir(cls) -> None:
        """Ensure content directory exists."""
        cls.CONTENT_DIR.mkdir(parents=True, exist_ok=True)
