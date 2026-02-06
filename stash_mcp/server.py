"""Main server entry point for stdio MCP transport."""

import asyncio
import logging
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


async def main():
    """Run the Stash MCP server over stdio."""
    logger.info("Starting Stash-MCP server...")

    # Ensure content directory exists
    Config.ensure_content_dir()

    # Initialize filesystem
    filesystem = FileSystem(Config.CONTENT_DIR, include_patterns=Config.CONTENT_PATHS)

    # Create FastMCP server and run with stdio transport
    mcp = create_mcp_server(filesystem)

    logger.info(f"Server running with content dir: {Config.CONTENT_DIR}")
    await mcp.run_stdio_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
