"""FastAPI app entrypoint for Stash-MCP."""

import logging

import uvicorn

from .api import create_api
from .config import Config
from .events import add_listener
from .filesystem import FileSystem
from .mcp_server import create_mcp_server
from .ui import create_ui_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def create_app():
    """Create and configure the FastAPI application."""
    Config.ensure_content_dir()
    filesystem = FileSystem(Config.CONTENT_DIR, include_patterns=Config.CONTENT_PATHS)

    # Create MCP http app first so we can wire its lifespan into FastAPI
    # FastMCP auto-detects auth from FASTMCP_SERVER_AUTH env var when auth
    # is not explicitly provided (default NotSet sentinel).
    mcp = create_mcp_server(filesystem)
    mcp_http_app = mcp.http_app(path="/")

    app = create_api(filesystem, lifespan=mcp_http_app.lifespan)
    ui_router = create_ui_router(filesystem)
    app.include_router(ui_router)

    # When auth is enabled, OAuth discovery endpoints (e.g.
    # /.well-known/oauth-authorization-server) must be reachable at the
    # domain root, not nested under /mcp.
    if mcp.auth is not None:
        well_known_routes = mcp.auth.get_well_known_routes(mcp_path="/mcp")
        for route in well_known_routes:
            app.routes.insert(0, route)

    # Mount FastMCP server onto FastAPI for streamable HTTP transport
    app.mount("/mcp", mcp_http_app)

    # Wire event bus: REST mutations emit MCP resource notifications
    def on_content_changed(event_type: str, path: str, **kwargs: str) -> None:
        logger.info(f"Content event: {event_type} {path} {kwargs}")

    add_listener(on_content_changed)

    return app


def main():
    """Run the Stash-MCP web server."""
    logger.info("Starting Stash-MCP server...")

    app = create_app()

    logger.info(f"Server running at http://{Config.HOST}:{Config.PORT}")
    logger.info(f"API docs at http://{Config.HOST}:{Config.PORT}/docs")
    logger.info(f"UI at http://{Config.HOST}:{Config.PORT}/ui")
    logger.info(f"MCP (SSE) at http://{Config.HOST}:{Config.PORT}/mcp")

    uvicorn.run(
        app,
        host=Config.HOST,
        port=Config.PORT,
        log_level=Config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
