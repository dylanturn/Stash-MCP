"""MCP Server implementation for Stash."""

import logging

from mcp.server import Server
from mcp.types import Resource, TextContent, Tool

from .config import Config
from .filesystem import FileNotFoundError, FileSystem, InvalidPathError

logger = logging.getLogger(__name__)


class StashMCPServer:
    """MCP Server for Stash content management."""

    def __init__(self, filesystem: FileSystem):
        """Initialize the MCP server.

        Args:
            filesystem: Filesystem instance for content management
        """
        self.fs = filesystem
        self.server = Server(Config.SERVER_NAME)
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Set up MCP protocol handlers."""

        @self.server.list_resources()
        async def list_resources() -> list[Resource]:
            """List all available resources (files)."""
            resources = []
            try:
                files = self.fs.list_all_files()
                for file_path in files:
                    # Convert file path to stash:// URI
                    uri = f"stash://{file_path}"
                    resources.append(
                        Resource(
                            uri=uri,
                            name=file_path,
                            mimeType="text/plain",
                            description=f"Content file: {file_path}",
                        )
                    )
                logger.info(f"Listed {len(resources)} resources")
            except Exception as e:
                logger.error(f"Error listing resources: {e}")
            return resources

        @self.server.read_resource()
        async def read_resource(uri: str) -> str:
            """Read a resource by URI.

            Args:
                uri: Resource URI in format stash://path/to/file

            Returns:
                Resource content
            """
            # Extract path from URI
            if not uri.startswith("stash://"):
                raise ValueError(f"Invalid URI scheme: {uri}")

            file_path = uri[8:]  # Remove 'stash://' prefix

            try:
                content = self.fs.read_file(file_path)
                logger.info(f"Read resource: {uri}")
                return content
            except FileNotFoundError:
                raise ValueError(f"Resource not found: {uri}")
            except InvalidPathError as e:
                raise ValueError(f"Invalid resource path: {e}")
            except Exception as e:
                logger.error(f"Error reading resource {uri}: {e}")
                raise ValueError(f"Failed to read resource: {e}")

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools for content management."""
            return [
                Tool(
                    name="create_content",
                    description="Create a new content file",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to content root",
                            },
                            "content": {
                                "type": "string",
                                "description": "File content",
                            },
                        },
                        "required": ["path", "content"],
                    },
                ),
                Tool(
                    name="update_content",
                    description="Update an existing content file",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to content root",
                            },
                            "content": {
                                "type": "string",
                                "description": "New file content",
                            },
                        },
                        "required": ["path", "content"],
                    },
                ),
                Tool(
                    name="delete_content",
                    description="Delete a content file",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path relative to content root",
                            },
                        },
                        "required": ["path"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Execute a tool.

            Args:
                name: Tool name
                arguments: Tool arguments

            Returns:
                Tool execution result
            """
            try:
                if name == "create_content":
                    return await self._create_content(arguments)
                elif name == "update_content":
                    return await self._update_content(arguments)
                elif name == "delete_content":
                    return await self._delete_content(arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
            except Exception as e:
                logger.error(f"Error executing tool {name}: {e}")
                return [TextContent(type="text", text=f"Error: {str(e)}")]

    async def _create_content(self, arguments: dict) -> list[TextContent]:
        """Create new content file.

        Args:
            arguments: Tool arguments with 'path' and 'content'

        Returns:
            Success message
        """
        path = arguments.get("path")
        content = arguments.get("content")

        if not path or not content:
            raise ValueError("Both 'path' and 'content' are required")

        # Check if file already exists
        if self.fs.file_exists(path):
            raise ValueError(f"File already exists: {path}")

        self.fs.write_file(path, content)

        # Notify about resource update
        uri = f"stash://{path}"
        await self.server.request_context.session.send_resource_updated(uri)

        return [TextContent(type="text", text=f"Created: {path}")]

    async def _update_content(self, arguments: dict) -> list[TextContent]:
        """Update existing content file.

        Args:
            arguments: Tool arguments with 'path' and 'content'

        Returns:
            Success message
        """
        path = arguments.get("path")
        content = arguments.get("content")

        if not path or not content:
            raise ValueError("Both 'path' and 'content' are required")

        # File can be created or updated
        self.fs.write_file(path, content)

        # Notify about resource update
        uri = f"stash://{path}"
        await self.server.request_context.session.send_resource_updated(uri)

        return [TextContent(type="text", text=f"Updated: {path}")]

    async def _delete_content(self, arguments: dict) -> list[TextContent]:
        """Delete content file.

        Args:
            arguments: Tool arguments with 'path'

        Returns:
            Success message
        """
        path = arguments.get("path")

        if not path:
            raise ValueError("'path' is required")

        self.fs.delete_file(path)

        # Notify about resource deletion
        uri = f"stash://{path}"
        await self.server.request_context.session.send_resource_updated(uri)

        return [TextContent(type="text", text=f"Deleted: {path}")]

    def get_server(self) -> Server:
        """Get the MCP server instance."""
        return self.server
