"""MCP Server implementation for Stash using FastMCP."""

import asyncio
import functools
import hashlib
import inspect
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.resources import FunctionResource
from fastmcp.server.context import Context
from mcp.types import ToolAnnotations
from pydantic import AnyUrl, BaseModel, Field

from .config import Config
from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_MOVED, CONTENT_UPDATED, emit
from .filesystem import FileNotFoundError, FileSystem, InvalidPathError
from .metrics import get_metrics
from .transactions import TransactionError, TransactionManager

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
    sha: str = Field(
        description="SHA-256 hex digest of the file's current full content, from read_content"
    )
    edits: list[EditOperation] = Field(description="Ordered list of edits to apply")


class MoveOperation(BaseModel):
    """A single file move operation."""

    source_path: str = Field(description="Current file path relative to content root")
    dest_path: str = Field(
        description="New file path relative to content root; must not already exist"
    )


# Shared parameter annotations so every tool's JSON schema carries
# per-parameter descriptions (clients surface these to agents).
ContentPath = Annotated[
    str,
    Field(description="File path relative to content root (POSIX-style, no leading slash)"),
]
FileSha = Annotated[
    str,
    Field(
        description="SHA-256 hex digest of the file's current full content, "
        "as returned by read_content"
    ),
]
MaxLines = Annotated[
    int | None,
    Field(
        ge=1,
        description="Maximum number of lines to return from the beginning of the "
        "file. Omit to return the full content — there is no offset parameter",
    ),
]

# Appended to write-tool descriptions when writes are transaction-gated.
_TXN_NOTE = (
    "\n\nNote: this server gates writes behind transactions. Call "
    "start_content_transaction before using this tool, then "
    "commit_content_transaction to persist the changes."
)


def _build_instructions(
    *,
    read_only: bool,
    search_enabled: bool,
    git_enabled: bool,
    transactions_active: bool,
) -> str:
    """Assemble the server-level instructions string sent to MCP clients."""
    parts = [
        "Stash is a file-backed document store. All paths are POSIX-style and "
        "relative to the content root, with no leading slash (e.g. 'docs/guide.md'). "
        "Start with list_content(recursive=true) to discover files."
    ]
    if read_only:
        parts.append(
            "This server is read-only: content can be listed and read but not modified."
        )
    else:
        parts.append(
            "Writing a file creates missing parent directories automatically; there "
            "is no separate mkdir step. To modify a file, call read_content first to "
            "get its sha, then edit_content (targeted string replacement, preferred "
            "for small changes) or overwrite_content (full replace). create_content "
            "is only for files that do not exist yet; delete_content also requires "
            "the sha."
        )
    if transactions_active:
        parts.append(
            "Writes are gated behind transactions: call start_content_transaction "
            "before any create/edit/overwrite/move/delete, make the changes, then "
            "commit_content_transaction with a commit message to persist them (or "
            "abort_content_transaction to discard). Idle transactions are "
            "auto-aborted after a timeout."
        )
    if search_enabled:
        parts.append(
            "search_content finds content by meaning and returns ranked snippets; "
            "follow up with read_content to retrieve full files."
        )
    if git_enabled:
        parts.append(
            "log_content, diff_content, and blame_content expose the git history "
            "of any file."
        )
    return "\n\n".join(parts)


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
    ".tsv": "text/tab-separated-values",
    ".toml": "application/toml",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".rst": "text/x-rst",
    ".log": "text/plain",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".bmp": "image/bmp",
    ".mmd": "text/x-mermaid",
    ".mermaid": "text/x-mermaid",
    ".gantt": "text/x-gantt",
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

    transactions_active = (
        not Config.READ_ONLY
        and git_backend is not None
        and isinstance(filesystem, TransactionManager)
    )

    mcp = FastMCP(
        name=Config.SERVER_NAME,
        version=Config.SERVER_VERSION,
        lifespan=lifespan,
        instructions=_build_instructions(
            read_only=Config.READ_ONLY,
            search_enabled=search_engine is not None,
            git_enabled=git_backend is not None,
            transactions_active=transactions_active,
        ),
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

    def _write_tool(**tool_kwargs):
        """mcp.tool wrapper for mutating tools.

        When writes are transaction-gated, appends a note to the tool
        description so agents learn the requirement up front instead of
        from a failed first call.
        """

        def decorate(fn):
            if transactions_active:
                fn.__doc__ = inspect.cleandoc(fn.__doc__ or "") + _TXN_NOTE
            return mcp.tool(**tool_kwargs)(fn)

        return decorate

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

        @_write_tool(
            annotations=ToolAnnotations(
                title="Create file",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def create_content(
            path: ContentPath,
            content: Annotated[str, Field(description="File content (UTF-8 text)")],
            ctx: Context,
        ) -> str:
            """
            Create a new file. Errors if the file already exists.

            Missing parent directories are created automatically — writing a
            file is also the only way to create a directory.

            Args:
                path: File path relative to content root
                content: File content
            """
            if filesystem.file_exists(path):
                raise ValueError(
                    f"File already exists: {path}. Use overwrite_content to replace "
                    "it or edit_content for targeted edits."
                )
            filesystem.write_file(path, content)
            if _register_resource(path):
                await ctx.send_resource_list_changed()
            emit(CONTENT_CREATED, path)
            logger.info(f"Created: {path}")
            return f"Created: {path}"

        @_write_tool(
            annotations=ToolAnnotations(
                title="Overwrite file content",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            )
        )
        async def overwrite_content(
            path: ContentPath,
            content: Annotated[
                str, Field(description="New full file content (replaces everything)")
            ],
            sha: FileSha,
            ctx: Context,
        ) -> str:
            """
            Replace the full content of an existing file.

            The file must already exist (use create_content for new files).
            For small changes prefer edit_content, which replaces exact
            strings instead of the whole file.

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

        @_write_tool(
            annotations=ToolAnnotations(
                title="Edit file",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            )
        )
        async def edit_content(
            file_path: ContentPath,
            sha: FileSha,
            edits: Annotated[
                list[EditOperation],
                Field(min_length=1, description="Ordered list of edits to apply"),
            ],
            ctx: Context,
        ) -> dict:
            """
            Apply targeted string-replacement edits to an existing file.

            Each edit replaces an exact occurrence of old_string with new_string.
            Edits are applied sequentially — later edits see the result of earlier
            ones. All edits are validated in memory and the file is written once;
            if any edit fails, nothing is written.

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

        @_write_tool(
            annotations=ToolAnnotations(
                title="Edit multiple files",
                readOnlyHint=False,
                destructiveHint=False,
                idempotentHint=True,
                openWorldHint=False,
            )
        )
        async def edit_content_batch(
            edit_operations: Annotated[
                list[FileEditOperation],
                Field(
                    min_length=1,
                    max_length=10,
                    description="Per-file edit operations (max 10 files, no duplicates)",
                ),
            ],
            ctx: Context,
        ) -> dict:
            """
            Atomically apply edits to multiple files (max 10 per call).

            All validations run before any writes — if any file fails validation
            the entire operation is aborted and no files are modified.

            Args:
                edit_operations: List of per-file edit operations (max 10)
            Returns:
                A dict with a results list containing path, result status, and new_sha per file
            """
            if len(edit_operations) == 0:
                raise ValueError("At least one edit operation is required.")
            if len(edit_operations) > 10:
                raise ValueError(
                    f"Maximum 10 files per batch edit. Got {len(edit_operations)}."
                )
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

        @_write_tool(
            annotations=ToolAnnotations(
                title="Delete file",
                readOnlyHint=False,
                destructiveHint=True,
                openWorldHint=False,
            )
        )
        async def delete_content(
            path: ContentPath,
            sha: FileSha,
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
        path: ContentPath,
        max_lines: MaxLines = None,
    ) -> dict:
        """
        Read and return the contents of a file along with its SHA-256 hash.
        The sha is required by overwrite_content, edit_content, and
        delete_content to ensure the file has not changed since it was read.

        Args:
            path: File path relative to content root
            max_lines: Optional maximum number of lines to return from the
                beginning of the file. If omitted, returns the full file.
                There is no offset parameter — to read past the truncation
                point, call again without max_lines.
        Returns:
            A dict with 'content' (file text), 'sha' (SHA-256 hex digest of
            the FULL file, even when truncated), 'truncated' (bool), and
            'total_lines' (line count of the full file)
        """
        content = await asyncio.to_thread(filesystem.read_file, path)
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        truncated = False
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        if max_lines is not None:
            if max_lines < 1:
                raise ValueError("max_lines must be a positive integer.")
            if total_lines > max_lines:
                content = "".join(lines[:max_lines])
                truncated = True
        return {
            "content": content,
            "sha": sha,
            "truncated": truncated,
            "total_lines": total_lines,
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Read multiple files",
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    async def read_content_batch(
        paths: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=10,
                description="File paths relative to content root (max 10, no duplicates)",
            ),
        ],
        max_lines: MaxLines = None,
    ) -> dict:
        """Read multiple files and return their contents with SHA-256 hashes.

        Reads up to 10 files in a single call. Each file's sha is required
        by overwrite_content, edit_content, and delete_content.

        Args:
            paths: List of file paths relative to content root (max 10)
            max_lines: Optional maximum number of lines to return from the
                beginning of each file. If omitted, returns full content.
        Returns:
            A dict with 'results' list, each containing 'path', 'content',
            'sha', 'truncated', 'total_lines', and 'error' (null on success;
            per-file failures set 'error' without failing the whole call)
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
                content = await asyncio.to_thread(filesystem.read_file, path)
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                truncated = False
                lines = content.splitlines(keepends=True)
                total_lines = len(lines)
                if max_lines is not None and total_lines > max_lines:
                    content = "".join(lines[:max_lines])
                    truncated = True
                results.append({
                    "path": path, "content": content, "sha": sha,
                    "truncated": truncated, "total_lines": total_lines,
                    "error": None,
                })
            except (FileNotFoundError, InvalidPathError) as exc:
                results.append({
                    "path": path, "content": None, "sha": None,
                    "truncated": False, "total_lines": None,
                    "error": str(exc),
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
        path: Annotated[
            str,
            Field(description="Directory path relative to content root; empty string is the root"),
        ] = "",
        recursive: Annotated[
            bool,
            Field(description="If true, list every file under path as full relative paths"),
        ] = False,
    ) -> str:
        """List files and directories in the content store.

        Non-recursive listings show one entry per line with a 📁 prefix for
        directories and 📄 for files; entries are names only, so join them
        with *path* to build full paths. Recursive listings return full
        relative file paths, one per line, with no prefixes. Hidden files
        (dotfiles) are excluded.

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
        path: Annotated[
            str,
            Field(description="Markdown file path (.md or .markdown) relative to content root"),
        ],
    ) -> dict:
        """Read a markdown file and return its document structure based on headings.

        Parses the heading hierarchy (h1-h6) and returns a nested outline of
        the document. Useful for understanding document organization before
        reading full content.

        Args:
            path: File path relative to content root (must be a .md or .markdown file)
        Returns:
            A dict with 'path', 'title' (first h1 if present), and 'sections'
            (nested list of {heading, level, line_number, children} entries)
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
        paths: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=10,
                description="Markdown file paths (.md or .markdown) relative to "
                "content root (max 10, no duplicates)",
            ),
        ],
    ) -> dict:
        """Return the heading structure of multiple markdown files.

        Parses up to 10 markdown files and returns their heading hierarchies.
        Useful for scanning a documentation tree to understand content organization
        across multiple files.

        Args:
            paths: List of markdown file paths relative to content root (max 10)
        Returns:
            A dict with 'results' list, each containing the path, title, sections
            (nested {heading, level, line_number, children} entries), and error
            (null on success; per-file failures set 'error' without failing
            the whole call)
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

        @_write_tool(
            annotations=ToolAnnotations(
                title="Move or rename file",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def move_content(
            source_path: Annotated[
                str, Field(description="Current file path relative to content root")
            ],
            dest_path: Annotated[
                str,
                Field(
                    description="New file path relative to content root; "
                    "must not already exist"
                ),
            ],
            ctx: Context,
        ) -> str:
            """Move or rename a content file.

            The destination must not already exist (files are never
            overwritten by a move); missing parent directories are created
            automatically. Use move_content_directory for whole directories.

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

        @_write_tool(
            annotations=ToolAnnotations(
                title="Move content directory",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def move_content_directory(
            source_path: Annotated[
                str, Field(description="Current directory path relative to content root")
            ],
            dest_path: Annotated[
                str,
                Field(
                    description="New directory path relative to content root; "
                    "must not already exist"
                ),
            ],
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

        @_write_tool(
            annotations=ToolAnnotations(
                title="Move multiple files",
                readOnlyHint=False,
                destructiveHint=False,
                openWorldHint=False,
            )
        )
        async def move_content_batch(
            moves: Annotated[
                list[MoveOperation],
                Field(
                    min_length=1,
                    max_length=10,
                    description="Move operations (max 10); no duplicate sources or "
                    "destinations, and no path may be both",
                ),
            ],
            ctx: Context,
        ) -> dict:
            """Move or rename multiple files in a single operation.

            All validations run before any moves — if any move fails validation
            the entire operation is aborted and no files are moved. Destinations
            must not already exist.

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
            path: ContentPath,
            max_count: Annotated[
                int, Field(ge=1, description="Maximum number of commits to return")
            ] = 20,
        ) -> str:
            """Return recent git commits touching a file.

            Each line is: short hash, ISO timestamp, author, commit message.
            Uncommitted changes (e.g. writes in an open transaction) do not
            appear until committed.

            Args:
                path: File path relative to content root
                max_count: Maximum number of commits to return (default 20)
            Returns:
                Commit history formatted as a string, or a "No git history
                found" message for files with no commits
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
            path: ContentPath,
            ref: Annotated[
                str | None,
                Field(
                    description="Git ref to diff against (default HEAD~1). "
                    "Use 'HEAD' to see uncommitted changes"
                ),
            ] = None,
        ) -> str:
            """Show what changed in a file since a given git ref.

            Compares the file's current on-disk content (working tree)
            against *ref*. The default HEAD~1 shows changes since the
            previous commit; pass ref='HEAD' to see only uncommitted
            changes, such as pending edits in an open transaction.

            Args:
                path: File path relative to content root
                ref: Git ref to diff against (default: HEAD~1)
            Returns:
                Unified diff as a string; an empty string means no changes.
                Invalid refs return git's error text instead of a diff.
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
            path: ContentPath,
            start_line: Annotated[
                int | None,
                Field(
                    ge=1,
                    description="1-based start line (inclusive); requires end_line "
                    "to also be set, otherwise the whole file is blamed",
                ),
            ] = None,
            end_line: Annotated[
                int | None,
                Field(
                    ge=1,
                    description="1-based end line (inclusive); requires start_line "
                    "to also be set, otherwise the whole file is blamed",
                ),
            ] = None,
        ) -> str:
            """Return line-level authorship and timestamps for a file.

            The line range applies only when BOTH start_line and end_line are
            provided; if either is omitted, the entire file is blamed.

            Args:
                path: File path relative to content root
                start_line: Optional 1-based start line (requires end_line)
                end_line: Optional 1-based end line (requires start_line)
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
                edit_content_batch, delete_content, move_content,
                move_content_directory, move_content_batch) on this session
                will be part of the transaction.  Call
                commit_content_transaction to commit or abort_content_transaction
                to discard.  Only one transaction may be active at a time
                across all sessions; idle transactions are auto-aborted after
                a timeout.

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
                return (
                    f"Transaction started: {txn_id}\n\n"
                    "IMPORTANT: When you are finished making changes, call "
                    "`commit_content_transaction` to save them. If you want to "
                    "discard all changes, call `abort_content_transaction` instead."
                )

            @mcp.tool(
                annotations=ToolAnnotations(
                    title="Commit transaction",
                    readOnlyHint=False,
                    destructiveHint=False,
                    openWorldHint=False,
                )
            )
            async def commit_content_transaction(
                message: Annotated[
                    str,
                    Field(description="Git commit message describing the changes"),
                ],
                ctx: Context,
                author: Annotated[
                    str | None,
                    Field(
                        description='Optional commit author as "Name <email>"; '
                        "defaults to the repository's configured identity"
                    ),
                ] = None,
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
