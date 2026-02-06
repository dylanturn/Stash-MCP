"""FastUI implementation for content browser."""

import logging
from typing import List

from fastapi import APIRouter
from fastui import FastUI, components as c
from fastui.components.display import DisplayLookup, DisplayMode
from fastui.events import GoToEvent

from .filesystem import FileSystem

logger = logging.getLogger(__name__)


def create_ui_router(filesystem: FileSystem) -> APIRouter:
    """Create FastUI router.

    Args:
        filesystem: Filesystem instance

    Returns:
        FastAPI router for UI
    """
    router = APIRouter()

    @router.get("/ui", response_model=FastUI, response_model_exclude_none=True)
    async def ui_home() -> List[c.AnyComponent]:
        """Main UI page."""
        try:
            files = filesystem.list_all_files()
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            files = []

        return [
            c.Page(
                components=[
                    c.Heading(text="Stash-MCP Content Browser", level=1),
                    c.Paragraph(
                        text="Browse and manage your content files. Files are stored on disk and exposed via MCP."
                    ),
                    c.Table(
                        data=[{"path": f, "view": f"View"} for f in files],
                        columns=[
                            {"name": "path", "title": "File Path"},
                            {
                                "name": "view",
                                "title": "Actions",
                                "render": lambda item: c.Link(
                                    components=[c.Text(text="View")],
                                    on_click=GoToEvent(url=f"/ui/view/{item['path']}"),
                                ),
                            },
                        ],
                    ),
                ]
            ),
        ]

    @router.get(
        "/ui/view/{path:path}", response_model=FastUI, response_model_exclude_none=True
    )
    async def ui_view_file(path: str) -> List[c.AnyComponent]:
        """View a specific file."""
        try:
            content = filesystem.read_file(path)
        except Exception as e:
            logger.error(f"Error reading file: {e}")
            content = f"Error: {e}"

        return [
            c.Page(
                components=[
                    c.Link(components=[c.Text(text="← Back")], on_click=GoToEvent(url="/ui")),
                    c.Heading(text=path, level=2),
                    c.Code(text=content, language="markdown"),
                ]
            ),
        ]

    return router
