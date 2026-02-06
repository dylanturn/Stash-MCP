"""Simple UI implementation for content browser."""

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .filesystem import FileSystem

logger = logging.getLogger(__name__)


def create_ui_router(filesystem: FileSystem) -> APIRouter:
    """Create UI router.

    Args:
        filesystem: Filesystem instance

    Returns:
        FastAPI router for UI
    """
    router = APIRouter()

    @router.get("/ui", response_class=HTMLResponse)
    async def ui_home() -> str:
        """Main UI page."""
        try:
            files = filesystem.list_all_files()
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            files = []

        # Generate simple HTML page
        files_html = "".join(
            f'<li><a href="/ui/view/{f}">{f}</a></li>' for f in files
        )

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Stash-MCP Content Browser</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                h1 {{
                    color: #333;
                    border-bottom: 3px solid #007bff;
                    padding-bottom: 10px;
                }}
                .description {{
                    color: #666;
                    margin: 20px 0;
                }}
                ul {{
                    list-style: none;
                    padding: 0;
                }}
                li {{
                    padding: 12px;
                    margin: 8px 0;
                    background: #f8f9fa;
                    border-radius: 4px;
                    border-left: 4px solid #007bff;
                }}
                a {{
                    color: #007bff;
                    text-decoration: none;
                    font-weight: 500;
                }}
                a:hover {{
                    text-decoration: underline;
                }}
                .empty {{
                    color: #999;
                    font-style: italic;
                    padding: 20px;
                    text-align: center;
                }}
                .links {{
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🗂️ Stash-MCP Content Browser</h1>
                <p class="description">
                    Browse and manage your content files.
                    Files are stored on disk and exposed via MCP.
                </p>
                <h2>📄 Content Files ({len(files)})</h2>
                {f'<ul>{files_html}</ul>' if files else (
                    '<p class="empty">'
                    'No content files found. Add some files to the content directory.'
                    '</p>'
                )}
                <div class="links">
                    <h3>📚 Resources</h3>
                    <ul>
                        <li><a href="/docs">📖 API Documentation (Swagger UI)</a></li>
                        <li><a href="/api/content">🔗 View Content API</a></li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """

    @router.get("/ui/view/{path:path}", response_class=HTMLResponse)
    async def ui_view_file(path: str) -> str:
        """View a specific file."""
        try:
            content = filesystem.read_file(path)
            error = None
        except Exception as e:
            logger.error(f"Error reading file: {e}")
            content = ""
            error = str(e)

        # Escape HTML in content
        import html
        escaped_content = html.escape(content)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{path} - Stash-MCP</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .container {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                h1 {{
                    color: #333;
                    border-bottom: 3px solid #007bff;
                    padding-bottom: 10px;
                }}
                .back {{
                    display: inline-block;
                    margin-bottom: 20px;
                    color: #007bff;
                    text-decoration: none;
                }}
                .back:hover {{
                    text-decoration: underline;
                }}
                pre {{
                    background: #f8f9fa;
                    padding: 20px;
                    border-radius: 4px;
                    overflow-x: auto;
                    border-left: 4px solid #007bff;
                }}
                code {{
                    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    font-size: 14px;
                    line-height: 1.6;
                }}
                .error {{
                    color: #dc3545;
                    background: #f8d7da;
                    padding: 15px;
                    border-radius: 4px;
                    border-left: 4px solid #dc3545;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <a href="/ui" class="back">← Back to Content List</a>
                <h1>📄 {path}</h1>
                {'<div class="error">Error: ' + error + '</div>' if error else ''}
                <pre><code>{escaped_content}</code></pre>
            </div>
        </body>
        </html>
        """

    return router
