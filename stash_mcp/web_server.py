"""Web server with REST API and UI."""

import logging

import uvicorn

from .api import create_api
from .config import Config
from .filesystem import FileSystem
from .ui import create_ui_router

logger = logging.getLogger(__name__)


def run_web_server():
    """Run the web server with REST API and UI."""
    logger.info("Starting Stash-MCP web server...")

    # Ensure content directory exists
    Config.ensure_content_dir()

    # Initialize filesystem
    filesystem = FileSystem(Config.CONTENT_DIR)

    # Create FastAPI app
    app = create_api(filesystem)

    # Add UI router
    ui_router = create_ui_router(filesystem)
    app.include_router(ui_router)

    # Run server
    logger.info(f"Server running at http://{Config.HOST}:{Config.PORT}")
    logger.info(f"API docs at http://{Config.HOST}:{Config.PORT}/docs")
    logger.info(f"UI at http://{Config.HOST}:{Config.PORT}/ui")

    uvicorn.run(
        app,
        host=Config.HOST,
        port=Config.PORT,
        log_level=Config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    run_web_server()
