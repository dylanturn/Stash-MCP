"""Main entry point for running stash_mcp as a module."""

from .server import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
