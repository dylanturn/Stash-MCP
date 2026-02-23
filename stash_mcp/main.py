"""FastAPI app entrypoint for Stash-MCP."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from starlette.types import ASGIApp, Receive, Scope, Send

from .api import create_api
from .config import Config
from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_UPDATED, add_listener, emit
from .filesystem import FileSystem
from .mcp_server import create_mcp_server
from .ui import create_ui_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _create_search_engine():
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
            contextual_model=Config.CONTEXTUAL_MODEL,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            chunk_size=Config.SEARCH_CHUNK_SIZE,
            chunk_overlap=Config.SEARCH_CHUNK_OVERLAP,
        )
        logger.info(
            f"Search engine initialised (model={Config.SEARCH_EMBEDDER_MODEL}, "
            f"contextual={Config.CONTEXTUAL_RETRIEVAL})"
        )
        return engine
    except Exception as e:
        logger.error(f"Failed to create search engine: {e}")
        return None


def _create_git_backend():
    """Validate git config and return a GitBackend, or None if tracking is off.

    Raises SystemExit on misconfiguration so the server fails fast.
    """
    if Config.GIT_SYNC_ENABLED and not Config.GIT_TRACKING:
        logger.error(
            "STASH_GIT_SYNC_ENABLED=true requires STASH_GIT_TRACKING=true. "
            "Set STASH_GIT_TRACKING=true or disable sync."
        )
        raise SystemExit(1)

    if not Config.GIT_TRACKING:
        return None

    from .git_backend import GitBackend

    backend = GitBackend(Config.CONTENT_DIR, sync_token=Config.GIT_SYNC_TOKEN)

    try:
        backend.validate()
    except RuntimeError as exc:
        logger.error("Git tracking enabled but validation failed: %s", exc)
        raise SystemExit(1) from exc

    logger.info("Git tracking active (content_dir=%s)", Config.CONTENT_DIR)

    if Config.GIT_SYNC_ENABLED:
        if not backend.validate_remote(Config.GIT_SYNC_REMOTE):
            logger.error(
                "Git sync remote '%s' is not configured in the repository.",
                Config.GIT_SYNC_REMOTE,
            )
            raise SystemExit(1)
        logger.info(
            "Git sync enabled (remote=%s branch=%s interval=%ds)",
            Config.GIT_SYNC_REMOTE,
            Config.GIT_SYNC_BRANCH,
            Config.GIT_SYNC_INTERVAL,
        )

    return backend


def _task_done_callback(task: asyncio.Task) -> None:
    """Log exceptions from background tasks."""
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error(f"Background task {task.get_name()} failed: {exc}", exc_info=exc)


async def _git_sync_loop(git_backend, search_engine) -> None:
    """Periodic git pull task.  Runs until cancelled."""
    remote = Config.GIT_SYNC_REMOTE
    branch = Config.GIT_SYNC_BRANCH
    interval = Config.GIT_SYNC_INTERVAL
    recursive = Config.GIT_SYNC_RECURSIVE

    while True:
        try:
            result = await asyncio.to_thread(git_backend.pull, remote, branch, recursive)
            if result.success:
                logger.info("Git sync: %s", result.message or "up to date")
                for path in result.added_files:
                    emit(CONTENT_CREATED, path)
                for path in result.modified_files:
                    emit(CONTENT_UPDATED, path)
                for path in result.deleted_files:
                    emit(CONTENT_DELETED, path)
            else:
                logger.warning("Git sync pull failed: %s", result.message)
        except Exception as exc:
            logger.warning("Git sync error: %s", exc)
        await asyncio.sleep(interval)


def create_app():
    """Create and configure the FastAPI application."""
    Config.ensure_content_dir()
    filesystem = FileSystem(Config.CONTENT_DIR, include_patterns=Config.CONTENT_PATHS)

    # Optionally create search engine
    search_engine = _create_search_engine()
    if search_engine is not None:
        search_engine._filesystem = filesystem

    # Optionally create git backend (may raise SystemExit on misconfiguration)
    git_backend = _create_git_backend()
    if git_backend is not None and search_engine is not None:
        search_engine._git_backend = git_backend

    # Create MCP http app first so we can wire its lifespan into FastAPI
    mcp = create_mcp_server(filesystem, search_engine=search_engine, git_backend=git_backend)
    mcp_http_app = mcp.http_app(path="/")

    # Build a combined lifespan that wraps the MCP lifespan and also
    # triggers the search index build on startup.  Using on_event("startup")
    # does NOT work when a lifespan handler is set on the FastAPI app.
    mcp_lifespan = mcp_http_app.lifespan

    @asynccontextmanager
    async def _combined_lifespan(fastapi_app):
        async with mcp_lifespan(fastapi_app):
            # Startup: build search index in background (non-blocking)
            if search_engine is not None:

                async def _do_build():
                    files = filesystem.list_all_files()
                    total = await search_engine.build_index(files)
                    logger.info(f"Startup search index build complete: {total} chunks")

                task = asyncio.create_task(_do_build())
                task.add_done_callback(_task_done_callback)

            # Start periodic git sync task if configured
            sync_task = None
            if git_backend is not None and Config.GIT_SYNC_ENABLED:
                sync_task = asyncio.create_task(
                    _git_sync_loop(git_backend, search_engine),
                    name="git-sync",
                )
                sync_task.add_done_callback(_task_done_callback)

            yield

            # Shutdown: cancel the sync task gracefully
            if sync_task is not None and not sync_task.done():
                sync_task.cancel()
                try:
                    await sync_task
                except asyncio.CancelledError:
                    pass

    app = create_api(filesystem, lifespan=_combined_lifespan, search_engine=search_engine)
    ui_router = create_ui_router(filesystem, search_engine=search_engine)
    app.include_router(ui_router)

    # Mount FastMCP server onto FastAPI for streamable HTTP transport
    app.mount("/mcp", mcp_http_app)

    # Normalize /mcp → /mcp/ so the mounted sub-app handles requests to
    # both paths without a 307 redirect.  Redirects can break MCP clients
    # behind reverse proxies (e.g. Cloudflare) that drop the request body.
    class _MCPSlashMiddleware:
        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http" and scope["path"] == "/mcp":
                scope = dict(scope)
                scope["path"] = "/mcp/"
            await self.app(scope, receive, send)

    app.add_middleware(_MCPSlashMiddleware)

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
                task.add_done_callback(_task_done_callback)
            elif event_type == "content_deleted":
                task = loop.create_task(search_engine.remove_file(path))
                task.add_done_callback(_task_done_callback)
            elif event_type == "content_moved":
                source_path = kwargs.get("source_path", "")
                if source_path:
                    task = loop.create_task(search_engine.remove_file(source_path))
                    task.add_done_callback(_task_done_callback)
                task = loop.create_task(search_engine.index_file(path))
                task.add_done_callback(_task_done_callback)

    add_listener(on_content_changed)

    return app


def main():
    """Run the Stash-MCP web server."""
    logger.info("Starting Stash-MCP server...")
    logger.info(f"Server name: {Config.SERVER_NAME}")
    if Config.READ_ONLY:
        logger.info("Read-only mode enabled — write tools will not be registered")
    if Config.GIT_TRACKING:
        logger.info("Git tracking enabled")
    if Config.GIT_SYNC_ENABLED:
        logger.info(
            f"Git sync enabled: remote={Config.GIT_SYNC_REMOTE} "
            f"branch={Config.GIT_SYNC_BRANCH} interval={Config.GIT_SYNC_INTERVAL}s"
        )

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
