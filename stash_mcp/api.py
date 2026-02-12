"""REST API implementation with FastAPI."""

import logging
from datetime import UTC, datetime
from pathlib import PurePosixPath

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import Config
from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_MOVED, CONTENT_UPDATED, emit
from .filesystem import (
    FileNotFoundError,
    FileSystem,
    FileSystemError,
    InvalidPathError,
)
from .mcp_server import MIME_TYPES

logger = logging.getLogger(__name__)


def _get_mime_type(path: str) -> str:
    """Get mime type for a file path based on extension."""
    suffix = PurePosixPath(path).suffix.lower()
    return MIME_TYPES.get(suffix, "text/plain")


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


def create_api(filesystem: FileSystem, lifespan=None, search_engine=None) -> FastAPI:
    """Create FastAPI application.

    Args:
        filesystem: Filesystem instance
        lifespan: Optional lifespan context manager for the app
        search_engine: Optional SearchEngine instance for semantic search

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

    def _get_updated_at(relative_path: str) -> str | None:
        """Get file modification time as ISO string."""
        try:
            full_path = filesystem._resolve_path(relative_path)
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
        try:
            for item_name, is_dir in filesystem.list_files(relative_path):
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
        try:
            items = []
            if recursive:
                # List all files recursively
                for file_path in filesystem.list_all_files(path):
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
                # List directory contents (shallow)
                for name, is_dir in filesystem.list_files(path):
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

    @app.get("/api/content/{path:path}", response_model=ContentItem)
    async def read_content(path: str):
        """Read content file."""
        try:
            content = filesystem.read_file(path)
            return ContentItem(
                path=path,
                is_directory=False,
                content=content,
                mime_type=_get_mime_type(path),
                updated_at=_get_updated_at(path),
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error reading content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.post("/api/content/{path:path}", status_code=201)
    async def create_content(path: str, data: ContentCreate):
        """Create a new content file. Returns 409 if file already exists."""
        try:
            if filesystem.file_exists(path):
                raise HTTPException(
                    status_code=409,
                    detail=f"File '{path}' already exists. Use PUT to update.",
                )
            filesystem.write_file(path, data.content)
            emit(CONTENT_CREATED, path)
            return {"message": f"File '{path}' created successfully", "path": path}
        except HTTPException:
            raise
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error creating content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.put("/api/content/{path:path}")
    async def update_content(path: str, data: ContentCreate):
        """Update an existing content file (also allows creation)."""
        try:
            is_new = not filesystem.file_exists(path)
            filesystem.write_file(path, data.content)
            emit(CONTENT_CREATED if is_new else CONTENT_UPDATED, path)
            return {"message": f"File '{path}' saved successfully", "path": path}
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error writing content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.delete("/api/content/{path:path}")
    async def delete_content(path: str):
        """Delete content file."""
        try:
            filesystem.delete_file(path)
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
        try:
            filesystem.move_file(path, data.destination)
            emit(CONTENT_MOVED, path, destination=data.destination)
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
                "contextual_retrieval": search_engine.contextual_retrieval,
                "embedder_model": search_engine.embedder_model,
                "indexed_files": search_engine.indexed_files,
                "indexed_chunks": search_engine.indexed_chunks,
            }

        @app.post("/api/search/reindex")
        async def reindex():
            """Trigger a full reindex."""
            total = await search_engine.reindex()
            return {
                "message": "Reindex complete",
                "indexed_chunks": total,
            }

    return app
