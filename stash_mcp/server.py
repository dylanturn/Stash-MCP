"""Main server entry point for stdio MCP transport."""

import asyncio
import logging
import os
import sys

from .config import Config
from .filesystem import FileSystem
from .mcp_server import create_mcp_server

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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
            contextual_model=Config.CONTEXTUAL_MODEL,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            chunk_size=Config.SEARCH_CHUNK_SIZE,
            chunk_overlap=Config.SEARCH_CHUNK_OVERLAP,
        )
        engine._filesystem = filesystem
        logger.info(f"Search engine initialised (model={Config.SEARCH_EMBEDDER_MODEL})")
        return engine
    except Exception as e:
        logger.error(f"Failed to create search engine: {e}")
        return None


def _create_git_backend():
    """Validate git config and return a GitBackend, or None if tracking is off."""
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
    return backend


async def main():
    """Run the Stash MCP server over stdio."""
    logger.info("Starting Stash-MCP server...")
    if Config.READ_ONLY:
        logger.info("Read-only mode enabled — write tools will not be registered")

    # Clone remote repo if configured (before ensuring content dir exists)
    _maybe_clone_repo()

    # Ensure content directory exists
    Config.ensure_content_dir()

    # Initialize filesystem
    filesystem = FileSystem(Config.CONTENT_DIR, include_patterns=Config.CONTENT_PATHS)

    # Optionally create search engine and git backend
    search_engine = _create_search_engine(filesystem)
    git_backend = _create_git_backend()

    # Create FastMCP server and run with stdio transport
    mcp = create_mcp_server(filesystem, search_engine=search_engine, git_backend=git_backend)

    if search_engine is not None:
        files = filesystem.list_all_files()
        await search_engine.build_index(files)
        logger.info("Search index built")

    logger.info(f"Server running with content dir: {Config.CONTENT_DIR}")
    await mcp.run_stdio_async()


def run():
    """Synchronous entry point for stdio MCP transport (used by uvx/extensions)."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
