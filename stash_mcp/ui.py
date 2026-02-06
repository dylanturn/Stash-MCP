"""Content browser & editor UI with three-panel layout."""

import html
import logging
from datetime import UTC, datetime
from pathlib import PurePosixPath

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .filesystem import FileSystem
from .mcp_server import MIME_TYPES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_icon(name: str) -> str:
    """Return an emoji icon based on file extension."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in (".md", ".markdown"):
        return "📝"
    if suffix in (".json", ".yaml", ".yml", ".toml"):
        return "📋"
    return "📄"


def _mime_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return MIME_TYPES.get(suffix, "text/plain")


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _breadcrumbs(path: str) -> list[tuple[str, str]]:
    """Return list of (label, href) breadcrumb pairs."""
    crumbs: list[tuple[str, str]] = [("Home", "/ui/browse/")]
    if not path:
        return crumbs
    parts = path.strip("/").split("/")
    for i, part in enumerate(parts):
        href = "/ui/browse/" + "/".join(parts[: i + 1])
        crumbs.append((part, href))
    return crumbs


def _breadcrumbs_html(path: str) -> str:
    crumbs = _breadcrumbs(path)
    items = []
    for i, (label, href) in enumerate(crumbs):
        escaped = html.escape(label)
        if i < len(crumbs) - 1:
            items.append(f'<a href="{href}">{escaped}</a>')
        else:
            items.append(f"<span>{escaped}</span>")
    return ' <span class="sep">›</span> '.join(items)


def _build_tree_html(filesystem: FileSystem, rel: str = "", active: str = "") -> str:
    """Build recursive HTML for the sidebar tree."""
    try:
        entries = filesystem.list_files(rel)
    except Exception:
        return ""
    parts: list[str] = []
    for name, is_dir in entries:
        child = f"{rel}/{name}" if rel else name
        escaped = html.escape(name)
        if is_dir:
            open_attr = "open" if active.startswith(child) else ""
            children_html = _build_tree_html(filesystem, child, active)
            parts.append(
                f'<details {open_attr}><summary class="tree-dir">📁 {escaped}</summary>'
                f'<div class="tree-children">{children_html}</div></details>'
            )
        else:
            icon = _file_icon(name)
            sel = ' class="tree-file selected"' if child == active else ' class="tree-file"'
            parts.append(f'<a href="/ui/browse/{child}"{sel}>{icon} {escaped}</a>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:#1e1e2e;color:#cdd6f4;min-height:100vh}
a{color:#94e2d5;text-decoration:none}
a:hover{text-decoration:underline}

/* layout */
.layout{display:flex;height:100vh}
.sidebar{width:250px;min-width:200px;background:#272738;border-right:1px solid #313244;
overflow-y:auto;padding:12px;flex-shrink:0;display:flex;flex-direction:column}
.sidebar-header{padding:8px 0 12px;border-bottom:1px solid #313244;margin-bottom:8px;
display:flex;flex-direction:column;gap:6px}
.sidebar-header h2{font-size:14px;color:#cdd6f4;font-weight:600}
.btn-new{display:inline-block;padding:6px 12px;background:#94e2d5;color:#1e1e2e;
border-radius:4px;font-size:13px;font-weight:600;text-align:center;border:none;cursor:pointer}
.btn-new:hover{background:#a6e3e0;text-decoration:none}

.center{flex:1;overflow-y:auto;padding:24px 32px;display:flex;flex-direction:column;
align-items:center}
.center-inner{width:100%;max-width:900px}

.right-panel{width:280px;min-width:220px;background:#272738;border-left:1px solid #313244;
overflow-y:auto;padding:16px;flex-shrink:0}

/* breadcrumbs */
.breadcrumbs{font-size:13px;color:#7f849c;margin-bottom:16px}
.breadcrumbs a{color:#94e2d5}
.breadcrumbs .sep{margin:0 4px;color:#7f849c}

/* tree */
.tree-file{display:block;padding:4px 8px;font-size:13px;border-radius:4px;
color:#cdd6f4;border-left:3px solid transparent;margin:1px 0}
.tree-file:hover{background:#2e2e42;text-decoration:none}
.tree-file.selected{border-left-color:#94e2d5;background:#2e2e42}
details summary.tree-dir{padding:4px 8px;font-size:13px;cursor:pointer;color:#cdd6f4;
list-style:none;border-radius:4px;margin:1px 0}
details summary.tree-dir:hover{background:#2e2e42}
details summary.tree-dir::marker,details summary.tree-dir::-webkit-details-marker{display:none}
.tree-children{padding-left:14px;border-left:1px solid #313244;margin-left:10px}

/* file listing table */
.file-table{width:100%;border-collapse:collapse;margin-top:12px}
.file-table th{text-align:left;font-size:12px;color:#7f849c;padding:8px 10px;
border-bottom:1px solid #313244;font-weight:500}
.file-table td{padding:8px 10px;border-bottom:1px solid #313244;font-size:14px}
.file-table tr:hover td{background:#2e2e42}
.file-table .name a{color:#94e2d5}
.file-table .dir a{color:#cdd6f4}

/* viewer */
.viewer-content{background:#181825;padding:20px;border-radius:6px;overflow-x:auto;
font-family:'Monaco','Menlo','Ubuntu Mono',monospace;font-size:14px;line-height:1.6;
white-space:pre-wrap;word-wrap:break-word;color:#cdd6f4;margin-top:12px}

/* editor */
.editor-area{width:100%;min-height:400px;background:#181825;color:#cdd6f4;
border:1px solid #313244;border-radius:6px;padding:16px;
font-family:'Monaco','Menlo','Ubuntu Mono',monospace;font-size:14px;line-height:1.6;
resize:vertical}
.editor-area:focus{outline:none;border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.15)}
.path-input{width:100%;padding:10px 12px;background:#181825;color:#cdd6f4;
border:1px solid #313244;border-radius:6px;font-size:14px;margin-bottom:12px}
.path-input:focus{outline:none;border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.15)}
.action-bar{display:flex;gap:10px;margin-top:12px}
.btn{padding:8px 18px;border-radius:4px;font-size:14px;font-weight:500;
cursor:pointer;border:none;transition:background 150ms ease}
.btn-save{background:#94e2d5;color:#1e1e2e}
.btn-save:hover{background:#a6e3e0}
.btn-cancel{background:#313244;color:#cdd6f4}
.btn-cancel:hover{background:#3e3e55}

/* right panel */
.meta-section{margin-bottom:20px}
.meta-section h3{font-size:13px;color:#7f849c;margin-bottom:8px;text-transform:uppercase;
letter-spacing:0.5px}
.meta-row{display:flex;justify-content:space-between;font-size:13px;padding:4px 0;
color:#cdd6f4}
.meta-row .label{color:#7f849c}
.action-stack{display:flex;flex-direction:column;gap:8px;margin-top:16px}
.btn-edit{display:block;padding:8px 14px;background:#94e2d5;color:#1e1e2e;border-radius:4px;
text-align:center;font-weight:500;font-size:13px;border:none;cursor:pointer}
.btn-edit:hover{background:#a6e3e0;text-decoration:none}
.btn-delete{display:block;padding:8px 14px;background:transparent;color:#f38ba8;
border:1px solid #f38ba8;border-radius:4px;text-align:center;font-weight:500;
font-size:13px;cursor:pointer}
.btn-delete:hover{background:rgba(243,139,168,0.1);text-decoration:none}
.confirm-row{display:flex;gap:6px}
.btn-confirm-del{padding:6px 12px;background:#f38ba8;color:#1e1e2e;border-radius:4px;
font-size:12px;font-weight:600;border:none;cursor:pointer}
.btn-confirm-del:hover{background:#f5a0ba}
.btn-confirm-cancel{padding:6px 12px;background:#313244;color:#cdd6f4;border-radius:4px;
font-size:12px;border:none;cursor:pointer}
.btn-confirm-cancel:hover{background:#3e3e55}

/* headings */
h1{font-size:22px;color:#e0e4f0;margin-bottom:4px;font-weight:600}
h2{font-size:17px;color:#e0e4f0;margin-bottom:12px;font-weight:500}

.empty-msg{color:#7f849c;font-style:italic;padding:20px 0;text-align:center}
.error-msg{color:#f38ba8;background:rgba(243,139,168,0.08);padding:12px;
border-radius:4px;border-left:3px solid #f38ba8;margin-bottom:12px}
"""

# ---------------------------------------------------------------------------
# Shared HTML wrappers
# ---------------------------------------------------------------------------


def _page(title: str, sidebar: str, center: str, right: str = "") -> str:
    """Wrap content in the three-panel layout."""
    right_panel = f'<aside class="right-panel">{right}</aside>' if right else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} – Stash-MCP</title>
<style>{_CSS}</style>
</head>
<body>
<div class="layout">
<nav class="sidebar">{sidebar}</nav>
<main class="center"><div class="center-inner">{center}</div></main>
{right_panel}
</div>
</body></html>"""


def _sidebar_html(filesystem: FileSystem, active: str = "") -> str:
    """Build sidebar HTML with header + tree."""
    tree = _build_tree_html(filesystem, active=active)
    return (
        '<div class="sidebar-header">'
        '<h2>🗂️ Stash-MCP</h2>'
        '<a href="/ui/new" class="btn-new">+ New Document</a>'
        "</div>"
        f'<div class="tree-root">{tree if tree else "<p class=empty-msg>No files yet</p>"}</div>'
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def create_ui_router(filesystem: FileSystem) -> APIRouter:
    """Create UI router with content browser & editor.

    Args:
        filesystem: Filesystem instance

    Returns:
        FastAPI router for UI
    """
    router = APIRouter()

    # --- redirect /ui to /ui/browse/ ---
    @router.get("/ui", response_class=RedirectResponse)
    async def ui_home():
        """Redirect to browse root."""
        return RedirectResponse(url="/ui/browse/", status_code=302)

    # --- browse (directory listing or file view) ---
    @router.get("/ui/browse/{path:path}", response_class=HTMLResponse)
    async def ui_browse(path: str) -> str:
        """Browse a directory or view a file."""
        # Normalise empty / trailing slashes
        path = path.strip("/")
        sidebar = _sidebar_html(filesystem, active=path)
        breadcrumbs = _breadcrumbs_html(path)

        # Determine if path is a directory or a file
        try:
            full = filesystem._resolve_path(path) if path else filesystem.content_dir
        except Exception:
            center = (
                f'<div class="breadcrumbs">{breadcrumbs}</div>'
                '<div class="error-msg">Invalid path.</div>'
            )
            return _page("Error", sidebar, center)

        # --- directory listing ---
        if full.is_dir():
            try:
                entries = filesystem.list_files(path)
            except Exception:
                entries = []
            rows = ""
            for name, is_dir in entries:
                child = f"{path}/{name}" if path else name
                escaped = html.escape(name)
                if is_dir:
                    rows += (
                        f'<tr><td class="dir"><a href="/ui/browse/{child}">📁 {escaped}/</a></td>'
                        "<td>directory</td><td>—</td><td>—</td></tr>"
                    )
                else:
                    # file metadata
                    try:
                        fp = filesystem._resolve_path(child)
                        st = fp.stat()
                        size = _human_size(st.st_size)
                        mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    except Exception:
                        size = "—"
                        mtime = "—"
                    icon = _file_icon(name)
                    rows += (
                        f'<tr><td class="name"><a href="/ui/browse/{child}">'
                        f"{icon} {escaped}</a></td>"
                        f"<td>{html.escape(_mime_type(child))}</td>"
                        f"<td>{size}</td><td>{mtime}</td></tr>"
                    )

            if rows:
                table = (
                    '<table class="file-table"><thead><tr>'
                    "<th>Name</th><th>Type</th><th>Size</th><th>Modified</th>"
                    "</tr></thead><tbody>" + rows + "</tbody></table>"
                )
            else:
                table = '<p class="empty-msg">This directory is empty.</p>'

            title = path or "Root"
            center = (
                f'<div class="breadcrumbs">{breadcrumbs}</div>'
                f"<h1>{html.escape(title)}</h1>"
                f"{table}"
            )
            return _page(f"Browse {title}", sidebar, center)

        # --- file view ---
        if full.is_file():
            try:
                content = filesystem.read_file(path)
            except Exception as exc:
                center = (
                    f'<div class="breadcrumbs">{breadcrumbs}</div>'
                    f'<div class="error-msg">Error reading file: {html.escape(str(exc))}</div>'
                )
                return _page("Error", sidebar, center)

            escaped_content = html.escape(content)
            center = (
                f'<div class="breadcrumbs">{breadcrumbs}</div>'
                f"<h1>{html.escape(PurePosixPath(path).name)}</h1>"
                f'<div class="viewer-content">{escaped_content}</div>'
            )

            # right panel — metadata + actions
            try:
                st = full.stat()
                size = _human_size(st.st_size)
                mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except Exception:
                size = "—"
                mtime = "—"
            words = len(content.split())
            chars = len(content)
            right = (
                '<div class="meta-section"><h3>File Info</h3>'
                f'<div class="meta-row"><span class="label">Path</span>'
                f"<span>{html.escape(path)}</span></div>"
                f'<div class="meta-row"><span class="label">MIME</span>'
                f"<span>{html.escape(_mime_type(path))}</span></div>"
                f'<div class="meta-row"><span class="label">Size</span>'
                f"<span>{size}</span></div>"
                f'<div class="meta-row"><span class="label">Modified</span>'
                f"<span>{mtime}</span></div>"
                f'<div class="meta-row"><span class="label">Words</span>'
                f"<span>{words}</span></div>"
                f'<div class="meta-row"><span class="label">Characters</span>'
                f"<span>{chars}</span></div>"
                "</div>"
                '<div class="action-stack">'
                f'<a href="/ui/edit/{path}" class="btn-edit">✏️ Edit</a>'
                f'<button class="btn-delete" onclick="showConfirm(this)">🗑️ Delete</button>'
                f'<form method="post" action="/ui/delete/{path}" style="display:none" '
                f'class="del-form">'
                '<div class="confirm-row">'
                '<button type="submit" class="btn-confirm-del">Yes, delete</button>'
                '<button type="button" class="btn-confirm-cancel" '
                'onclick="hideConfirm(this)">Cancel</button>'
                "</div></form>"
                "</div>"
                "<script>"
                "function showConfirm(btn){"
                "btn.style.display='none';"
                "btn.nextElementSibling.style.display='block'}"
                "function hideConfirm(btn){"
                "var f=btn.closest('.del-form');f.style.display='none';"
                "f.previousElementSibling.style.display='block'}"
                "</script>"
            )
            return _page(PurePosixPath(path).name, sidebar, center, right)

        # path exists but is neither dir nor file
        center = (
            f'<div class="breadcrumbs">{breadcrumbs}</div>'
            '<div class="error-msg">Path not found.</div>'
        )
        return _page("Not Found", sidebar, center)

    # also handle bare /ui/browse/ (no trailing path)
    @router.get("/ui/browse/", response_class=HTMLResponse)
    async def ui_browse_root() -> str:
        """Browse root directory."""
        return await ui_browse("")

    # --- edit ---
    @router.get("/ui/edit/{path:path}", response_class=HTMLResponse)
    async def ui_edit(path: str) -> str:
        """Edit an existing file."""
        path = path.strip("/")
        sidebar = _sidebar_html(filesystem, active=path)
        breadcrumbs = _breadcrumbs_html(path)

        try:
            content = filesystem.read_file(path)
        except Exception as exc:
            center = (
                f'<div class="breadcrumbs">{breadcrumbs}</div>'
                f'<div class="error-msg">Error: {html.escape(str(exc))}</div>'
            )
            return _page("Error", sidebar, center)

        escaped = html.escape(content)
        center = (
            f'<div class="breadcrumbs">{breadcrumbs}</div>'
            f"<h1>Editing: {html.escape(PurePosixPath(path).name)}</h1>"
            f'<form method="post" action="/ui/save">'
            f'<input type="hidden" name="path" value="{html.escape(path)}">'
            f'<textarea class="editor-area" name="content">{escaped}</textarea>'
            '<div class="action-bar">'
            '<button type="submit" class="btn btn-save">Save</button>'
            f'<a href="/ui/browse/{path}" class="btn btn-cancel">Cancel</a>'
            "</div></form>"
        )
        return _page(f"Edit {path}", sidebar, center)

    # --- new file ---
    @router.get("/ui/new", response_class=HTMLResponse)
    async def ui_new() -> str:
        """Create a new file form."""
        sidebar = _sidebar_html(filesystem)
        breadcrumbs = _breadcrumbs_html("")
        center = (
            f'<div class="breadcrumbs">{breadcrumbs}</div>'
            "<h1>New Document</h1>"
            '<form method="post" action="/ui/save">'
            '<input class="path-input" type="text" name="path" '
            'placeholder="e.g. notes/meeting.md" required>'
            '<textarea class="editor-area" name="content" '
            'placeholder="Start writing…"></textarea>'
            '<div class="action-bar">'
            '<button type="submit" class="btn btn-save">Create</button>'
            '<a href="/ui/browse/" class="btn btn-cancel">Cancel</a>'
            "</div></form>"
        )
        return _page("New Document", sidebar, center)

    # --- save (handles both create and edit) ---
    @router.post("/ui/save")
    async def ui_save(request: Request, path: str = Form(...), content: str = Form(...)):
        """Save file content (create or update)."""
        path = path.strip("/")
        try:
            filesystem.write_file(path, content)
        except Exception as exc:
            logger.error(f"UI save error: {exc}")
            # Fall back to edit page with error shown via redirect
            return RedirectResponse(url=f"/ui/edit/{path}", status_code=303)
        return RedirectResponse(url=f"/ui/browse/{path}", status_code=303)

    # --- delete ---
    @router.post("/ui/delete/{path:path}")
    async def ui_delete(path: str):
        """Delete a file and redirect to parent directory."""
        path = path.strip("/")
        parent = str(PurePosixPath(path).parent)
        if parent == ".":
            parent = ""
        try:
            filesystem.delete_file(path)
        except Exception as exc:
            logger.error(f"UI delete error: {exc}")
        return RedirectResponse(url=f"/ui/browse/{parent}", status_code=303)

    return router
