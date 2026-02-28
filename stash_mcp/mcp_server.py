"""MCP Server implementation for Stash using FastMCP."""

import functools
import hashlib
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from fastmcp import FastMCP
from fastmcp.resources import FunctionResource
from fastmcp.server.context import Context
from mcp.types import ToolAnnotations
from pydantic import AnyUrl, BaseModel, Field

from .config import Config
from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_MOVED, CONTENT_UPDATED, emit
from .filesystem import FileNotFoundError, FileSystem, InvalidPathError
from .metrics import get_metrics

logger = logging.getLogger(__name__)


class EditOperation(BaseModel):
    """A single string-replacement edit."""

    old_string: str = Field(description="The exact text to find in the file")
    new_string: str = Field(description="The text to replace it with")
    replace_all: bool = Field(
        default=False,
        description="Replace every occurrence (True) or require exactly one match (False)",
    )


class FileEditOperation(BaseModel):
    """Edits targeting a single file, used by edit_content_batch."""

    file_path: str = Field(description="File path relative to content root")
    sha: str = Field(description="SHA-256 hex digest of the current file content")
    edits: list[EditOperation] = Field(description="Ordered list of edits to apply")


class MoveOperation(BaseModel):
    """A single file move operation."""

    source_path: str = Field(description="Current file path relative to content root")
    dest_path: str = Field(description="New file path relative to content root")


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

# Only files matching this name are exposed as MCP resources.
# All other files remain accessible via tools and the resource template.
RESOURCE_FILENAME = "README.md"


def _is_resource_file(path: str) -> bool:
    """Check if a file should be exposed as an MCP resource."""
    # Normalize to POSIX-style path and remove trailing slashes to handle
    # inputs with OS-native separators or accidental trailing separators.
    normalized = path.replace("\\", "/").rstrip("/")
    return PurePosixPath(normalized).name == RESOURCE_FILENAME


def _get_mime_type(path: str) -> str:
    """Get mime type for a file path based on extension."""
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


def _apply_edits(content: str, edits: list[EditOperation], path: str) -> str:
    """Apply a sequence of string-replacement edits to *content*.

    Raises ``ValueError`` if any edit is invalid (empty old_string, not found,
    or ambiguous when replace_all is False).
    """
    for edit in edits:
        if not edit.old_string:
            raise ValueError(f"old_string must not be empty (file: {path})")
        if edit.old_string not in content:
            raise ValueError(
                f"old_string not found in '{path}'. The file content may have changed."
            )
        if not edit.replace_all and content.count(edit.old_string) > 1:
            raise ValueError(
                f"old_string appears {content.count(edit.old_string)} times in '{path}'. "
                "Set replace_all=True or provide a more specific old_string."
            )
        if edit.replace_all:
            content = content.replace(edit.old_string, edit.new_string)
        else:
            content = content.replace(edit.old_string, edit.new_string, 1)
    return content


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_FENCE_RE = re.compile(r"^```")


def _build_heading_tree(flat: list[dict]) -> list[dict]:
    """Convert a flat list of headings into a nested tree."""
    root: list[dict] = []
    stack: list[dict] = []

    for heading in flat:
        while stack and stack[-1]["level"] >= heading["level"]:
            stack.pop()

        if stack:
            stack[-1]["children"].append(heading)
        else:
            root.append(heading)

        stack.append(heading)

    return root


def parse_markdown_structure(content: str) -> list[dict]:
    """Parse markdown content and return a nested heading structure."""
    in_code_block = False
    flat_headings: list[dict] = []

    for line_num, line in enumerate(content.splitlines(), start=1):
        if _FENCE_RE.match(line.strip()):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        match = _HEADING_RE.match(line.strip())
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            flat_headings.append({
                "heading": text,
                "level": level,
                "line_number": line_num,
                "children": [],
            })

    return _build_heading_tree(flat_headings)


def create_mcp_server(filesystem: FileSystem, search_engine=None, git_backend=None) -> FastMCP:
    """Create and configure the FastMCP server.

    Args:
        filesystem: Filesystem instance for content management
        search_engine: Optional SearchEngine instance for semantic search
        git_backend: Optional GitBackend instance for git tools

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
    )

    # Wrap mcp.tool() so every registered tool is automatically timed and
    # its outcome recorded in the metrics collector.  Using functools.wraps
    # preserves the original signature so FastMCP generates the correct schema.
    _original_mcp_tool = mcp.tool

    def _instrumented_tool(*deco_args, **deco_kwargs):
        orig_decorator = _original_mcp_tool(*deco_args, **deco_kwargs)

        def patching_decorator(fn):
            tool_name = fn.__name__

            @functools.wraps(fn)
            async def _tracked(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                    get_metrics().record_tool_call(
                        tool_name, (time.perf_counter() - t0) * 1000, True
                    )
                    return result
                except Exception as exc:
                    get_metrics().record_tool_call(
                        tool_name,
                        (time.perf_counter() - t0) * 1000,
                        False,
                        type(exc).__name__,
                    )
                    raise

            return orig_decorator(_tracked)

        return patching_decorator

    mcp.tool = _instrumented_tool

    # --- Resources ---

    # Register only README.md files as resources (for resources/list).
    # All other files are accessible via tools and the resource template.
    for file_path in filesystem.list_all_files():
        if not _is_resource_file(file_path):
            continue
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

    def _register_resource(path: str) -> bool:
        """Add a file to the MCP resource registry if it is a README.md.

        Returns:
            True if a resource was registered, False otherwise.
        """
        if not _is_resource_file(path):
            return False
        uri = f"stash://{path}"
        mcp.add_resource(FunctionResource(
            uri=AnyUrl(uri), name=path,
            description=_get_description(filesystem, path),
            mime_type=_get_mime_type(path),
            fn=lambda _fp=path: filesystem.read_file(_fp),
        ))
        return True

    def _unregister_resource(path: str) -> bool:
        """Remove a file from the MCP resource registry.

        Returns:
            True if a resource was removed, False otherwise.
        """
        if not _is_resource_file(path):
            return False
        uri_key = f"stash://{path}"
        try:
            # fastmcp 3.x: use public local_provider API
            mcp.local_provider.remove_resource(uri_key)
            return True
        except AttributeError:
            # fastmcp 2.x: ResourceManager exposes _resources dict directly
            return mcp._resource_manager._resources.pop(uri_key, None) is not None
        except KeyError:
            return False

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

    # --- Write tools (only registered when not in read-only mode) ---

    if not Config.READ_ONLY:

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Create file",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def create_content(
            path: str,
            content: str,
            ctx: Context,
        ) -> str:
            """
            Create a new file. Errors if file already exists.

            Args:
                path: File path relative to content root
                content: File content
            """
            if filesystem.file_exists(path):
                raise ValueError(
                    f"File already exists: {path}. Use update_content to modify existing files."
                )
            filesystem.write_file(path, content)
            if _register_resource(path):
                await ctx.send_resource_list_changed()
            emit(CONTENT_CREATED, path)
            logger.info(f"Created: {path}")
            return f"Created: {path}"

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Overwrite file content",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            )
        )
        async def overwrite_content(
            path: str,
            content: str,
            sha: str,
            ctx: Context,
        ) -> str:
            """
            Replace the content of an existing file.

            Args:
                path: File path relative to content root
                content: New file content
                sha: SHA-256 hex digest of the current file content (from read_content)
            """
            if filesystem.file_exists(path):
                current = filesystem.read_file(path)
                current_sha = hashlib.sha256(current.encode("utf-8")).hexdigest()
                if sha != current_sha:
                    raise ValueError(
                        f"SHA mismatch for '{path}': expected {current_sha}, got {sha}. "
                        "The file may have changed since it was last read."
                    )
            else:
                raise FileNotFoundError(
                    f"File '{path}' does not exist. Use create_content for new files."
                )
            filesystem.write_file(path, content)
            if _is_resource_file(path):
                uri = AnyUrl(f"stash://{path}")
                await ctx.session.send_resource_updated(uri=uri)
            emit(CONTENT_UPDATED, path)
            logger.info(f"Updated: {path}")
            return f"Updated: {path}"

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Edit file",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            )
        )
        async def edit_content(
            file_path: str,
            sha: str,
            edits: list[EditOperation],
            ctx: Context,
        ) -> dict:
            """
            Apply targeted string-replacement edits to an existing file.

            Each edit replaces an exact occurrence of old_string with new_string.
            Edits are applied sequentially — later edits see the result of earlier ones.

            Args:
                file_path: File path relative to content root
                sha: SHA-256 hex digest of the current file content (from read_content)
                edits: Ordered list of edit operations to apply
            Returns:
                A dict with path, result status, and new_sha
            """
            current = filesystem.read_file(file_path)
            current_sha = hashlib.sha256(current.encode("utf-8")).hexdigest()
            if sha != current_sha:
                raise ValueError(
                    f"SHA mismatch for '{file_path}': expected {current_sha}, got {sha}. "
                    "The file may have changed since it was last read."
                )
            new_content = _apply_edits(current, edits, file_path)
            filesystem.write_file(file_path, new_content)
            if _is_resource_file(file_path):
                uri = AnyUrl(f"stash://{file_path}")
                await ctx.session.send_resource_updated(uri=uri)
            emit(CONTENT_UPDATED, file_path)
            logger.info(f"Edited: {file_path}")
            new_sha = hashlib.sha256(new_content.encode("utf-8")).hexdigest()
            return {"path": file_path, "result": "ok", "new_sha": new_sha}

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Edit multiple files",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            )
        )
        async def edit_content_batch(
            edit_operations: list[FileEditOperation],
            ctx: Context,
        ) -> dict:
            """
            Atomically apply edits to multiple files.

            All validations run before any writes — if any file fails validation
            the entire operation is aborted and no files are modified.

            Args:
                edit_operations: List of per-file edit operations
            Returns:
                A dict with a results list containing path, result status, and new_sha per file
            """
            # Reject duplicate file paths
            paths = [op.file_path for op in edit_operations]
            if len(paths) != len(set(paths)):
                raise ValueError("Duplicate file_path entries are not allowed in a single edit_content_batch call.")

            # Phase 1: read all files and validate SHAs
            originals: dict[str, str] = {}
            for op in edit_operations:
                current = filesystem.read_file(op.file_path)
                current_sha = hashlib.sha256(current.encode("utf-8")).hexdigest()
                if op.sha != current_sha:
                    raise ValueError(
                        f"SHA mismatch for '{op.file_path}': expected {current_sha}, got {op.sha}. "
                        "The file may have changed since it was last read."
                    )
                originals[op.file_path] = current

            # Phase 2: apply all edits in memory
            new_contents: dict[str, str] = {}
            for op in edit_operations:
                new_contents[op.file_path] = _apply_edits(originals[op.file_path], op.edits, op.file_path)

            # Phase 3: write all files and send notifications
            results = []
            for op in edit_operations:
                filesystem.write_file(op.file_path, new_contents[op.file_path])
                if _is_resource_file(op.file_path):
                    uri = AnyUrl(f"stash://{op.file_path}")
                    await ctx.session.send_resource_updated(uri=uri)
                emit(CONTENT_UPDATED, op.file_path)
                logger.info(f"Edited: {op.file_path}")
                new_sha = hashlib.sha256(new_contents[op.file_path].encode("utf-8")).hexdigest()
                results.append({"path": op.file_path, "result": "ok", "new_sha": new_sha})

            return {"results": results}

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Delete file",
                readOnlyHint=False,
                destructiveHint=True,
                openWorldHint=False,
            )
        )
        async def delete_content(
            path: str,
            sha: str,
            ctx: Context,
        ) -> str:
            """
            Delete a content file.

            Args:
                path: File path relative to content root
                sha: SHA-256 hex digest of the current file content (from read_content)
            Returns:
                Confirmation message
            """
            current = filesystem.read_file(path)
            current_sha = hashlib.sha256(current.encode("utf-8")).hexdigest()
            if sha != current_sha:
                raise ValueError(
                    f"SHA mismatch for '{path}': expected {current_sha}, got {sha}. "
                    "The file may have changed since it was last read."
                )
            filesystem.delete_file(path)
            if _unregister_resource(path):
                await ctx.send_resource_list_changed()
            emit(CONTENT_DELETED, path)
            logger.info(f"Deleted: {path}")
            return f"Deleted: {path}"

    # --- Read-only tools (always registered) ---

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Read file content",
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def read_content(
        path: str,
        max_lines: int | None = None,
    ) -> dict:
        """
        Read and return the contents of a file along with its SHA-256 hash.
        The SHA will be required for update and delete operations to ensure the file has not changed since it was read.

        Args:
            path: File path relative to content root
            max_lines: Optional maximum number of lines to return from the
                beginning of the file. If omitted, returns the full file.
        Returns:
            A dict with 'content' (file text), 'sha' (SHA-256 hex digest of
            the FULL file), and 'truncated' (bool)
        """
        content = filesystem.read_file(path)
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        truncated = False
        if max_lines is not None:
            if max_lines < 1:
                raise ValueError("max_lines must be a positive integer.")
            lines = content.splitlines(keepends=True)
            if len(lines) > max_lines:
                content = "".join(lines[:max_lines])
                truncated = True
        return {"content": content, "sha": sha, "truncated": truncated}

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Read multiple files",
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def read_content_batch(
        paths: list[str],
        max_lines: int | None = None,
    ) -> dict:
        """Read multiple files and return their contents with SHA-256 hashes.

        Reads up to 10 files in a single call. Each file's content and SHA
        are returned so they can be used with update/delete operations.

        Args:
            paths: List of file paths relative to content root (max 10)
            max_lines: Optional maximum number of lines to return from the
                beginning of each file. If omitted, returns full content.
        Returns:
            A dict with 'results' list, each containing 'path', 'content',
            'sha', 'truncated', and 'error' (null on success)
        """
        if not paths:
            raise ValueError("At least one path is required.")
        if len(paths) > 10:
            raise ValueError(f"Maximum 10 files per batch read. Got {len(paths)}.")
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate paths are not allowed in a single batch read.")
        if max_lines is not None and max_lines < 1:
            raise ValueError("max_lines must be a positive integer.")

        results = []
        for path in paths:
            try:
                content = filesystem.read_file(path)
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                truncated = False
                if max_lines is not None:
                    lines = content.splitlines(keepends=True)
                    if len(lines) > max_lines:
                        content = "".join(lines[:max_lines])
                        truncated = True
                results.append({
                    "path": path, "content": content, "sha": sha,
                    "truncated": truncated, "error": None,
                })
            except (FileNotFoundError, InvalidPathError) as exc:
                results.append({
                    "path": path, "content": None, "sha": None,
                    "truncated": False, "error": str(exc),
                })
        return {"results": results}

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List files and directories",
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def list_content(
        path: str = "",
        recursive: bool = False,
    ) -> str:
        """List files and directories in the content store.

        Args:
            path: Path relative to content root (defaults to root)
            recursive: If true, list all files recursively
        Returns:
            A formatted string listing the files and directories
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

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Inspect content structure",
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def inspect_content_structure(
        path: str,
    ) -> dict:
        """Read a markdown file and return its document structure based on headings.

        Parses the heading hierarchy (h1-h6) and returns a nested outline of
        the document. Useful for understanding document organization before
        reading full content.

        Args:
            path: File path relative to content root (must be a .md or .markdown file)
        Returns:
            A dict with 'path', 'title' (first h1 if present), and 'sections'
            (nested list of heading entries)
        """
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in {".md", ".markdown"}:
            raise ValueError(
                f"inspect_content_structure only supports markdown files (.md, .markdown). Got: {path}"
            )
        content = filesystem.read_file(path)
        sections = parse_markdown_structure(content)
        title = None
        for heading in sections:
            if heading["level"] == 1:
                title = heading["heading"]
                break
        return {"path": path, "title": title, "sections": sections}

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Inspect content structure (batch)",
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def inspect_content_structure_batch(
        paths: list[str],
    ) -> dict:
        """Return the heading structure of multiple markdown files.

        Parses up to 10 markdown files and returns their heading hierarchies.
        Useful for scanning a documentation tree to understand content organization
        across multiple files.

        Args:
            paths: List of markdown file paths relative to content root (max 10)
        Returns:
            A dict with 'results' list, each containing the path, title, sections,
            and error (null on success)
        """
        if len(paths) == 0:
            raise ValueError("At least one path is required.")
        if len(paths) > 10:
            raise ValueError(f"Maximum 10 files per batch. Got {len(paths)}.")
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate paths are not allowed in a single batch call.")

        results = []
        for path in paths:
            try:
                suffix = PurePosixPath(path).suffix.lower()
                if suffix not in (".md", ".markdown"):
                    raise ValueError(
                        f"inspect_content_structure only supports markdown files "
                        f"(.md, .markdown). Got: {path}"
                    )
                content = filesystem.read_file(path)
                sections = parse_markdown_structure(content)
                title = None
                for s in sections:
                    if s["level"] == 1:
                        title = s["heading"]
                        break
                results.append({
                    "path": path,
                    "title": title,
                    "sections": sections,
                    "error": None,
                })
            except (FileNotFoundError, InvalidPathError, ValueError) as exc:
                results.append({
                    "path": path,
                    "title": None,
                    "sections": None,
                    "error": str(exc),
                })
        return {"results": results}

    if not Config.READ_ONLY:

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Move or rename file",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def move_content(
            source_path: str,
            dest_path: str,
            ctx: Context,
        ) -> str:
            """Move or rename a content file.

            Args:
                source_path: Current file path relative to content root
                dest_path: New file path relative to content root
            Returns:
                Confirmation message
            """
            filesystem.move_file(source_path, dest_path)
            source_was_resource = _unregister_resource(source_path)
            dest_is_resource = _register_resource(dest_path)
            if source_was_resource or dest_is_resource:
                await ctx.send_resource_list_changed()
            emit(CONTENT_MOVED, dest_path, source_path=source_path)
            logger.info(f"Moved: {source_path} -> {dest_path}")
            return f"Moved: {source_path} -> {dest_path}"

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Move content directory",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def move_content_directory(
            source_path: str,
            dest_path: str,
            ctx: Context,
        ) -> dict:
            """Move or rename an entire directory tree.

            Moves all files and subdirectories from source_path to dest_path.
            The destination must not already exist.

            Args:
                source_path: Current directory path relative to content root
                dest_path: New directory path relative to content root
            Returns:
                A dict with 'source', 'destination', and 'files_moved' count
            """
            moved_files = filesystem.move_directory(source_path, dest_path)

            # Handle resource registration changes for any README.md files
            resources_changed = False
            for old_path, new_path in moved_files:
                if _unregister_resource(old_path):
                    resources_changed = True
                if _register_resource(new_path):
                    resources_changed = True
                emit(CONTENT_MOVED, new_path, source_path=old_path)

            if resources_changed:
                await ctx.send_resource_list_changed()

            logger.info(f"Moved directory: {source_path} -> {dest_path} ({len(moved_files)} files)")
            return {
                "source": source_path,
                "destination": dest_path,
                "files_moved": len(moved_files),
            }

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Move multiple files",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def move_content_batch(
            moves: list[MoveOperation],
            ctx: Context,
        ) -> dict:
            """Move or rename multiple files in a single operation.

            All validations run before any moves — if any move fails validation
            the entire operation is aborted and no files are moved.

            Args:
                moves: List of move operations (max 10), each with source_path and dest_path
            Returns:
                A dict with 'results' list containing source, destination, and status per file
            """
            if len(moves) == 0:
                raise ValueError("At least one move operation is required.")
            if len(moves) > 10:
                raise ValueError(f"Maximum 10 moves per batch. Got {len(moves)}.")

            sources = [m.source_path for m in moves]
            if len(sources) != len(set(sources)):
                raise ValueError("Duplicate source paths are not allowed in a single batch move.")

            dests = [m.dest_path for m in moves]
            if len(dests) != len(set(dests)):
                raise ValueError(
                    "Duplicate destination paths are not allowed in a single batch move."
                )

            source_set = set(sources)
            dest_set = set(dests)
            overlap = source_set & dest_set
            if overlap:
                raise ValueError(
                    f"Paths cannot appear as both source and destination: {overlap}. "
                    "Use intermediate paths for swap operations."
                )

            for m in moves:
                if not filesystem.file_exists(m.source_path):
                    raise ValueError(f"Source file not found: {m.source_path}")
                dst = filesystem._resolve_path(m.dest_path)
                if dst.exists():
                    raise ValueError(f"Destination already exists: {m.dest_path}")

            results = []
            resources_changed = False

            for m in moves:
                filesystem.move_file(m.source_path, m.dest_path)
                if _unregister_resource(m.source_path):
                    resources_changed = True
                if _register_resource(m.dest_path):
                    resources_changed = True
                emit(CONTENT_MOVED, m.dest_path, source_path=m.source_path)
                logger.info(f"Moved: {m.source_path} -> {m.dest_path}")
                results.append({
                    "source": m.source_path,
                    "destination": m.dest_path,
                    "result": "ok",
                })

            if resources_changed:
                await ctx.send_resource_list_changed()

            return {"results": results}

    # --- Search tool (conditional) ---

    if search_engine is not None:

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Search content",
                readOnlyHint=True,
                openWorldHint=False,
            )
        )
        async def search_content(
            query: str,
            max_results: int = 5,
            file_types: str | None = None,
        ) -> str:
            """Search for content by meaning using semantic similarity.

            Args:
                query: Natural language search query
                max_results: Maximum number of results (default 5)
                file_types: Optional comma-separated file extensions
                    (e.g. ".md,.py")
            Returns:
                Search results formatted as a string
            """
            types_list = None
            if file_types:
                types_list = [
                    t.strip() for t in file_types.split(",") if t.strip()
                ]

            t0 = time.perf_counter()
            results = await search_engine.search(
                query, max_results=max_results, file_types=types_list
            )
            get_metrics().record_search_query(
                query=query,
                provider=Config.SEARCH_EMBEDDER_MODEL,
                result_count=len(results),
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

            if not results:
                return "No results found."

            lines = []
            for r in results:
                lines.append(f"📄 {r.file_path} (score: {r.score:.2f})")
                if r.context:
                    lines.append(f"   Context: {r.context}")
                if r.last_changed_at:
                    lines.append(f"   Last changed: {r.last_changed_at} by {r.changed_by}")
                if r.commit_message:
                    lines.append(f"   Commit: {r.commit_message}")
                snippet = r.content[:200]
                if len(r.content) > 200:
                    snippet += "..."
                lines.append(f"   {snippet}")
                lines.append("")
            return "\n".join(lines)

    # --- Git tools (registered only when GIT_TRACKING is enabled) ---

    if git_backend is not None:

        @mcp.tool(
            annotations=ToolAnnotations(
                title="Log file history",
                readOnlyHint=True,
                openWorldHint=False,
            )
        )
        async def log_content(
            path: str,
            max_count: int = 20,
        ) -> str:
            """Return recent git commits touching a file.

            Args:
                path: File path relative to content root
                max_count: Maximum number of commits to return (default 20)
            Returns:
                Commit history formatted as a string
            """
            import asyncio

            entries = await asyncio.to_thread(git_backend.log, path, max_count)
            if not entries:
                return f"No git history found for '{path}'."
            lines = []
            for e in entries:
                lines.append(
                    f"{e.commit_hash[:8]}  {e.timestamp.isoformat()}  {e.author}  {e.message}"
                )
            return "\n".join(lines)

        @mcp.tool(
            annotations=ToolAnnotations(
                title="View file changes",
                readOnlyHint=True,
                openWorldHint=False,
            )
        )
        async def diff_content(
            path: str,
            ref: str | None = None,
        ) -> str:
            """Show what changed in a file since a given git ref.

            Args:
                path: File path relative to content root
                ref: Git ref to diff against (default: HEAD~1)
            Returns:
                Unified diff as a string
            """
            import asyncio

            return await asyncio.to_thread(git_backend.diff, path, ref)

        @mcp.tool(
            annotations=ToolAnnotations(
                title="View file blame",
                readOnlyHint=True,
                openWorldHint=False,
            )
        )
        async def blame_content(
            path: str,
            start_line: int | None = None,
            end_line: int | None = None,
        ) -> str:
            """Return line-level authorship and timestamps for a file.

            Args:
                path: File path relative to content root
                start_line: Optional 1-based start line
                end_line: Optional 1-based end line
            Returns:
                Blame information formatted as a string
            """
            import asyncio

            blame_lines = await asyncio.to_thread(
                git_backend.blame, path, start_line, end_line
            )
            if not blame_lines:
                return f"No blame data available for '{path}'."
            lines = []
            for bl in blame_lines:
                lines.append(
                    f"{bl.line_number:4d}  {bl.commit_hash[:8]}  "
                    f"{bl.timestamp.isoformat()}  {bl.author}  {bl.content}"
                )
            return "\n".join(lines)

    # --- Transaction tools (only when write mode + git tracking are both active) ---

    if not Config.READ_ONLY and git_backend is not None:
        from .transactions import TransactionError, TransactionManager

        tm = filesystem if isinstance(filesystem, TransactionManager) else None

        if tm is not None:

            @mcp.tool(
                annotations=ToolAnnotations(
                    title="Start transaction",
                    readOnlyHint=False,
                    destructiveHint=False,
                    openWorldHint=False,
                )
            )
            async def start_content_transaction(ctx: Context) -> str:
                """Begin a write transaction and return its UUID.

                Acquires the global transaction lock.  All subsequent mutating
                tool calls (create_content, overwrite_content, edit_content,
                edit_content_batch, delete_content, move_content) on this
                session will be part of the transaction.  Call
                commit_content_transaction to commit or abort_content_transaction
                to discard.

                Returns:
                    Transaction UUID string
                """
                session_id = str(id(ctx.session))
                try:
                    txn_id = await tm.start_transaction(
                        session_id,
                        Config.TRANSACTION_TIMEOUT,
                        Config.TRANSACTION_LOCK_WAIT,
                    )
                except TransactionError as exc:
                    raise ValueError(str(exc))
                return txn_id

            @mcp.tool(
                annotations=ToolAnnotations(
                    title="Commit transaction",
                    readOnlyHint=False,
                    destructiveHint=False,
                    openWorldHint=False,
                )
            )
            async def commit_content_transaction(
                message: str,
                ctx: Context,
                author: str | None = None,
            ) -> str:
                """Commit all changes in the active transaction.

                Runs ``git add -A && git commit -m <message>`` and, when
                GIT_SYNC_ENABLED is true, pushes to the configured remote.
                Releases the transaction lock so other sessions may proceed.

                Args:
                    message: Commit message describing the changes
                    author: Optional commit author in ``"Name <email>"`` format.
                        Defaults to the repository's configured identity.
                Returns:
                    Confirmation string
                """
                session_id = str(id(ctx.session))
                sync_remote = Config.GIT_SYNC_REMOTE if Config.GIT_SYNC_ENABLED else None
                sync_branch = Config.GIT_SYNC_BRANCH if Config.GIT_SYNC_ENABLED else None
                try:
                    await tm.end_transaction(
                        session_id, message, author, sync_remote, sync_branch
                    )
                except TransactionError as exc:
                    raise ValueError(str(exc))
                return f"Transaction committed: {message}"

            @mcp.tool(
                annotations=ToolAnnotations(
                    title="Abort transaction",
                    readOnlyHint=False,
                    destructiveHint=True,
                    idempotentHint=True,
                    openWorldHint=False,
                )
            )
            async def abort_content_transaction(ctx: Context) -> str:
                """Abort the active transaction and discard all uncommitted changes.

                Runs ``git reset --hard HEAD``, resumes git sync, and releases
                the transaction lock.

                Returns:
                    Confirmation string
                """
                session_id = str(id(ctx.session))
                try:
                    await tm.abort_transaction(session_id)
                except TransactionError as exc:
                    raise ValueError(str(exc))
                return "Transaction aborted."

            @mcp.tool(
                annotations=ToolAnnotations(
                    title="List transactions",
                    readOnlyHint=True,
                    openWorldHint=False,
                )
            )
            async def list_content_transactions(ctx: Context) -> dict:
                """List active content transactions.

                Returns the current transaction state including whether a
                transaction is active, its ID, which session owns it, and
                whether this session is the owner.  Useful for agent
                retry/recovery scenarios where the agent needs to know if a
                transaction is still open before attempting to start a new one.

                Returns:
                    A dict with 'has_active_transaction' (bool) and optional
                    transaction details.
                """
                session_id = str(id(ctx.session))
                return tm.get_transaction_status(session_id)

    return mcp
