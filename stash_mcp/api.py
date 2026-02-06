"""REST API implementation with FastAPI."""

import logging
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import Config
from .filesystem import (
    FileSystem,
    FileNotFoundError,
    FileSystemError,
    InvalidPathError,
)

logger = logging.getLogger(__name__)


class ContentItem(BaseModel):
    """Content item model."""

    path: str
    is_directory: bool
    content: Optional[str] = None


class ContentCreate(BaseModel):
    """Content creation model."""

    content: str


class ContentList(BaseModel):
    """Content list response."""

    items: List[ContentItem]


def create_api(filesystem: FileSystem) -> FastAPI:
    """Create FastAPI application.

    Args:
        filesystem: Filesystem instance

    Returns:
        FastAPI application
    """
    app = FastAPI(
        title="Stash-MCP API",
        description="REST API for Stash content management",
        version=Config.SERVER_VERSION,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "name": "Stash-MCP API",
            "version": Config.SERVER_VERSION,
            "endpoints": {
                "list": "/api/content",
                "read": "/api/content/{path}",
                "create": "PUT /api/content/{path}",
                "delete": "DELETE /api/content/{path}",
            },
        }

    @app.get("/api/content", response_model=ContentList)
    async def list_content(path: str = ""):
        """List content at path."""
        try:
            items = []
            if path:
                # List specific directory
                for name, is_dir in filesystem.list_files(path):
                    item_path = f"{path}/{name}" if path else name
                    items.append(
                        ContentItem(path=item_path, is_directory=is_dir)
                    )
            else:
                # List all files recursively
                for file_path in filesystem.list_all_files():
                    items.append(
                        ContentItem(path=file_path, is_directory=False)
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
            return ContentItem(path=path, is_directory=False, content=content)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error reading content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.put("/api/content/{path:path}")
    async def create_or_update_content(path: str, data: ContentCreate):
        """Create or update content file."""
        try:
            filesystem.write_file(path, data.content)
            return {"message": f"File '{path}' saved successfully"}
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
            return {"message": f"File '{path}' deleted successfully"}
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")
        except InvalidPathError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error deleting content: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return app
