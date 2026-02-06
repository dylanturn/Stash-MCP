"""Main server entry point."""

import asyncio
import logging
import sys

from mcp.server.stdio import stdio_server

from .config import Config
from .filesystem import FileSystem
from .mcp_server import StashMCPServer

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Run the Stash MCP server."""
    logger.info("Starting Stash-MCP server...")
    
    # Ensure content directory exists
    Config.ensure_content_dir()
    
    # Initialize filesystem
    filesystem = FileSystem(Config.CONTENT_DIR)
    
    # Initialize MCP server
    mcp_server = StashMCPServer(filesystem)
    
    # Run server with stdio transport
    logger.info(f"Server running with content dir: {Config.CONTENT_DIR}")
    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.get_server().run(
            read_stream,
            write_stream,
            mcp_server.get_server().create_initialization_options()
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
