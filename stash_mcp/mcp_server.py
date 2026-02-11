"""MCP Server implementation for Stash using FastMCP."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.resources import FunctionResource
from fastmcp.server.context import Context
from pydantic import AnyUrl

from .config import Config
from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_MOVED, CONTENT_UPDATED, emit
from .filesystem import FileNotFoundError, FileSystem, InvalidPathError

logger = logging.getLogger(__name__)

# Mime type mapping for common extensions
MIME_TYPES: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".ts": "application/typescript",
    ".py": "text/x-python",
    ".csv": "text/csv",
    ".toml": "application/toml",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".rst": "text/x-rst",
    ".log": "text/plain",
}


def _get_mime_type(path: str) -> str:
    """Get mime type for a file path based on extension."""
    from pathlib import PurePosixPath

    suffix = PurePosixPath(path).suffix.lower()
    return MIME_TYPES.get(suffix, "text/plain")


def _get_description(fs: FileSystem, path: str) -> str:
    """Get description for a file from frontmatter or first line."""
    try:
        content = fs.read_file(path)
        lines = content.strip().splitlines()
        if not lines:
            return f"Content file: {path}"
        first_line = lines[0].strip()
        # Strip markdown heading markers
        if first_line.startswith("#"):
            first_line = first_line.lstrip("# ").strip()
        return first_line[:100] if first_line else f"Content file: {path}"
    except Exception:
        return f"Content file: {path}"


def create_mcp_server(filesystem: FileSystem, auth=None) -> FastMCP:
    """Create and configure the FastMCP server.

    Args:
        filesystem: Filesystem instance for content management
        auth: Optional OAuth provider for authentication (e.g. GitHubProvider)

    Returns:
        Configured FastMCP server
    """

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
        """Lifespan handler to inject filesystem into context."""
        yield {"fs": filesystem}

    mcp = FastMCP(
        name=Config.SERVER_NAME,
        version=Config.SERVER_VERSION,
        lifespan=lifespan,
        auth=auth,
    )

    # --- Resources ---

    # Register individual resources for each file (for resources/list)
    for file_path in filesystem.list_all_files():
        uri = f"stash://{file_path}"
        mime = _get_mime_type(file_path)
        desc = _get_description(filesystem, file_path)
        fp = file_path  # capture for closure

        mcp.add_resource(
            FunctionResource(
                uri=AnyUrl(uri),
                name=file_path,
                description=desc,
                mime_type=mime,
                fn=lambda _fp=fp: filesystem.read_file(_fp),
            )
        )

    def _register_resource(path: str) -> None:
        """Add a file to the MCP resource registry."""
        uri = f"stash://{path}"
        mcp.add_resource(FunctionResource(
            uri=AnyUrl(uri), name=path,
            description=_get_description(filesystem, path),
            mime_type=_get_mime_type(path),
            fn=lambda _fp=path: filesystem.read_file(_fp),
        ))

    def _unregister_resource(path: str) -> None:
        """Remove a file from the MCP resource registry."""
        uri_key = f"stash://{path}"
        mcp._resource_manager._resources.pop(uri_key, None)

    # Resource template for dynamic access (resources/templates/list)
    @mcp.resource("stash://{path}", mime_type="text/plain", description="Read any file by path")
    def read_resource(path: str) -> str:
        """Read a file by its path."""
        try:
            return filesystem.read_file(path)
        except FileNotFoundError:
            raise ValueError(f"Resource not found: stash://{path}")
        except InvalidPathError as e:
            raise ValueError(f"Invalid resource path: {e}")

    # --- Tools ---

    @mcp.tool(description="Create a new content file")
    async def create_content(
        path: str,
        content: str,
        ctx: Context,
    ) -> str:
        """Create a new file. Errors if file already exists.

        Args:
            path: File path relative to content root
            content: File content
        """
        if filesystem.file_exists(path):
            raise ValueError(
                f"File already exists: {path}. Use update_content to modify existing files."
            )
        filesystem.write_file(path, content)
        _register_resource(path)
        await ctx.send_resource_list_changed()
        emit(CONTENT_CREATED, path)
        logger.info(f"Created: {path}")
        return f"Created: {path}"

    @mcp.tool(description="Update an existing content file")
    async def update_content(
        path: str,
        content: str,
        ctx: Context,
    ) -> str:
        """Update an existing file.

        Args:
            path: File path relative to content root
            content: New file content
        """
        is_new = not filesystem.file_exists(path)
        filesystem.write_file(path, content)
        if is_new:
            _register_resource(path)
            await ctx.send_resource_list_changed()
            emit(CONTENT_CREATED, path)
        else:
            uri = AnyUrl(f"stash://{path}")
            await ctx.session.send_resource_updated(uri=uri)
            emit(CONTENT_UPDATED, path)
        logger.info(f"Updated: {path}")
        return f"Updated: {path}"

    @mcp.tool(description="Delete a content file")
    async def delete_content(
        path: str,
        ctx: Context,
    ) -> str:
        """Delete a file.

        Args:
            path: File path relative to content root
        """
        filesystem.delete_file(path)
        _unregister_resource(path)
        await ctx.send_resource_list_changed()
        emit(CONTENT_DELETED, path)
        logger.info(f"Deleted: {path}")
        return f"Deleted: {path}"

    @mcp.tool(description="List files and directories")
    async def list_content(
        path: str = "",
        recursive: bool = False,
    ) -> str:
        """List files and directories in the content store.

        Args:
            path: Path relative to content root (defaults to root)
            recursive: If true, list all files recursively
        """
        if recursive:
            files = filesystem.list_all_files(path)
            if not files:
                return f"No files found under '{path or '/'}'"
            return "\n".join(files)
        else:
            items = filesystem.list_files(path)
            lines = []
            for name, is_dir in items:
                prefix = "📁 " if is_dir else "📄 "
                lines.append(f"{prefix}{name}")
            if not lines:
                return f"Empty directory: '{path or '/'}'"
            return "\n".join(lines)

    @mcp.tool(description="Move or rename a content file")
    async def move_content(
        source_path: str,
        dest_path: str,
        ctx: Context,
    ) -> str:
        """Move or rename a file.

        Args:
            source_path: Current file path relative to content root
            dest_path: New file path relative to content root
        """
        filesystem.move_file(source_path, dest_path)
        _unregister_resource(source_path)
        _register_resource(dest_path)
        await ctx.send_resource_list_changed()
        emit(CONTENT_MOVED, dest_path, source_path=source_path)
        logger.info(f"Moved: {source_path} -> {dest_path}")
        return f"Moved: {source_path} -> {dest_path}"

    return mcp
