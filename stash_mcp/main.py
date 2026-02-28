"""FastAPI app entrypoint for Stash-MCP."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from .api import create_api
from .config import Config
from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_UPDATED, add_listener, emit
from .filesystem import FileSystem
from .mcp_server import create_mcp_server
from .metrics import get_metrics, init_metrics
from .ui import create_ui_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Mapping from event bus event types to metric event names
_CONTENT_EVENT_METRIC_MAP = {
    "content_created": "created",
    "content_updated": "updated",
    "content_deleted": "deleted",
    "content_moved": "moved",
}


def _maybe_clone_repo() -> None:
    """Clone remote repo into content dir if STASH_GIT_CLONE_URL is configured."""
    if not Config.GIT_CLONE_URL:
        return

    content_dir = Config.CONTENT_DIR

    if content_dir.exists() and any(content_dir.iterdir()):
        git_dir = content_dir / ".git"
        if git_dir.exists():
            logger.info("Content directory already contains a git repo, skipping clone")
            return
        logger.error(
            "Content directory %s is non-empty but not a git repo. "
            "Cannot clone into it. Clear the directory or remove STASH_GIT_CLONE_URL.",
            content_dir,
        )
        raise SystemExit(1)

    from .git_backend import GitBackend

    logger.info(
        "Cloning %s (branch=%s) into %s",
        Config.GIT_CLONE_URL,
        Config.GIT_CLONE_BRANCH,
        content_dir,
    )
    try:
        GitBackend.clone(
            url=Config.GIT_CLONE_URL,
            target_dir=content_dir,
            branch=Config.GIT_CLONE_BRANCH,
            token=Config.GIT_CLONE_TOKEN,
            recursive=Config.GIT_SYNC_RECURSIVE,
        )
    except RuntimeError as exc:
        logger.error("Clone failed: %s", exc)
        raise SystemExit(1) from exc

    Config.GIT_TRACKING = True
    logger.info("Clone complete. Git tracking auto-enabled.")


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

    backend = GitBackend(
        Config.CONTENT_DIR,
        sync_token=Config.GIT_SYNC_TOKEN,
        author_default=Config.GIT_AUTHOR_DEFAULT,
    )

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


async def _git_sync_loop(
    git_backend, search_engine, sync_event: asyncio.Event | None = None
) -> None:
    """Periodic git pull task.  Runs until cancelled."""
    remote = Config.GIT_SYNC_REMOTE
    branch = Config.GIT_SYNC_BRANCH
    interval = Config.GIT_SYNC_INTERVAL
    recursive = Config.GIT_SYNC_RECURSIVE

    while True:
        try:
            if sync_event is None or sync_event.is_set():
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
            else:
                logger.debug("Git sync skipped: transaction in progress")
        except Exception as exc:
            logger.warning("Git sync error: %s", exc)
        await asyncio.sleep(interval)


def create_app():
    """Create and configure the FastAPI application."""
    _maybe_clone_repo()
    Config.ensure_content_dir()
    filesystem = FileSystem(Config.CONTENT_DIR, include_patterns=Config.CONTENT_PATHS)

    # Initialise metrics collector (no-op when disabled)
    init_metrics(
        db_path=str(Config.METRICS_PATH),
        enabled=Config.METRICS_ENABLED,
        retention_days=Config.METRICS_RETENTION_DAYS,
    )

    # Optionally create search engine
    search_engine = _create_search_engine()
    if search_engine is not None:
        search_engine._filesystem = filesystem

    # Optionally create git backend (may raise SystemExit on misconfiguration)
    git_backend = _create_git_backend()
    if git_backend is not None and search_engine is not None:
        search_engine._git_backend = git_backend

    # When git tracking and writes are both active, wrap the filesystem in a
    # TransactionManager so that all mutating MCP tool calls are gated behind
    # an active transaction.
    transaction_manager = None
    fs_for_mcp = filesystem
    if not Config.READ_ONLY and git_backend is not None:
        from .transactions import TransactionManager

        transaction_manager = TransactionManager(filesystem, git_backend)
        fs_for_mcp = transaction_manager

    # Create MCP http app first so we can wire its lifespan into FastAPI
    mcp = create_mcp_server(fs_for_mcp, search_engine=search_engine, git_backend=git_backend)
    mcp_http_app = mcp.http_app(path="/")

    # Build a combined lifespan that wraps the MCP lifespan and also
    # triggers the search index build on startup.  Using on_event("startup")
    # does NOT work when a lifespan handler is set on the FastAPI app.
    mcp_lifespan = mcp_http_app.lifespan

    @asynccontextmanager
    async def _combined_lifespan(fastapi_app):
        # Set up a sync-pause event and register callbacks on the TransactionManager
        # so that git sync is suspended for the duration of any active transaction.
        sync_event = asyncio.Event()
        sync_event.set()  # set = sync allowed; cleared = sync paused during a transaction
        if transaction_manager is not None:
            transaction_manager.set_sync_callbacks(
                pause=lambda: sync_event.clear(),
                resume=lambda: sync_event.set(),
            )

        async with mcp_lifespan(fastapi_app):
            # Startup: build search index in background (non-blocking)
            get_metrics().record_server_event("startup")
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
                    _git_sync_loop(git_backend, search_engine, sync_event),
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
            get_metrics().record_server_event("shutdown")
            get_metrics().close()

    app = create_api(filesystem, lifespan=_combined_lifespan, search_engine=search_engine)
    ui_router = create_ui_router(filesystem, search_engine=search_engine)
    app.include_router(ui_router)

    # Serve vendored static assets (highlight.js, mermaid.js, etc.)
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

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

        # Record content lifecycle metric
        metric_event = _CONTENT_EVENT_METRIC_MAP.get(event_type)
        if metric_event:
            try:
                full_path = Config.CONTENT_DIR / path
                size = full_path.stat().st_size if full_path.is_file() else 0
            except Exception:
                size = 0
            get_metrics().record_content_event(metric_event, path, size_bytes=size)

        # Async bridge: trigger search index updates from sync event bus
        if search_engine is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug("No running event loop; skipping search index update")
                return
            if event_type in ("content_created", "content_updated"):
                task = loop.create_task(
                    search_engine.index_file(path), name=f"index-{path}"
                )
                task.add_done_callback(_task_done_callback)
            elif event_type == "content_deleted":
                task = loop.create_task(
                    search_engine.remove_file(path), name=f"remove-{path}"
                )
                task.add_done_callback(_task_done_callback)
            elif event_type == "content_moved":
                source_path = kwargs.get("source_path", "")
                if source_path:
                    task = loop.create_task(
                        search_engine.move_file_index(source_path, path),
                        name=f"move-{source_path}->{path}",
                    )
                    task.add_done_callback(_task_done_callback)
                else:
                    task = loop.create_task(
                        search_engine.index_file(path), name=f"index-{path}"
                    )
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
