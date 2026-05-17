"""REST API implementation with FastAPI."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Config
from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_MOVED, CONTENT_UPDATED, emit
from .filesystem import (
    FileNotFoundError,
    FileSystemError,
    InvalidPathError,
)
from .mcp_server import BINARY_EXTENSIONS, MIME_TYPES
from .metrics import get_metrics

logger = logging.getLogger(__name__)


USE_CURRENT_STORE: Any = object()
"""Sentinel passed to :func:`create_api` in auth mode — handlers then
resolve the filesystem from :func:`current_store` at request time
instead of closing over a single FS."""


def _get_mime_type(path: str) -> str:
    """Get mime type for a file path based on extension."""
    suffix = PurePosixPath(path).suffix.lower()
    return MIME_TYPES.get(suffix, "text/plain")


def _is_binary_path(path: str) -> bool:
    """Return True when this path's extension is known-binary (image, PDF, …).

    Binary files cannot be decoded as UTF-8, so the JSON ``/api/content``
    endpoint surfaces a 415 and clients are expected to fetch the bytes
    from ``/api/raw/{path}`` instead.
    """
    return PurePosixPath(path).suffix.lower() in BINARY_EXTENSIONS


class ContentItem(BaseModel):
    """Content item model."""

    path: str
    is_directory: bool
    content: str | None = None
    mime_type: str | None = None
    updated_at: str | None = None


class ContentCreate(BaseModel):
    """Content creation model."""

    content: str


class ContentMove(BaseModel):
    """Content move/rename model."""

    destination: str


class ContentList(BaseModel):
    """Content list response."""

    items: list[ContentItem]


class TreeNode(BaseModel):
    """Directory tree node."""

    name: str
    path: str
    type: str  # "file" or "directory"
    children: list["TreeNode"] | None = None


def create_api(
    filesystem_or_resolver,
    lifespan=None,
    search_engine=None,
    git_backend=None,
    git_overview_remote: str = "",
    git_overview_branch: str = "",
) -> FastAPI:
    """Create FastAPI application.

    Args:
        filesystem_or_resolver: Either a :class:`FileSystem` (legacy
            single-store mode) or the :data:`USE_CURRENT_STORE` sentinel
            (auth mode, where handlers resolve the FS from
            :func:`current_store` at request time).
        lifespan: Optional lifespan context manager for the app
        search_engine: Optional SearchEngine instance for semantic search
        git_backend: Optional GitBackend instance (legacy mode only)
        git_overview_remote: Git remote for overview comparison
        git_overview_branch: Git branch for overview comparison

    Returns:
        FastAPI application
    """
    app = FastAPI(
        title="Stash-MCP API",
        description="REST API for Stash content management",
        version=Config.SERVER_VERSION,
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _fs():
        """Resolve the FileSystem for the in-flight request.

        Returns the bare :class:`FileSystem` — REST writes are *not*
        wrapped in a transaction (MCP tools own that lifecycle). This
        matches legacy mode where ``main.py`` passes the bare filesystem
        directly to the API.
        """
        if filesystem_or_resolver is USE_CURRENT_STORE:
            from .routing.context import require_store

            return require_store().filesystem
        return filesystem_or_resolver

    def _bare_fs():
        """Same as :func:`_fs` — kept for symmetry with the
        path-resolution / stat helpers below."""
        return _fs()

    def _git_backend():
        """Resolve the git backend for the in-flight request, if any."""
        if filesystem_or_resolver is USE_CURRENT_STORE:
            from .routing.context import current_store

            store = current_store()
            return store.git_backend if store is not None else None
        return git_backend

    def _etag(path: str) -> str:
        """Compute the strong ETag for a content path."""
        gb = _git_backend()
        if gb is not None:
            return gb.hash_object(path)
        return _bare_fs().content_hash(path)

    def _quoted(etag: str) -> str:
        """Wrap a hex digest in quotes — strong ETag form."""
        return f'"{etag}"'

    def _if_match_matches(header: str | None, current_etag: str) -> bool:
        """Return True when an ``If-Match`` header includes *current_etag*.

        Comma-separated lists and ``*`` (any) are honoured.
        """
        if header is None:
            return True
        header = header.strip()
        if header == "*":
            return True
        quoted = _quoted(current_etag)
        for value in (v.strip() for v in header.split(",")):
            if value == quoted or value == current_etag:
                return True
        return False

    def _if_none_match_matches(header: str | None, current_etag: str) -> bool:
        """Return True when an ``If-None-Match`` header includes
        *current_etag* (so caller should get a 304)."""
        if header is None:
            return False
        header = header.strip()
        if header == "*":
            return True
        quoted = _quoted(current_etag)
        for value in (v.strip() for v in header.split(",")):
            if value == quoted or value == current_etag:
                return True
        return False

    @app.middleware("http")
    async def _metrics_middleware(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - t0) * 1000
        get_metrics().record_request(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    def _get_updated_at(relative_path: str) -> str | None:
        """Get file modification time as ISO string."""
        try:
            full_path = _bare_fs()._resolve_path(relative_path)
            if full_path.exists() and full_path.is_file():
                mtime = full_path.stat().st_mtime
                return datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        except Exception:
            pass
        return None

    def _build_tree(relative_path: str = "") -> TreeNode:
        """Build a recursive directory tree."""
        name = PurePosixPath(relative_path).name if relative_path else "root"
        node = TreeNode(name=name, path=relative_path, type="directory", children=[])
        fs = _fs()
        try:
            for item_name, is_dir in fs.list_files(relative_path):
                child_path = f"{relative_path}/{item_name}" if relative_path else item_name
                if is_dir:
                    node.children.append(_build_tree(child_path))
                else:
                    node.children.append(
                        TreeNode(name=item_name, path=child_path, type="file")
                    )
        except Exception:
            pass
        return node

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "name": "Stash-MCP API",
            "version": Config.SERVER_VERSION,
            "endpoints": {
                "list": "/api/content",
                "read": "/api/content/{path}",
                "create": "POST /api/content/{path}",
                "update": "PUT /api/content/{path}",
                "delete": "DELETE /api/content/{path}",
                "move": "PATCH /api/content/{path}",
                "tree": "/api/tree",
                "health": "/api/health",
            },
        }

    @app.get("/api/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": Config.SERVER_VERSION}

    @app.get("/api/tree", response_model=TreeNode)
    async def get_tree():
        """Get full directory tree for sidebar navigation."""
        return _build_tree()

    @app.get("/api/content", response_model=ContentList)
    async def list_content(
        path: str = "",
        recursive: bool = False,
        file_type: str | None = None,
    ):
        """List content at path.

        Args:
            path: Directory path to list (empty for root)
            recursive: If true, list all files recursively
            file_type: Filter by file extension (e.g. ".md", ".txt")
        """
        fs = _fs()
        try:
            items = []
            if recursive:
                for file_path in fs.list_all_files(path):
                    if file_type and not file_path.endswith(file_type):
                        continue
                    items.append(
                        ContentItem(
                            path=file_path,
                            is_directory=False,
                            mime_type=_get_mime_type(file_path),
                            updated_at=_get_updated_at(file_path),
                        )
                    )
            else:
                for name, is_dir in fs.list_files(path):
                    item_path = f"{path}/{name}" if path else name
                    if file_type and not is_dir and not name.endswith(file_type):
                        continue
                    items.append(
                        ContentItem(
                            path=item_path,
                            is_directory=is_dir,
                            mime_type=_get_mime_type(item_path) if not is_dir else None,
                            updated_at=_get_updated_at(item_path) if not is_dir else None,
                        )
                    )

            return ContentList(items=items)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Path not found")
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error listing content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.get("/api/content/{path:path}")
    async def read_content(path: str, request: Request, response: Response):
        """Read content file. Returns 304 when ``If-None-Match`` matches.

        Binary file types (images, PDFs) return 415 — clients should
        fetch them from :http:get:`/api/raw/{path}` instead.
        """
        if _is_binary_path(path):
            raise HTTPException(
                status_code=415,
                detail=(
                    f"File '{path}' is binary; fetch raw bytes from "
                    f"/api/raw/{path}"
                ),
            )
        fs = _fs()
        try:
            content = fs.read_file(path)
            etag = _etag(path)
            quoted = _quoted(etag)
            if _if_none_match_matches(request.headers.get("if-none-match"), etag):
                return Response(status_code=304, headers={"ETag": quoted})
            response.headers["ETag"] = quoted
            item = ContentItem(
                path=path,
                is_directory=False,
                content=content,
                mime_type=_get_mime_type(path),
                updated_at=_get_updated_at(path),
            )
            return item
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"File '{path}' is not UTF-8 text; fetch raw bytes "
                    f"from /api/raw/{path}"
                ),
            )
        except Exception as e:
            logger.error(f"Error reading content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.get("/api/raw/{path:path}")
    async def read_raw(path: str, request: Request):
        """Stream raw file bytes with the correct ``Content-Type``.

        Used by the UI to render images, PDFs, and HTML artifacts that
        the JSON content endpoint cannot represent. Honours
        ``If-None-Match`` so the browser can cache aggressively.
        """
        fs = _fs()
        try:
            full_path = fs._resolve_path(path)
            if not full_path.exists():
                raise HTTPException(status_code=404, detail="File not found")
            if not full_path.is_file():
                raise HTTPException(status_code=400, detail="Path is not a file")
            etag = _etag(path)
            quoted = _quoted(etag)
            if _if_none_match_matches(request.headers.get("if-none-match"), etag):
                return Response(status_code=304, headers={"ETag": quoted})
            return FileResponse(
                full_path,
                media_type=_get_mime_type(path),
                headers={"ETag": quoted},
            )
        except HTTPException:
            raise
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except Exception as e:
            logger.error(f"Error reading raw content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post("/api/content/{path:path}", status_code=201)
    async def create_content(path: str, data: ContentCreate, response: Response):
        """Create a new content file. Returns 409 if file already exists."""
        fs = _fs()
        try:
            if fs.file_exists(path):
                raise HTTPException(
                    status_code=409,
                    detail=f"File '{path}' already exists. Use PUT to update.",
                )
            fs.write_file(path, data.content)
            emit(CONTENT_CREATED, path)
            try:
                response.headers["ETag"] = _quoted(_etag(path))
            except Exception:
                pass
            return {"message": f"File '{path}' created successfully", "path": path}
        except HTTPException:
            raise
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error creating content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.put("/api/content/{path:path}")
    async def update_content(
        path: str,
        data: ContentCreate,
        request: Request,
        response: Response,
    ):
        """Update an existing content file (also allows creation).

        Honours ``If-Match`` for optimistic concurrency: 412 when the
        precondition fails.
        """
        fs = _fs()
        try:
            if_match = request.headers.get("if-match")
            exists = fs.file_exists(path)
            if if_match is not None:
                if not exists:
                    # No current representation to match against.
                    raise HTTPException(
                        status_code=412, detail="File does not exist"
                    )
                current_etag = _etag(path)
                if not _if_match_matches(if_match, current_etag):
                    return Response(
                        status_code=412,
                        content=(
                            '{"detail":"ETag mismatch","current_etag":"'
                            + current_etag
                            + '"}'
                        ),
                        media_type="application/json",
                        headers={"ETag": _quoted(current_etag)},
                    )
            is_new = not exists
            fs.write_file(path, data.content)
            emit(CONTENT_CREATED if is_new else CONTENT_UPDATED, path)
            try:
                response.headers["ETag"] = _quoted(_etag(path))
            except Exception:
                pass
            return {"message": f"File '{path}' saved successfully", "path": path}
        except HTTPException:
            raise
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error writing content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.delete("/api/content/{path:path}")
    async def delete_content(path: str):
        """Delete content file."""
        fs = _fs()
        try:
            fs.delete_file(path)
            emit(CONTENT_DELETED, path)
            return {"message": f"File '{path}' deleted successfully", "path": path}
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error deleting content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.patch("/api/content/{path:path}")
    async def move_content(path: str, data: ContentMove):
        """Move or rename a content file."""
        fs = _fs()
        try:
            fs.move_file(path, data.destination)
            emit(CONTENT_MOVED, data.destination, source_path=path)
            return {
                "message": f"File moved from '{path}' to '{data.destination}'",
                "source": path,
                "destination": data.destination,
            }
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Source file not found")
        except FileSystemError as e:
            if "already exists" in str(e):
                raise HTTPException(status_code=409, detail=str(e))
            raise HTTPException(status_code=400, detail=str(e))
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error moving content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    # --- Git endpoints (only when git backend is available in legacy mode) ---

    if git_backend is not None:

        @app.get("/api/git/overview")
        async def git_overview(max_commits: int = 20):
            """Get git commit history overview."""
            return await asyncio.to_thread(
                git_backend.overview,
                max_commits,
                git_overview_remote,
                git_overview_branch,
            )

    # --- Search endpoints (only when search engine is available) ---

    if search_engine is not None:

        @app.get("/api/search")
        async def search_content(
            q: str,
            max_results: int = 5,
            file_types: str | None = None,
        ):
            """Semantic search across stashed content.

            Args:
                q: Search query.
                max_results: Maximum number of results (default 5).
                file_types: Comma-separated file extensions (e.g. ".md,.py").
            """
            types_list = None
            if file_types:
                types_list = [t.strip() for t in file_types.split(",") if t.strip()]

            results = await search_engine.search(
                q, max_results=max_results, file_types=types_list
            )
            return {
                "query": q,
                "results": [
                    {
                        "file_path": r.file_path,
                        "chunk_index": r.chunk_index,
                        "content": r.content,
                        "context": r.context,
                        "score": r.score,
                    }
                    for r in results
                ],
                "total": len(results),
            }

        @app.get("/api/search/status")
        async def search_status():
            """Get search engine status."""
            return {
                "enabled": True,
                "ready": search_engine.ready,
                "indexing": search_engine.indexing,
                "contextual_retrieval": search_engine.contextual_retrieval,
                "embedder_model": search_engine.embedder_model,
                "indexed_files": search_engine.indexed_files,
                "indexed_chunks": search_engine.indexed_chunks,
            }

        @app.post("/api/search/reindex")
        async def reindex():
            """Trigger a full reindex (non-blocking)."""
            asyncio.create_task(search_engine.reindex())
            return {
                "message": "Reindex started",
                "status": "in_progress",
            }

    return app
