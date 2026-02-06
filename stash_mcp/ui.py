"""Content browser & editor UI with three-panel layout."""

import html
import logging
from datetime import UTC, datetime
from pathlib import PurePosixPath

import markdown as md
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .filesystem import FileSystem
from .mcp_server import MIME_TYPES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lucide icon SVGs (inline, 16×16)
# ---------------------------------------------------------------------------

_ICONS = {
    "folder": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9'
        "a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0"
        ' 2 2Z"/></svg>'
    ),
    "file-text": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 '
        '2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M10 13H8"/><path d="M16 17H8"/><path d="M16 13h-2"/></svg>'
    ),
    "file-json": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 '
        '2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M10 12a1 1 0 0 0-1 1v1a1 1 0 0 1-1 1 1 1 0 0 1 1 1v1a1 1 0 0 0 '
        '1 1"/><path d="M14 18a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1 1 1 0 0 1-1-1v-1a1 1 '
        '0 0 0-1-1"/></svg>'
    ),
    "file": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 '
        '2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg>'
    ),
    "chevron-right": (
        '<svg class="icon chevron" width="14" height="14" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>'
    ),
    "plus": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>'
    ),
    "eye": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 '
        '10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/>'
        '<circle cx="12" cy="12" r="3"/></svg>'
    ),
    "pencil": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 '
        '16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 '
        '0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>'
    ),
    "trash-2": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 '
        '2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>'
        '<line x1="10" x2="10" y1="11" y2="17"/>'
        '<line x1="14" x2="14" y1="11" y2="17"/></svg>'
    ),
    "save": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 '
        '1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
        '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/>'
        '<path d="M7 3v4a1 1 0 0 0 1 1h7"/></svg>'
    ),
    "x": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>'
    ),
    "panel-left": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/>'
        '<path d="M9 3v18"/></svg>'
    ),
    "panel-right": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2"/>'
        '<path d="M15 3v18"/></svg>'
    ),
    "home": (
        '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 '
        '1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 '
        '5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>'
    ),
    "archive": (
        '<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><rect width="20" height="5" x="2" y="3" rx="1"/>'
        '<path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/>'
        '<path d="M10 12h4"/></svg>'
    ),
}


def _icon(name: str) -> str:
    """Return inline SVG for a Lucide icon name."""
    return _ICONS.get(name, "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_icon(name: str) -> str:
    """Return a Lucide SVG icon based on file extension."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in (".md", ".markdown"):
        return _icon("file-text")
    if suffix in (".json", ".yaml", ".yml", ".toml"):
        return _icon("file-json")
    return _icon("file")


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
        if i == 0:
            items.append(f'<a href="{html.escape(href)}">{_icon("home")} {escaped}</a>')
        elif i < len(crumbs) - 1:
            items.append(f'<a href="{html.escape(href)}">{escaped}</a>')
        else:
            items.append(f"<span>{escaped}</span>")
    return f' <span class="sep">{_icon("chevron-right")}</span> '.join(items)


def _render_markdown(content: str) -> str:
    """Render markdown to HTML with extensions.

    Raw HTML tags in content are escaped to prevent XSS.
    """
    safe_content = content.replace("<", "&lt;")
    converter = md.Markdown(extensions=[
        "fenced_code",
        "tables",
        "nl2br",
    ])
    return converter.convert(safe_content)


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
                f'<details {open_attr}><summary class="tree-dir">'
                f'{_icon("chevron-right")} {_icon("folder")} {escaped}</summary>'
                f'<div class="tree-children">{children_html}</div></details>'
            )
        else:
            icon = _file_icon(name)
            sel = ' class="tree-file selected"' if child == active else ' class="tree-file"'
            escaped_child = html.escape(child)
            parts.append(f'<a href="/ui/browse/{escaped_child}"{sel}>{icon} {escaped}</a>')
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

/* custom scrollbar */
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#313244;border-radius:4px;
transition:background 150ms ease}
::-webkit-scrollbar-thumb:hover{background:#7f849c}
*{scrollbar-width:thin;scrollbar-color:#313244 transparent}

/* icons */
.icon{display:inline-block;vertical-align:middle;flex-shrink:0}
.icon.chevron{transition:transform 150ms ease}
details[open]>summary .icon.chevron{transform:rotate(90deg)}

/* layout */
.layout{display:flex;height:100vh}
.sidebar{width:250px;min-width:0;background:#272738;border-right:1px solid #313244;
overflow-y:auto;padding:12px;flex-shrink:0;display:flex;flex-direction:column;
transition:width 150ms ease,padding 150ms ease}
.sidebar.collapsed{width:0;padding:0;overflow:hidden;border-right:none}
.sidebar-header{padding:8px 0 12px;border-bottom:1px solid #313244;margin-bottom:8px;
display:flex;flex-direction:column;gap:6px}
.sidebar-title{display:flex;align-items:center;gap:6px;font-size:14px;color:#cdd6f4;
font-weight:600}
.btn-new{display:flex;align-items:center;justify-content:center;gap:6px;
padding:6px 12px;background:#94e2d5;color:#1e1e2e;
border-radius:4px;font-size:13px;font-weight:600;text-align:center;border:none;cursor:pointer;
transition:background 150ms ease,transform 150ms ease}
.btn-new:hover{background:#a6e3e0;text-decoration:none;transform:translateY(-1px)}

/* search */
.search-box{margin-top:8px;position:relative}
.search-input{width:100%;padding:8px 12px;background:#1e1e2e;color:#cdd6f4;
border:1px solid #313244;border-radius:6px;font-size:13px;outline:none;
transition:border-color 150ms ease,box-shadow 150ms ease}
.search-input:focus{border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.1)}

.center{flex:1;overflow-y:auto;display:flex;flex-direction:column}
.center-toolbar{display:flex;align-items:center;justify-content:space-between;
padding:8px 24px;background:#272738;border-bottom:1px solid #313244;flex-shrink:0}
.toolbar-left{display:flex;align-items:center;gap:8px}
.toolbar-right{display:flex;align-items:center;gap:4px}
.panel-toggle{background:none;border:none;color:#7f849c;cursor:pointer;
padding:4px 6px;border-radius:4px;display:flex;align-items:center;
transition:background 150ms ease,color 150ms ease}
.panel-toggle:hover{color:#cdd6f4;background:#2e2e42}
.mode-switch{display:flex;background:#1e1e2e;border-radius:4px;overflow:hidden;
border:1px solid #313244}
.mode-btn{display:flex;align-items:center;gap:5px;padding:5px 12px;font-size:12px;
color:#7f849c;background:transparent;border:none;cursor:pointer;
transition:background 150ms ease,color 150ms ease;white-space:nowrap}
.mode-btn:hover{color:#cdd6f4}
.mode-btn.active{background:#94e2d5;color:#1e1e2e}
.center-content{flex:1;padding:24px 32px;overflow-y:auto;display:flex;
flex-direction:column;align-items:center}
.center-inner{width:100%;max-width:900px}

.right-panel{width:280px;min-width:0;background:#272738;border-left:1px solid #313244;
overflow-y:auto;padding:16px;flex-shrink:0;transition:width 150ms ease,padding 150ms ease}
.right-panel.collapsed{width:0;padding:0;overflow:hidden;border-left:none}

/* breadcrumbs */
.breadcrumbs{font-size:13px;color:#7f849c;margin-bottom:16px;
display:flex;align-items:center;flex-wrap:wrap;gap:2px}
.breadcrumbs a{color:#94e2d5;display:inline-flex;align-items:center;gap:3px}
.breadcrumbs .sep{color:#7f849c;display:inline-flex;align-items:center}

/* tree */
.tree-file{display:flex;align-items:center;gap:6px;padding:4px 8px;font-size:13px;
border-radius:4px;color:#cdd6f4;border-left:3px solid transparent;margin:1px 0;
transition:background 150ms ease}
.tree-file:hover{background:#2e2e42;text-decoration:none}
.tree-file.selected{border-left-color:#94e2d5;background:#2e2e42}
details summary.tree-dir{display:flex;align-items:center;gap:4px;
padding:4px 8px;font-size:13px;cursor:pointer;color:#cdd6f4;
list-style:none;border-radius:4px;margin:1px 0;transition:background 150ms ease}
details summary.tree-dir:hover{background:#2e2e42}
details summary.tree-dir::marker,details summary.tree-dir::-webkit-details-marker{display:none}
.tree-children{padding-left:14px;border-left:1px solid #313244;margin-left:10px}

/* file listing table */
.file-table{width:100%;border-collapse:collapse;margin-top:12px}
.file-table th{text-align:left;font-size:12px;color:#7f849c;padding:8px 10px;
border-bottom:1px solid #313244;font-weight:500}
.file-table td{padding:8px 10px;border-bottom:1px solid #313244;font-size:14px}
.file-table tr:hover td{background:#2e2e42}
.file-table .name a,.file-table .dir a{display:inline-flex;align-items:center;gap:6px}
.file-table .name a{color:#94e2d5}
.file-table .dir a{color:#cdd6f4}

/* viewer - typography for comfortable reading */
.viewer-content{background:#181825;padding:24px 32px;border-radius:6px;overflow-x:auto;
font-size:18px;line-height:1.6;color:#cdd6f4;margin-top:12px;max-width:70ch;
margin-left:auto;margin-right:auto}
.viewer-content pre{font-family:'Monaco','Menlo','Ubuntu Mono',monospace;
white-space:pre-wrap;word-wrap:break-word;margin:0}
.viewer-content h1{color:#e0e4f0;font-size:28px;margin-bottom:1.5rem;margin-top:0}
.viewer-content h2{color:#e0e4f0;font-size:22px;margin-top:2rem;margin-bottom:1rem}
.viewer-content h3{color:#e0e4f0;font-size:18px;margin-top:1.5rem;margin-bottom:0.75rem}
.viewer-content p{margin-bottom:1.5rem}
.viewer-content ul,.viewer-content ol{margin-bottom:1.5rem;padding-left:1.5rem}
.viewer-content li{margin-bottom:0.5rem}

/* markdown body styles */
.markdown-body code{background:#181825;padding:0.2em 0.4em;border-radius:3px;
font-size:0.9em;font-family:'Monaco','Menlo',monospace}
.markdown-body pre{background:#181825;padding:1rem;border-radius:6px;
overflow-x:auto;margin-bottom:1.5rem}
.markdown-body pre code{background:transparent;padding:0}
.markdown-body a{color:#94e2d5;text-decoration:underline}
.markdown-body table{width:100%;border-collapse:collapse;margin-bottom:1.5rem;
border:1px solid #313244}
.markdown-body th{padding:0.75rem;background:#272738;
border-bottom:2px solid #313244;text-align:left;color:#e0e4f0}
.markdown-body td{padding:0.75rem;border-bottom:1px solid #313244}
.markdown-body blockquote{border-left:3px solid #94e2d5;padding-left:1rem;
margin-left:0;color:#7f849c;margin-bottom:1.5rem}

/* editor */
.editor-area{width:100%;min-height:400px;background:#181825;color:#cdd6f4;
border:1px solid #313244;border-radius:6px;padding:16px;
font-family:'Monaco','Menlo','Ubuntu Mono',monospace;font-size:14px;line-height:1.6;
resize:vertical;transition:border-color 150ms ease,box-shadow 150ms ease}
.editor-area:focus{outline:none;border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.15)}
.path-input{width:100%;padding:10px 12px;background:#181825;color:#cdd6f4;
border:1px solid #313244;border-radius:6px;font-size:14px;margin-bottom:12px;
transition:border-color 150ms ease,box-shadow 150ms ease}
.path-input:focus{outline:none;border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.15)}
.action-bar{position:sticky;bottom:0;display:flex;gap:10px;margin-top:12px;
padding:16px 24px;background:rgba(30,30,46,0.95);backdrop-filter:blur(12px);
-webkit-backdrop-filter:blur(12px);border-top:1px solid #313244;
border-radius:8px 8px 0 0;justify-content:center;z-index:10}
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border-radius:4px;
font-size:14px;font-weight:500;cursor:pointer;border:none;
transition:background 150ms ease,opacity 150ms ease,transform 150ms ease}
.btn:hover{opacity:0.9;transform:translateY(-1px)}
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
.btn-edit{display:flex;align-items:center;justify-content:center;gap:6px;
padding:8px 14px;background:#94e2d5;color:#1e1e2e;border-radius:4px;
font-weight:500;font-size:13px;border:none;cursor:pointer;
transition:background 150ms ease,transform 150ms ease}
.btn-edit:hover{background:#a6e3e0;text-decoration:none;transform:translateY(-1px)}
.btn-delete{display:flex;align-items:center;justify-content:center;gap:6px;
padding:8px 14px;background:transparent;color:#f38ba8;
border:1px solid #f38ba8;border-radius:4px;font-weight:500;
font-size:13px;cursor:pointer;transition:background 150ms ease,transform 150ms ease}
.btn-delete:hover{background:rgba(243,139,168,0.1);text-decoration:none;transform:translateY(-1px)}
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
# JS for panel toggle
# ---------------------------------------------------------------------------

_JS = """
function toggleSidebar(){
  document.querySelector('.sidebar').classList.toggle('collapsed');
}
function toggleRight(){
  document.querySelector('.right-panel').classList.toggle('collapsed');
}
function showConfirm(btn){
  btn.style.display='none';
  btn.nextElementSibling.style.display='block';
}
function hideConfirm(btn){
  var f=btn.closest('.del-form');f.style.display='none';
  f.previousElementSibling.style.display='block';
}
function filterTree(query){
  var files=document.querySelectorAll('.tree-file');
  var dirs=document.querySelectorAll('.tree-root details');
  query=query.toLowerCase();
  if(!query){
    files.forEach(function(f){f.style.display='flex';});
    dirs.forEach(function(d){d.style.display='';d.removeAttribute('open');});
    return;
  }
  dirs.forEach(function(d){d.style.display='none';});
  files.forEach(function(file){
    var name=file.textContent.toLowerCase();
    if(name.includes(query)){
      file.style.display='flex';
      var p=file.parentElement;
      while(p&&!p.classList.contains('tree-root')){
        if(p.tagName==='DETAILS'){p.style.display='';p.setAttribute('open','');}
        p=p.parentElement;
      }
    }else{file.style.display='none';}
  });
}
var _unsaved=false;
(function(){
  var ta=document.querySelector('.editor-area');
  if(ta){ta.addEventListener('input',function(){_unsaved=true;});}
  var form=document.querySelector('form');
  if(form){form.addEventListener('submit',function(){_unsaved=false;});}
  window.addEventListener('beforeunload',function(e){
    if(_unsaved){e.preventDefault();e.returnValue='';return '';}
  });
  document.body.addEventListener('click',function(e){
    var link=e.target.closest('a');
    if(link&&_unsaved&&!confirm('You have unsaved changes. Continue?')){e.preventDefault();}
  });
  document.addEventListener('keydown',function(e){
    if((e.ctrlKey||e.metaKey)&&e.key==='s'){
      e.preventDefault();
      var f=document.querySelector('form');if(f)f.submit();
    }
    if((e.ctrlKey||e.metaKey)&&e.key==='e'){
      e.preventDefault();
      var el=document.querySelector('.mode-btn:not(.active)');if(el)el.click();
    }
    if((e.ctrlKey||e.metaKey)&&e.key==='b'){
      e.preventDefault();toggleSidebar();
    }
  });
})();
"""

# ---------------------------------------------------------------------------
# Shared HTML wrappers
# ---------------------------------------------------------------------------


def _page(
    title: str,
    sidebar: str,
    center: str,
    right: str = "",
    mode: str = "view",
    path: str = "",
) -> str:
    """Wrap content in the three-panel layout."""
    right_panel = f'<aside class="right-panel">{right}</aside>' if right else ""

    # Build mode switch if viewing/editing a file
    mode_switch = ""
    if path:
        view_cls = "mode-btn active" if mode == "view" else "mode-btn"
        edit_cls = "mode-btn active" if mode == "edit" else "mode-btn"
        escaped_path = html.escape(path)
        mode_switch = (
            '<div class="mode-switch">'
            f'<a class="{view_cls}" href="/ui/browse/{escaped_path}">'
            f'{_icon("eye")} View</a>'
            f'<a class="{edit_cls}" href="/ui/edit/{escaped_path}">'
            f'{_icon("pencil")} Edit</a>'
            "</div>"
        )

    toolbar_right_items = mode_switch
    if right:
        toolbar_right_items += (
            f'<button class="panel-toggle" onclick="toggleRight()" '
            f'title="Toggle info panel">{_icon("panel-right")}</button>'
        )

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
<div class="center">
<div class="center-toolbar">
<div class="toolbar-left">
<button class="panel-toggle" onclick="toggleSidebar()" title="Toggle sidebar">
{_icon("panel-left")}</button>
</div>
<div class="toolbar-right">{toolbar_right_items}</div>
</div>
<div class="center-content"><div class="center-inner">{center}</div></div>
</div>
{right_panel}
</div>
<script>{_JS}</script>
</body></html>"""


def _sidebar_html(filesystem: FileSystem, active: str = "") -> str:
    """Build sidebar HTML with header + search + tree."""
    tree = _build_tree_html(filesystem, active=active)
    return (
        '<div class="sidebar-header">'
        f'<div class="sidebar-title">{_icon("archive")} Stash-MCP</div>'
        f'<a href="/ui/new" class="btn-new">{_icon("plus")} New Document</a>'
        '<div class="search-box">'
        '<input type="text" id="tree-search" class="search-input" '
        'placeholder="Search files..." aria-label="Search files" '
        'oninput="filterTree(this.value)">'
        "</div>"
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
                escaped_child = html.escape(child)
                if is_dir:
                    rows += (
                        f'<tr><td class="dir"><a href="/ui/browse/{escaped_child}">'
                        f"{_icon('folder')} {escaped}/</a></td>"
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
                        f'<tr><td class="name"><a href="/ui/browse/{escaped_child}">'
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
            if path.endswith((".md", ".markdown")):
                rendered = _render_markdown(content)
                center = (
                    f'<div class="breadcrumbs">{breadcrumbs}</div>'
                    f"<h1>{html.escape(PurePosixPath(path).name)}</h1>"
                    f'<div class="viewer-content markdown-body">{rendered}</div>'
                )
            else:
                center = (
                    f'<div class="breadcrumbs">{breadcrumbs}</div>'
                    f"<h1>{html.escape(PurePosixPath(path).name)}</h1>"
                    f'<div class="viewer-content"><pre>{escaped_content}</pre></div>'
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
                f'<a href="/ui/edit/{html.escape(path)}" class="btn-edit">'
                f'{_icon("pencil")} Edit</a>'
                f'<button class="btn-delete" onclick="showConfirm(this)">'
                f'{_icon("trash-2")} Delete</button>'
                f'<form method="post" action="/ui/delete/{html.escape(path)}" '
                f'style="display:none" '
                f'class="del-form">'
                '<div class="confirm-row">'
                '<button type="submit" class="btn-confirm-del">Yes, delete</button>'
                '<button type="button" class="btn-confirm-cancel" '
                'onclick="hideConfirm(this)">Cancel</button>'
                "</div></form>"
                "</div>"
            )
            return _page(
                PurePosixPath(path).name, sidebar, center, right, mode="view", path=path
            )

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
            f"<h1>{html.escape(PurePosixPath(path).name)}</h1>"
            f'<form method="post" action="/ui/save">'
            f'<input type="hidden" name="path" value="{html.escape(path)}">'
            f'<textarea class="editor-area" name="content">{escaped}</textarea>'
            '<div class="action-bar">'
            f'<button type="submit" class="btn btn-save">{_icon("save")} Save</button>'
            f'<a href="/ui/browse/{html.escape(path)}" class="btn btn-cancel">'
            f'{_icon("x")} Cancel</a>'
            "</div></form>"
        )
        return _page(f"Edit {path}", sidebar, center, mode="edit", path=path)

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
            f'<button type="submit" class="btn btn-save">{_icon("save")} Create</button>'
            f'<a href="/ui/browse/" class="btn btn-cancel">{_icon("x")} Cancel</a>'
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
