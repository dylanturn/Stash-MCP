"""Serve the React SPA at /ui with fallback to legacy HTML UI."""

import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger("stash_mcp")

# Resolve frontend dist directory
# Docker: /app/stash_ui/dist
# Local dev: <repo_root>/stash_ui/dist
FRONTEND_DIR = Path(__file__).parent.parent / "stash_ui" / "dist"


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that serves index.html for unknown paths (SPA fallback)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except Exception:
            # File not found -> serve index.html for client-side routing
            return await super().get_response("index.html", scope)


def mount_frontend(app: FastAPI) -> bool:
    """Mount the React SPA at /ui.

    If the frontend dist directory doesn't exist (local dev without
    a frontend build), returns False so the caller can fall back to
    the legacy HTML UI.

    Returns:
        True if the React SPA was mounted, False otherwise.
    """
    if not FRONTEND_DIR.is_dir():
        logger.warning(
            "Frontend dist not found at %s — /ui will use legacy HTML UI. "
            "Run 'npm run build' in stash_ui/ or build with Docker.",
            FRONTEND_DIR,
        )
        return False

    app.mount(
        "/ui",
        SPAStaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="frontend",
    )
    logger.info("React frontend mounted at /ui from %s", FRONTEND_DIR)
    return True
