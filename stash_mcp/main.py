"""FastAPI app entrypoint for Stash-MCP."""

import asyncio
import logging
import os

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


def _create_search_engine(filesystem: FileSystem):
    """Create a SearchEngine if search is enabled, or return None."""
    if not Config.SEARCH_ENABLED:
        return None

    try:
        from .search import SearchEngine

        engine = SearchEngine(
            content_dir=Config.CONTENT_DIR,
            index_dir=Config.SEARCH_INDEX_DIR,
            embedder_model=Config.SEARCH_EMBEDDER_MODEL,
            contextual_retrieval=Config.CONTEXTUAL_RETRIEVAL,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            filesystem=filesystem,
        )
        logger.info(
            f"Search engine initialised (model={Config.SEARCH_EMBEDDER_MODEL}, "
            f"contextual={Config.CONTEXTUAL_RETRIEVAL})"
        )
        return engine
    except Exception as e:
        logger.error(f"Failed to create search engine: {e}")
        return None


def _log_task_exception(task: asyncio.Task) -> None:
    """Log unhandled exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"Background task failed: {exc}", exc_info=exc)


def create_app():
    """Create and configure the FastAPI application."""
    Config.ensure_content_dir()
    filesystem = FileSystem(Config.CONTENT_DIR, include_patterns=Config.CONTENT_PATHS)

    # Optionally create search engine
    search_engine = _create_search_engine(filesystem)

    # Create MCP http app first so we can wire its lifespan into FastAPI
    mcp = create_mcp_server(filesystem, search_engine=search_engine)
    mcp_http_app = mcp.http_app(path="/")

    app = create_api(filesystem, lifespan=mcp_http_app.lifespan, search_engine=search_engine)
    ui_router = create_ui_router(filesystem)
    app.include_router(ui_router)

    # Mount FastMCP server onto FastAPI for streamable HTTP transport
    app.mount("/mcp", mcp_http_app)

    # Wire event bus: REST mutations emit MCP resource notifications
    def on_content_changed(event_type: str, path: str, **kwargs: str) -> None:
        logger.info(f"Content event: {event_type} {path} {kwargs}")

        # Async bridge: trigger search index updates from sync event bus
        if search_engine is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug("No running event loop; skipping search index update")
                return
            if event_type in ("content_created", "content_updated"):
                task = loop.create_task(search_engine.index_file(path))
                task.add_done_callback(_log_task_exception)
            elif event_type == "content_deleted":
                task = loop.create_task(search_engine.remove_file(path))
                task.add_done_callback(_log_task_exception)
            elif event_type == "content_moved":
                source_path = kwargs.get("source_path", "")
                if source_path:
                    task = loop.create_task(search_engine.remove_file(source_path))
                    task.add_done_callback(_log_task_exception)
                task = loop.create_task(search_engine.index_file(path))
                task.add_done_callback(_log_task_exception)

    add_listener(on_content_changed)

    # Non-blocking startup index build
    @app.on_event("startup")
    async def _build_search_index():
        if search_engine is not None:
            files = filesystem.list_all_files()
            task = asyncio.create_task(search_engine.build_index(files))
            task.add_done_callback(_log_task_exception)

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
