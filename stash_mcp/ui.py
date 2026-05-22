"""Content browser & editor UI with three-panel layout."""

import base64
import csv
import html
import io
import json as _json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import markdown as md
import yaml as _yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .events import CONTENT_CREATED, CONTENT_DELETED, CONTENT_MOVED, CONTENT_UPDATED, emit
from .filesystem import FileNotFoundError as FSFileNotFoundError
from .filesystem import FileSystem, InvalidPathError
from .mcp_server import MIME_TYPES

_STATIC_DIR = Path(__file__).parent / "static"


def _static_url(rel_path: str) -> str:
    """Return a `/static/...` URL with an mtime-based cache buster.

    Browsers cache `/static/*` aggressively. Appending the file's mtime as a
    query string means any edit to a shipped asset invalidates the cache on
    next page load — no hard-refresh required.
    """
    try:
        mtime = int((_STATIC_DIR / rel_path).stat().st_mtime)
    except OSError:
        mtime = 0
    return f"/static/{rel_path}?v={mtime}"


_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp"})
_SVG_EXTENSIONS = frozenset({".svg"})
_HTML_EXTENSIONS = frozenset({".html", ".htm"})
_MERMAID_EXTENSIONS = frozenset({".mmd", ".mermaid"})
_GANTT_EXTENSIONS = frozenset({".gantt"})
_CSV_EXTENSIONS = frozenset({".csv", ".tsv"})

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
    "folder-open": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 '
        '0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2'
        'h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/></svg>'
    ),
    "chevron-down": (
        '<svg class="icon chevron-down" width="14" height="14" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>'
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
    "image": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>'
        '<circle cx="9" cy="9" r="2"/>'
        '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>'
    ),
    "code": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/>'
        '<polyline points="8 6 2 12 8 18"/></svg>'
    ),
    "globe": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><circle cx="12" cy="12" r="10"/>'
        '<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
        '<path d="M2 12h20"/></svg>'
    ),
    "git-branch": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><line x1="6" x2="6" y1="3" y2="15"/>'
        '<circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>'
        '<path d="M18 9a9 9 0 0 1-9 9"/></svg>'
    ),
    "external-link": (
        '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M15 3h6v6"/>'
        '<path d="M10 14 21 3"/>'
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>'
    ),
    "pen-line": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 '
        '3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l'
        '.838-2.872a2 2 0 0 1 .506-.854z"/></svg>'
    ),
    "table": (
        '<svg class="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M12 3v18"/><rect width="18" height="18" '
        'x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/></svg>'
    ),
}


def _icon(name: str) -> str:
    """Return inline SVG for a Lucide icon name."""
    return _ICONS.get(name, "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_icon(name: str) -> str:
    """Return a Lucide SVG icon for a file."""
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in _IMAGE_EXTENSIONS or suffix in _SVG_EXTENSIONS:
        return _icon("image")
    if suffix in _HTML_EXTENSIONS:
        return _icon("globe")
    if suffix in _MERMAID_EXTENSIONS or suffix in _GANTT_EXTENSIONS:
        return _icon("git-branch")
    if suffix in _CSV_EXTENSIONS:
        return _icon("table")
    if suffix in {".json"}:
        return _icon("file-json")
    return _icon("file-text")


def _mime_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return MIME_TYPES.get(suffix, "text/plain")


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


_METHOD_COLORS = {
    "get": ("#a6e3a1", "#1e1e2e"),
    "post": ("#89b4fa", "#1e1e2e"),
    "put": ("#fab387", "#1e1e2e"),
    "patch": ("#cba6f7", "#1e1e2e"),
    "delete": ("#f38ba8", "#1e1e2e"),
    "head": ("#94e2d5", "#1e1e2e"),
    "options": ("#7f849c", "#1e1e2e"),
}


def _render_openapi(spec: dict) -> tuple[str, str]:
    """Render an OpenAPI spec as styled HTML. Returns (center_html, toc_html)."""
    info = spec.get("info", {})
    title = html.escape(info.get("title", "API"))
    version = html.escape(info.get("version", ""))
    description = html.escape(info.get("description", ""))
    openapi_ver = html.escape(str(spec.get("openapi", "")))

    parts: list[str] = []
    toc_items: list[str] = []

    parts.append(
        f'<div class="oas-header">'
        f'<h1>{title}</h1>'
        f'<div class="oas-meta">'
        f'<span class="oas-badge oas-badge-ver">OpenAPI {openapi_ver}</span>'
        f'<span class="oas-badge oas-badge-ver">v{version}</span>'
        f'</div>'
    )
    if description:
        parts.append(f'<p class="oas-desc">{description}</p>')
    parts.append('</div>')

    paths = spec.get("paths", {})
    if paths:
        tag_groups: dict[str, list[tuple[str, str, dict]]] = {}
        for route, methods in paths.items():
            for method, op in methods.items():
                if method.lower() in _METHOD_COLORS:
                    tags = op.get("tags", ["default"])
                    for tag in tags:
                        tag_groups.setdefault(tag, []).append(
                            (route, method.upper(), op)
                        )

        for tag, operations in tag_groups.items():
            tag_slug = re.sub(r'[^a-z0-9_-]', '-', tag.lower()).strip('-')
            tag_id = f"tag-{html.escape(tag_slug)}"
            tag_esc = html.escape(tag)
            toc_items.append(
                f'<a href="#{tag_id}" class="toc-link">{tag_esc}'
                f'<span class="toc-count">{len(operations)}</span></a>'
            )
            parts.append(
                f'<div class="oas-tag-group" id="{tag_id}">'
                f'<h2 class="oas-tag-title">{tag_esc}</h2>'
            )

            for route, method, op in operations:
                bg, fg = _METHOD_COLORS.get(method.lower(), ("#7f849c", "#1e1e2e"))
                summary = html.escape(op.get("summary", ""))
                desc = html.escape(op.get("description", ""))
                op_id = html.escape(op.get("operationId", ""))
                route_esc = html.escape(route)

                parts.append(
                    f'<details class="oas-op">'
                    f'<summary class="oas-op-summary">'
                    f'<span class="oas-method" style="background:{bg};color:{fg}">'
                    f'{method}</span>'
                    f'<span class="oas-path">{route_esc}</span>'
                    f'<span class="oas-summary">{summary}</span>'
                    f'</summary>'
                    f'<div class="oas-op-body">'
                )

                if desc:
                    parts.append(f'<p class="oas-op-desc">{desc}</p>')
                if op_id:
                    parts.append(
                        f'<div class="oas-op-id">'
                        f'<span class="oas-label">operationId:</span> {op_id}</div>'
                    )

                params = op.get("parameters", [])
                if params:
                    parts.append(
                        '<div class="oas-section">'
                        '<h4 class="oas-section-title">Parameters</h4>'
                        '<table class="oas-params">'
                        '<thead><tr><th>Name</th><th>In</th><th>Type</th>'
                        '<th>Required</th><th>Description</th></tr></thead><tbody>'
                    )
                    for p in params:
                        pname = html.escape(p.get("name", ""))
                        pin = html.escape(p.get("in", ""))
                        schema = p.get("schema", {})
                        ptype = html.escape(_oas_type_label(schema))
                        preq = "Yes" if p.get("required") else "No"
                        pdesc = html.escape(p.get("description", ""))
                        req_cls = " oas-required" if p.get("required") else ""
                        parts.append(
                            f'<tr><td class="oas-pname{req_cls}">{pname}</td>'
                            f'<td><span class="oas-in-badge">{pin}</span></td>'
                            f'<td class="oas-ptype">{ptype}</td>'
                            f'<td>{preq}</td><td>{pdesc}</td></tr>'
                        )
                    parts.append('</tbody></table></div>')

                req_body = op.get("requestBody", {})
                if req_body:
                    rb_content = req_body.get("content", {})
                    for media, media_obj in rb_content.items():
                        schema = media_obj.get("schema", {})
                        parts.append(
                            f'<div class="oas-section">'
                            f'<h4 class="oas-section-title">Request Body'
                            f'<span class="oas-media-type">{html.escape(media)}</span></h4>'
                            f'<div class="oas-schema-block">'
                            f'{_oas_schema_html(schema, spec)}'
                            f'</div></div>'
                        )

                responses = op.get("responses", {})
                if responses:
                    parts.append(
                        '<div class="oas-section">'
                        '<h4 class="oas-section-title">Responses</h4>'
                    )
                    for code, resp in responses.items():
                        rdesc = html.escape(resp.get("description", ""))
                        code_cls = "oas-code-2xx" if code.startswith("2") else (
                            "oas-code-4xx" if code.startswith("4") else "oas-code-other"
                        )
                        parts.append(
                            f'<div class="oas-response">'
                            f'<span class="oas-resp-code {code_cls}">{html.escape(code)}</span>'
                            f'<span class="oas-resp-desc">{rdesc}</span>'
                            f'</div>'
                        )
                    parts.append('</div>')

                parts.append('</div></details>')

            parts.append('</div>')

    schemas = spec.get("components", {}).get("schemas", {})
    if schemas:
        toc_items.append(
            '<a href="#oas-schemas" class="toc-link">Schemas'
            f'<span class="toc-count">{len(schemas)}</span></a>'
        )
        parts.append(
            '<div class="oas-tag-group" id="oas-schemas">'
            '<h2 class="oas-tag-title">Schemas</h2>'
        )
        for name, schema in schemas.items():
            name_esc = html.escape(name)
            schema_type = html.escape(_oas_type_label(schema))
            desc = html.escape(schema.get("description", ""))
            parts.append(
                f'<details class="oas-op oas-schema-def">'
                f'<summary class="oas-op-summary">'
                f'<span class="oas-method oas-schema-badge">SCHEMA</span>'
                f'<span class="oas-path">{name_esc}</span>'
                f'<span class="oas-summary">{schema_type}</span>'
                f'</summary>'
                f'<div class="oas-op-body">'
            )
            if desc:
                parts.append(f'<p class="oas-op-desc">{desc}</p>')
            parts.append(
                f'<div class="oas-schema-block">{_oas_schema_html(schema, spec)}'
                f'</div></div></details>'
            )
        parts.append('</div>')

    center_html = f'<div class="viewer-openapi">{"".join(parts)}</div>'

    toc_html = ""
    if toc_items:
        toc_html = '<div class="toc">' + "".join(toc_items) + '</div>'
    return center_html, toc_html


def _oas_type_label(schema: dict) -> str:
    """Human-readable type from a JSON Schema snippet."""
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    t = schema.get("type", "")
    if isinstance(t, list):
        return " | ".join(t)
    if t == "array":
        items = schema.get("items", {})
        return f"array[{_oas_type_label(items)}]"
    fmt = schema.get("format")
    if fmt:
        return f"{t} ({fmt})"
    any_of = schema.get("anyOf", [])
    if any_of:
        return " | ".join(_oas_type_label(s) for s in any_of)
    return t or "object"


def _oas_schema_html(schema: dict, spec: dict, depth: int = 0) -> str:
    """Render a JSON Schema object's properties as an HTML table."""
    if "$ref" in schema:
        ref = schema["$ref"]
        resolved = _oas_resolve_ref(ref, spec)
        if resolved and depth < 3:
            return _oas_schema_html(resolved, spec, depth + 1)
        name = html.escape(ref.rsplit("/", 1)[-1])
        return f'<span class="oas-ref">{name}</span>'

    props = schema.get("properties", {})
    if not props:
        return f'<span class="oas-ptype">{html.escape(_oas_type_label(schema))}</span>'

    required_set = set(schema.get("required", []))
    rows: list[str] = []
    for pname, pschema in props.items():
        pname_esc = html.escape(pname)
        ptype = html.escape(_oas_type_label(pschema))
        req_cls = " oas-required" if pname in required_set else ""
        rows.append(
            f'<tr><td class="oas-pname{req_cls}">{pname_esc}</td>'
            f'<td class="oas-ptype">{ptype}</td></tr>'
        )
    return (
        '<table class="oas-props"><tbody>'
        + "".join(rows)
        + '</tbody></table>'
    )


def _oas_resolve_ref(ref: str, spec: dict) -> dict | None:
    """Resolve a $ref like '#/components/schemas/Foo'."""
    if not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    node: dict = spec
    for p in parts:
        if isinstance(node, dict) and p in node:
            node = node[p]
        else:
            return None
    return node if isinstance(node, dict) else None


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


_CSV_FENCE_RE = re.compile(
    r"^```(?P<lang>csv|tsv)\s*\n(?P<body>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)


def _csv_fence_replace(m: re.Match) -> str:
    """Replace a ```csv/tsv fenced block with a rendered HTML table."""
    lang = m.group("lang")
    body = m.group("body")
    suffix = f".{lang}"
    try:
        table_html, _ = _render_csv(body, suffix)
        return table_html
    except Exception:
        return m.group(0)


_EMBED_FENCE_RE = re.compile(
    r"^```stash-embed\s*\n(?P<body>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)


def _embed_error(message: str) -> str:
    return f'<div class="error-msg">Embed error: {html.escape(message)}</div>'


def _resolve_embed_src(src: str, base_dir: str) -> str:
    """Resolve an embed `src` to a content-store-relative path.

    Absolute (`/specs/api.json`) is rooted at the content store; otherwise the
    src is interpreted relative to the embedding document's directory.
    """
    if src.startswith("/"):
        return src.lstrip("/")
    if base_dir:
        return str(PurePosixPath(base_dir) / src)
    return src


def _filter_openapi_spec(
    spec: dict,
    *,
    tag: str | None = None,
    path_filter: str | None = None,
    operation_id: str | None = None,
) -> dict:
    """Return a copy of `spec` containing only paths/operations matching the filters.

    With no filters set, returns the spec unchanged. When filters are applied,
    `components.schemas` is dropped from the embedded view — embeds are meant
    to show a focused slice, and the schemas block doubles the rendered height.
    """
    if not (tag or path_filter or operation_id):
        return spec

    filtered_paths: dict = {}
    for route, methods in spec.get("paths", {}).items():
        if path_filter and route != path_filter:
            continue
        if not isinstance(methods, dict):
            continue
        kept: dict = {}
        for method, op in methods.items():
            if not isinstance(op, dict) or method.lower() not in _METHOD_COLORS:
                continue
            if tag and tag not in op.get("tags", []):
                continue
            if operation_id and op.get("operationId") != operation_id:
                continue
            kept[method] = op
        if kept:
            filtered_paths[route] = kept

    new_spec = dict(spec)
    new_spec["paths"] = filtered_paths
    components = new_spec.get("components")
    if isinstance(components, dict) and "schemas" in components:
        trimmed = dict(components)
        trimmed.pop("schemas", None)
        new_spec["components"] = trimmed
    return new_spec


_OPENAPI_EXTS = frozenset({".json", ".yaml", ".yml"})
_HTML_EMBED_EXTS = frozenset({".html", ".htm"})


def _infer_embed_type(src: str, raw: str, suffix: str) -> str | None:
    """Infer embed type from extension + content. Returns None if ambiguous."""
    if suffix in _HTML_EMBED_EXTS:
        return "html"
    if suffix in _OPENAPI_EXTS:
        # JSON/YAML could be anything; sniff for openapi key.
        try:
            if suffix in (".yaml", ".yml"):
                parsed = _yaml.safe_load(raw)
            else:
                parsed = _json.loads(raw)
        except (ValueError, _yaml.YAMLError):
            return None
        if isinstance(parsed, dict) and "openapi" in parsed:
            return "openapi"
    return None


def _render_openapi_embed(raw: str, src: str, suffix: str, config: dict) -> str:
    """Render an OpenAPI fragment for inline embedding.

    YAML 1.1 is a superset of JSON, so a single `yaml.safe_load` parses both —
    important because `type: openapi` overrides let users embed YAML specs
    stored under ambiguous extensions (e.g. `.txt`) where suffix-based parser
    selection would have wrongly defaulted to JSON.
    """
    del suffix  # parser is now extension-agnostic
    try:
        spec = _yaml.safe_load(raw)
    except (ValueError, _yaml.YAMLError) as exc:
        return _embed_error(f"failed to parse '{src}': {exc}")
    if not isinstance(spec, dict) or "openapi" not in spec:
        return _embed_error(f"'{src}' is not an OpenAPI spec")

    tag = config.get("tag")
    path_filter = config.get("path")
    operation_id = config.get("operationId")
    for name, value in (("tag", tag), ("path", path_filter), ("operationId", operation_id)):
        if value is not None and not isinstance(value, str):
            return _embed_error(f"'{name}' must be a string")

    filtered = _filter_openapi_spec(
        spec, tag=tag, path_filter=path_filter, operation_id=operation_id,
    )
    if (tag or path_filter or operation_id) and not filtered.get("paths"):
        selectors = ", ".join(
            f"{k}={v}" for k, v in [
                ("tag", tag), ("path", path_filter), ("operationId", operation_id)
            ] if v
        )
        return _embed_error(f"no operations in '{src}' matched {selectors}")

    try:
        center_html, _ = _render_openapi(filtered)
    except Exception as exc:
        return _embed_error(f"render failed: {exc}")
    return f'<div class="embedded-openapi">{center_html}</div>'


# Matches `body`, `html`, or `:root` when they appear at the start of a CSS
# selector (start of file, after `}`, or after `,`) and are followed by a token
# that ends a selector or starts a compound (whitespace, `{`, `,`, `.`, `#`,
# `:`, `[`, `>`, `~`, `+`). Captures the preceding boundary and any whitespace
# so they can be re-emitted unchanged.
_ROOT_SELECTOR_RE = re.compile(
    r"(^|[\},])(\s*)(?:body|html|:root)(?=[\s\.\#\:\[\>\~\+\,\{]|$)"
)

# Matches a non-@-rule selector list that ends in `{`. The boundary captures
# either start-of-file or the closing of the previous block, so we can prepend
# `:scope ` to every selector inside an `@scope` block. The `[^@\}\{]+?`
# excludes `@` so we don't try to rewrite `@media` / `@supports` / etc. preludes
# — their inner rules are matched in subsequent iterations.
_RULE_HEAD_RE = re.compile(r"(^|[\}\{])([^@\}\{]+?)\{", re.MULTILINE)

# Matches the `@keyframes <name>` (or vendor-prefixed) start of a keyframes
# at-rule. Keyframes step lists (`0% { ... }`, `from { ... }`, `to { ... }`)
# are NOT selectors and must not be prefixed with `:scope` — doing so produces
# invalid CSS and silently breaks animations. We extract the whole keyframes
# block by tracking brace depth, then splice it back unchanged after scoping.
_KEYFRAMES_START_RE = re.compile(
    r"@(?:-webkit-|-moz-|-o-|-ms-)?keyframes\b", re.IGNORECASE,
)


def _extract_keyframes(css: str) -> tuple[str, dict[str, str]]:
    """Replace each `@keyframes` block with a placeholder. Returns the
    placeholder-substituted CSS and a mapping of placeholders to original
    block text.

    The placeholder is itself an empty at-rule (`@stash-kf-N{}`) so that the
    later selector-rewriting pass ignores it (`_RULE_HEAD_RE` skips selector
    portions that contain `@`) and treats the trailing `}` as a clean boundary
    before the next real rule.
    """
    placeholders: dict[str, str] = {}
    out: list[str] = []
    i = 0
    while i < len(css):
        m = _KEYFRAMES_START_RE.search(css, i)
        if not m:
            out.append(css[i:])
            break
        out.append(css[i:m.start()])
        # Find the opening brace; if none, give up and emit verbatim.
        brace = css.find("{", m.end())
        if brace < 0:
            out.append(css[m.start():])
            break
        depth = 1
        j = brace + 1
        while j < len(css) and depth > 0:
            ch = css[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        token = f"@stash-kf-{len(placeholders)}{{}}"
        placeholders[token] = css[m.start():j]
        out.append(token)
        i = j
    return "".join(out), placeholders


def _split_top_level_commas(s: str) -> list[str]:
    """Split `s` on commas that sit at the top level — outside parentheses,
    square brackets, and quoted strings.

    Needed for CSS selector lists: `:is(h1, h2, h3) { ... }` is a single
    selector, but a naive `s.split(",")` would shred it into three nonsense
    fragments (`:is(h1`, `h2`, `h3)`). Functional pseudo-classes like
    `:is()`, `:not()`, `:where()`, `:has()`, and `:nth-child(2n+1 of ...)`
    all rely on this behavior, and attribute selectors like `[data-x=","]`
    can carry a literal comma inside brackets/strings too.
    """
    parts: list[str] = []
    buf: list[str] = []
    paren = 0
    bracket = 0
    in_string: str | None = None
    i = 0
    while i < len(s):
        ch = s[i]
        if in_string is not None:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(s):
                # Pass through escape sequence atomically so an escaped quote
                # doesn't end the string.
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = ch
            buf.append(ch)
        elif ch == "(":
            paren += 1
            buf.append(ch)
        elif ch == ")":
            if paren > 0:
                paren -= 1
            buf.append(ch)
        elif ch == "[":
            bracket += 1
            buf.append(ch)
        elif ch == "]":
            if bracket > 0:
                bracket -= 1
            buf.append(ch)
        elif ch == "," and paren == 0 and bracket == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _scope_css_selectors(css: str) -> str:
    """Rewrite every non-@-rule selector in `css` so it gains class-level
    specificity inside the embed's `@scope (.embed-xxx)` block.

    1. Leading `body` / `html` / `:root` tokens are rewritten to `:scope`.
    2. Other selectors are prefixed with `:scope ` (descendant combinator) so
       e.g. `h2 { ... }` becomes `:scope h2 { ... }`. Without this boost the
       host's `.markdown-body h2 { color: ... }` (specificity 0,1,1) beats the
       source's naked `h2 { ... }` (0,0,1) and headings render in the host's
       color instead of the source's.

    `@keyframes` blocks are extracted first and spliced back unchanged so we
    don't try to rewrite their step lists (`0%`, `from`, `to`) as selectors.
    Selector lists are split with `_split_top_level_commas` so commas inside
    `:is(...)` / `:not(...)` / attribute selectors don't shred a functional
    pseudo-class into garbage.
    """
    css, keyframes = _extract_keyframes(css)

    def _rewrite(match: re.Match) -> str:
        boundary = match.group(1)
        selectors = match.group(2)
        if not selectors.strip():
            return match.group(0)
        parts: list[str] = []
        for raw in _split_top_level_commas(selectors):
            stripped = raw.strip()
            if not stripped:
                continue
            stripped = _ROOT_SELECTOR_RE.sub(r":scope", stripped)
            if not stripped.startswith(":scope"):
                stripped = f":scope {stripped}"
            parts.append(stripped)
        return f"{boundary}{', '.join(parts)} {{"

    rewritten = _RULE_HEAD_RE.sub(_rewrite, css)
    for token, block in keyframes.items():
        rewritten = rewritten.replace(token, block)
    return rewritten


# Defensive reset injected into every styled HTML embed. Each `:scope <el>`
# selector has specificity (0,1,1) — ties with host rules like
# `.markdown-body th { background: #272738 }` and wins by source order, so
# host CSS doesn't leak into elements the source didn't explicitly style.
#
# `all: revert` resets every property of the matched elements to what the
# user-agent stylesheet would set, ignoring all author styles from earlier in
# the cascade (i.e., the host). Source rules with the same selector come
# *after* this reset in the same author origin, so they win on source order
# and the source's intended styling lands on top. Source class/id rules
# (specificity 0,2,0+) beat the reset outright. Anything the source doesn't
# style falls back to UA defaults (transparent bg, browser-default fonts and
# borders) — i.e., the embed renders like a standalone HTML page.
_EMBED_HOST_STYLE_RESET = (
    ":scope h1, :scope h2, :scope h3, :scope h4, :scope h5, :scope h6, "
    ":scope p, :scope a, :scope li, :scope ul, :scope ol, :scope dl, "
    ":scope dt, :scope dd, :scope table, :scope thead, :scope tbody, "
    ":scope tr, :scope th, :scope td, :scope caption, "
    ":scope blockquote, :scope figure, :scope figcaption, "
    ":scope code, :scope pre, :scope kbd, :scope samp, :scope var, "
    ":scope strong, :scope em, :scope b, :scope i, :scope u, :scope s, "
    ":scope small, :scope mark, :scope label, :scope hr "
    "{ all: revert; }\n"
)


def _sanitize_embed_dom(soup) -> None:
    """In-place: strip scripts and inline event handlers from an embed tree.

    Standalone `.html` files render in a sandboxed iframe (see the
    `serve_browse` route). Embedded fragments, however, are injected directly
    into the host document — they share the UI page's origin and have access
    to its DOM. To keep embed semantics closer to the sandboxed view (and to
    defend against accidentally executing scripts from un-vetted HTML in the
    content store), we remove:

      - `<script>` elements
      - Any `on*` event-handler attribute (onclick, onerror, etc.)
      - `href`/`src`/`xlink:href`/`action` values that use the `javascript:`
        scheme

    Styles are intentionally kept — they're already isolated via `@scope`.
    """
    for tag in list(soup.find_all("script")):
        tag.decompose()
    for tag in soup.find_all(True):
        # Iterate over a snapshot of attr keys; we mutate the dict in-place.
        for attr in list(tag.attrs.keys()):
            if attr.lower().startswith("on"):
                del tag.attrs[attr]
            elif attr.lower() in ("href", "src", "xlink:href", "action", "formaction"):
                value = tag.attrs[attr]
                if isinstance(value, list):
                    value = " ".join(value)
                if isinstance(value, str) and value.strip().lower().startswith("javascript:"):
                    del tag.attrs[attr]


def _rewrite_embed_relative_urls(html_str: str, embed_dir: str) -> str:
    """Rewrite relative `src`/`href` in an embed fragment to absolute
    `/ui/raw/...` paths anchored at the embed source's directory.

    The host markdown's `_rewrite_relative_urls` runs once over the final
    rendered document, but it uses the *embedding markdown's* base_dir — so
    relative URLs inside an embed (e.g. `images/foo.png` inside
    `reports/q2.html`) would resolve under the markdown's folder instead of
    the HTML source's folder. Rewriting here, before insertion, turns them
    into absolute paths that the later pass leaves alone.
    """
    if not embed_dir or embed_dir == ".":
        # Source sits at the content root; relatives already resolve correctly
        # via the later pass with base_dir="".
        return _rewrite_relative_urls(html_str, "")
    return _rewrite_relative_urls(html_str, embed_dir)


def _render_html_embed(raw: str, src: str, embed_dir: str, config: dict) -> str:
    """Render an HTML fragment for inline embedding.

    With `selector:`, returns the matched subtree(s). Without, returns the
    document `<body>` (or the whole tree if no body element).

    `<style>` blocks from the source are extracted and re-emitted scoped to a
    per-embed CSS `@scope` rule, so the source's styling applies to its own
    fragment without leaking into the host document. A short hash of
    (src, selector) keys the scope class so multiple embeds from different
    sources don't collide on shared selectors like `section { ... }`.

    Scripts and event-handler attributes are stripped (see
    `_sanitize_embed_dom`), and relative URLs are rewritten relative to the
    source's directory (`embed_dir`).
    """
    import hashlib

    from bs4 import BeautifulSoup

    selector = config.get("selector")
    if selector is not None and not isinstance(selector, str):
        return _embed_error("'selector' must be a string")

    try:
        soup = BeautifulSoup(raw, "html.parser")
    except Exception as exc:
        return _embed_error(f"failed to parse '{src}': {exc}")

    style_blocks = soup.find_all("style")
    combined_css = "\n".join(str(s.string or "") for s in style_blocks).strip()
    for s in style_blocks:
        s.decompose()

    _sanitize_embed_dom(soup)

    # Always emit the reset — even when the source has no <style> block at
    # all. Without this, sources like a bare `<div>...<code>...</code></div>`
    # would still have host markdown rules (e.g. `.markdown-body code
    # { background: #181825 }`) leak through. Source CSS, if present, gets
    # the `:scope ` specificity boost so it beats host rules too. See
    # _scope_css_selectors() for the why.
    if combined_css:
        combined_css = _scope_css_selectors(combined_css)
    combined_css = _EMBED_HOST_STYLE_RESET + combined_css

    if selector:
        try:
            matches = soup.select(selector)
        except Exception as exc:
            return _embed_error(f"invalid selector '{selector}': {exc}")
        if not matches:
            return _embed_error(f"no elements in '{src}' matched selector '{selector}'")
        fragment = "".join(str(m) for m in matches)
    else:
        body = soup.body
        fragment = body.decode_contents() if body else str(soup)

    fragment = _rewrite_embed_relative_urls(fragment, embed_dir)

    digest = hashlib.sha256(f"{src}|{selector or ''}".encode()).hexdigest()[:10]
    scope_class = f"embed-{digest}"

    style_html = ""
    if combined_css:
        style_html = f"<style>@scope (.{scope_class}) {{\n{combined_css}\n}}</style>"

    return f'{style_html}<div class="embedded-html {scope_class}">{fragment}</div>'


def _make_embed_replacer(filesystem: "FileSystem | None", base_dir: str):
    """Build a fenced-block replacer that resolves ```stash-embed blocks.

    Dispatches by `type:` (if set) or by `src` extension + content sniffing.
    Supported types: openapi, html.
    """

    def _replace(m: re.Match) -> str:
        body = m.group("body")
        try:
            config = _yaml.safe_load(body) or {}
        except _yaml.YAMLError as exc:
            return _embed_error(f"invalid YAML: {exc}")
        if not isinstance(config, dict):
            return _embed_error("embed config must be a YAML mapping")

        src = config.get("src")
        if not isinstance(src, str) or not src:
            return _embed_error("embed requires a 'src' field")
        if filesystem is None:
            return _embed_error(f"cannot resolve '{src}': no filesystem in context")

        resolved = _resolve_embed_src(src, base_dir)
        try:
            raw = filesystem.read_file(resolved)
        except (FileNotFoundError, FSFileNotFoundError):
            return _embed_error(f"source not found: {src}")
        except InvalidPathError:
            # `..` escapes or absolute paths that resolve outside the content
            # root reach here. Surface a dedicated message rather than leaking
            # the raw exception text via the generic handler below.
            return _embed_error(f"invalid src '{src}': resolves outside content directory")
        except Exception as exc:
            return _embed_error(f"failed to read '{src}': {exc}")

        suffix = PurePosixPath(resolved).suffix.lower()
        explicit_type = config.get("type")
        if explicit_type is not None and not isinstance(explicit_type, str):
            return _embed_error("'type' must be a string")

        embed_type = explicit_type or _infer_embed_type(src, raw, suffix)
        if embed_type is None:
            return _embed_error(
                f"could not determine embed type for '{src}'; "
                f"set 'type:' explicitly (openapi, html)"
            )

        if embed_type == "openapi":
            return _render_openapi_embed(raw, src, suffix, config)
        if embed_type == "html":
            # The embed source's parent dir — used to resolve relative URLs
            # inside the fragment so e.g. `<img src="images/foo.png">` in
            # `reports/q2.html` resolves under `reports/`, not the embedding
            # markdown's folder.
            parent = PurePosixPath(resolved).parent
            embed_dir = "" if str(parent) in ("", ".") else str(parent)
            return _render_html_embed(raw, src, embed_dir, config)
        return _embed_error(f"unknown embed type '{embed_type}' (supported: openapi, html)")

    return _replace


def _render_markdown(
    content: str,
    filesystem: "FileSystem | None" = None,
    base_dir: str = "",
) -> tuple[str, str]:
    """Render markdown to HTML with extensions. Returns (html, toc_html).

    Raw HTML in markdown is passed through by design — Stash-MCP stores
    user-controlled content (personal knowledge base), so constructs like
    <details>, <img>, and <div> in markdown files are intentionally supported.
    Do not expose the UI to untrusted third-party content.
    """
    if filesystem is not None:
        content = _EMBED_FENCE_RE.sub(_make_embed_replacer(filesystem, base_dir), content)
    content = _CSV_FENCE_RE.sub(_csv_fence_replace, content)
    converter = md.Markdown(extensions=[
        "fenced_code",
        "tables",
        "nl2br",
        "toc",
        "sane_lists",
        "smarty",
    ])
    rendered = converter.convert(content)
    return rendered, getattr(converter, "toc", "")


_RELATIVE_URL_RE = re.compile(
    r'(<(?:img|source|video|audio|iframe)\b[^>]*?\b(?:src)='
    r'["\'])(?!https?://|data:|/|#)'
    r'|'
    r'(<a\b[^>]*?\bhref='
    r'["\'])(?!https?://|mailto:|data:|/|#)',
    re.IGNORECASE,
)


def _rewrite_relative_urls(html_str: str, base_dir: str) -> str:
    """Rewrite relative src/href in rendered HTML to /ui/raw/ or /ui/browse/ paths."""
    from urllib.parse import quote
    safe_dir = quote(base_dir, safe="/")
    if not base_dir:
        raw_prefix = "/ui/raw/"
        browse_prefix = "/ui/browse/"
    else:
        raw_prefix = f"/ui/raw/{html.escape(safe_dir)}/"
        browse_prefix = f"/ui/browse/{html.escape(safe_dir)}/"

    def _replace(m: re.Match) -> str:
        tag_img = m.group(1)
        tag_a = m.group(2)
        if tag_img:
            return tag_img + raw_prefix
        return tag_a + browse_prefix

    return _RELATIVE_URL_RE.sub(_replace, html_str)


def _render_csv(content: str, suffix: str) -> tuple[str, str]:
    """Render CSV/TSV content as an HTML table. Returns (center_html, toc_html)."""
    delimiter = "\t" if suffix == ".tsv" else ","
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return '<div class="viewer-content"><pre></pre></div>', ""

    has_header = csv.Sniffer().has_header(content[:8192]) if len(content) > 0 else False
    header = rows[0] if has_header else [f"Col {i + 1}" for i in range(len(rows[0]))]
    data_rows = rows[1:] if has_header else rows
    num_cols = len(header)

    thead = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    thead = f'<th class="csv-row-num">#</th>{thead}'

    tbody_parts: list[str] = []
    for i, row in enumerate(data_rows, start=1):
        cells = "".join(
            f"<td>{html.escape(row[j]) if j < len(row) else ''}</td>"
            for j in range(num_cols)
        )
        tbody_parts.append(f'<tr><td class="csv-row-num">{i}</td>{cells}</tr>')

    num_rows = len(data_rows)
    stats = (
        f'<div class="csv-stats">'
        f"<span>{num_rows:,} row{'s' if num_rows != 1 else ''}</span>"
        f"<span>{num_cols:,} column{'s' if num_cols != 1 else ''}</span>"
        f"</div>"
    )

    center = (
        f'<div class="viewer-csv">'
        f'<table class="csv-table"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{"".join(tbody_parts)}</tbody></table>'
        f"{stats}</div>"
    )
    return center, ""


def _sort_entries(entries: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Sort entries: directories first, then README.md, then remaining files (all alpha)."""
    dirs = [(n, d) for n, d in entries if d]
    readme = [(n, d) for n, d in entries if not d and n.lower() == "readme.md"]
    files = [(n, d) for n, d in entries if not d and n.lower() != "readme.md"]
    return dirs + readme + files


def _build_tree_html(filesystem: FileSystem, rel: str = "", active: str = "") -> str:
    """Build recursive HTML for the sidebar tree."""
    try:
        entries = filesystem.list_files(rel)
    except Exception:
        return ""
    sorted_entries = _sort_entries(entries)
    parts: list[str] = []
    for name, is_dir in sorted_entries:
        child = f"{rel}/{name}" if rel else name
        escaped = html.escape(name)
        if is_dir:
            open_attr = "open" if active.startswith(child) else ""
            children_html = _build_tree_html(filesystem, child, active)
            escaped_child = html.escape(child)
            parts.append(
                f'<details {open_attr} data-path="{escaped_child}">'
                f'<summary class="tree-dir">'
                f'<span class="tree-chevron">{_icon("chevron-right")}{_icon("chevron-down")}</span>'
                f'<span class="tree-folder-icon">{_icon("folder")}{_icon("folder-open")}</span>'
                f' {escaped}</summary>'
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

/* tree chevron + folder icon swap */
.tree-chevron{display:inline-flex;align-items:center;flex-shrink:0;color:#7f849c}
.tree-chevron .icon.chevron-down{display:none}
details[open]>summary .tree-chevron .icon{display:none}
details[open]>summary .tree-chevron .icon.chevron-down{display:inline-block}
.tree-folder-icon{display:inline-flex;align-items:center;flex-shrink:0;color:#94e2d5}
.tree-folder-icon .icon:last-child{display:none}
details[open]>summary .tree-folder-icon .icon:first-child{display:none}
details[open]>summary .tree-folder-icon .icon:last-child{display:inline-block}
.tree-file .icon{color:#7f849c}

/* layout */
.app{display:flex;flex-direction:column;height:100vh}
.top-bar{display:flex;align-items:center;justify-content:space-between;
padding:0 20px;height:70px;background:#272738;border-bottom:1px solid #313244;flex-shrink:0}
.top-bar-left{display:flex;align-items:center}
.app-wordmark{display:block}
.top-bar-right{display:flex;align-items:center;gap:4px}
.layout{display:flex;flex:1;overflow:hidden}
.sidebar{width:250px;min-width:0;background:#272738;border-right:1px solid #313244;
overflow-y:auto;padding:12px;flex-shrink:0;display:flex;flex-direction:column;
transition:width 150ms ease,padding 150ms ease}
.sidebar.collapsed{width:0;padding:0;overflow:hidden;border-right:none}
.sidebar-header{padding:8px 0 12px;border-bottom:1px solid #313244;margin-bottom:8px;
display:flex;flex-direction:column;gap:6px}
.btn-new{display:flex;align-items:center;justify-content:center;gap:6px;
padding:8px 12px;background:#94e2d5;color:#1e1e2e;
border-radius:6px;font-size:13px;font-weight:600;text-align:center;border:none;cursor:pointer;
transition:background 150ms ease,transform 150ms ease}
.btn-new:hover{background:#a6e3e0;text-decoration:none;transform:translateY(-1px)}

/* search */
.search-box{margin-top:8px;position:relative}
.search-input{width:100%;padding:8px 12px;background:#1e1e2e;color:#cdd6f4;
border:1px solid #313244;border-radius:6px;font-size:13px;outline:none;
transition:border-color 150ms ease,box-shadow 150ms ease}
.search-input:focus{border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.1)}
.search-results{margin-top:6px;display:none}
.search-results.active{display:block}
.search-result{display:block;padding:6px 10px;margin:2px 0;border-radius:4px;
color:#cdd6f4;text-decoration:none;font-size:12px;background:#1e1e2e;
border:1px solid #313244;transition:background 150ms ease,border-color 150ms ease}
.search-result:hover{background:#2e2e42;border-color:#94e2d5;text-decoration:none}
.search-result-path{font-weight:600;color:#94e2d5;display:block;margin-bottom:2px}
.search-result-snippet{color:#a6adc8;font-size:11px;line-height:1.4;
display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.search-result-score{font-size:10px;color:#585b70;margin-top:2px}
.search-no-results{padding:8px 10px;color:#585b70;font-size:12px;font-style:italic}
.search-loading{display:flex;align-items:center;gap:8px;padding:10px;color:#7f849c;font-size:12px}
.search-spinner{width:16px;height:16px;border:2px solid #313244;border-top-color:#94e2d5;
border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

.center{flex:1;overflow-y:auto;display:flex;flex-direction:column}
.panel-toggle{background:none;border:none;color:#7f849c;cursor:pointer;
padding:6px 8px;border-radius:4px;display:flex;align-items:center;
transition:background 150ms ease,color 150ms ease}
.panel-toggle:hover{color:#cdd6f4;background:#2e2e42}

/* mode tabs */
.mode-tabs{display:flex;gap:0;border-bottom:1px solid #313244;flex-shrink:0;
padding:0 32px;background:transparent;height: 50px;}
.mode-tab{display:inline-flex;align-items:center;gap:6px;padding:10px 16px;
font-size:14px;color:#7f849c;background:transparent;border:none;
border-bottom:2px solid transparent;cursor:pointer;
transition:color 150ms ease,border-color 150ms ease;white-space:nowrap;margin-bottom:-1px}
.mode-tab:hover{color:#cdd6f4;text-decoration:none}
.mode-tab.active{color:#cdd6f4;border-bottom-color:#94e2d5}

.center-content{flex:1;padding:24px 32px;overflow-y:auto;display:flex;
flex-direction:column;align-items:center;min-height:0}
.center-inner{width:100%;display:flex;flex-direction:column;flex:1;min-height:0}

.right-panel{width:280px;min-width:0;background:#272738;border-left:1px solid #313244;
flex-shrink:0;display:flex;flex-direction:column;overflow:hidden;
transition:width 150ms ease,padding 150ms ease}
.right-panel.collapsed{width:0;overflow:hidden;border-left:none}
.right-toc{flex:1;min-height:0;overflow-y:auto;padding:16px}
.toc-heading{font-size:14px;font-weight:600;color:#7f849c;margin-bottom:12px;
display:flex;align-items:center;gap:8px}
.toc-nav .toc li{list-style:none}
.toc-nav .toc a{display:block;padding:6px 12px;color:#7f849c;font-size:14px;
text-decoration:none;border-left:2px solid transparent;border-radius:0 4px 4px 0;
transition:color 150ms ease,background 150ms ease,border-color 150ms ease}
.toc-nav .toc a:hover{color:#cdd6f4;background:rgba(148,226,213,0.05)}
.toc-nav .toc a.active{color:#94e2d5;background:rgba(148,226,213,0.08);
border-left-color:#94e2d5}
.toc-nav .toc ul{padding-left:0;margin:0}
.toc-nav .toc>ul>li>a{padding-left:12px}
.toc-nav .toc>ul>li>ul>li>a{padding-left:28px}
.toc-nav .toc>ul>li>ul>li>ul>li>a{padding-left:44px}
.right-meta-accordion{flex-shrink:0;border-top:1px solid #313244}
.meta-accordion-header{display:flex;align-items:center;justify-content:space-between;
padding:14px 16px;font-size:15px;font-weight:600;color:#cdd6f4;cursor:pointer;list-style:none}
.meta-accordion-header::-webkit-details-marker,.meta-accordion-header::marker{display:none}
.meta-accordion-header .icon{transition:transform 150ms ease}
.meta-accordion[open] .meta-accordion-header .icon{transform:rotate(90deg)}
.meta-accordion-body{padding:0 16px 16px}
.right-bottom{flex-shrink:0;border-top:1px solid #313244;padding:12px 16px}

/* breadcrumbs */
.breadcrumbs{font-size:13px;color:#7f849c;margin-bottom:16px;
display:flex;align-items:center;flex-wrap:wrap;gap:2px}
.breadcrumbs a{color:#94e2d5;display:inline-flex;align-items:center;gap:3px}
.breadcrumbs .sep{color:#7f849c;display:inline-flex;align-items:center}

/* tree */
.tree-file{display:flex;align-items:center;gap:8px;padding:6px 10px;font-size:14px;
border-radius:6px;color:#cdd6f4;margin:2px 0;transition:background 150ms ease}
.tree-file:hover{background:#2e2e42;text-decoration:none}
.tree-file.selected{background:rgba(148,226,213,0.08);outline:1px solid rgba(148,226,213,0.20)}
details summary.tree-dir{display:flex;align-items:center;gap:4px;
padding:6px 8px;font-size:14px;cursor:pointer;color:#cdd6f4;
list-style:none;border-radius:6px;margin:2px 0;transition:background 150ms ease}
details summary.tree-dir:hover{background:#2e2e42}
details summary.tree-dir::marker,details summary.tree-dir::-webkit-details-marker{display:none}
.tree-children{padding-left:24px}

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
.viewer-content{background:transparent;padding:24px 32px;border-radius:6px;overflow-x:auto;
font-size:18px;line-height:1.6;color:#cdd6f4;margin-top:12px;flex:1;width:100%}
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
.editor-form{display:flex;flex-direction:column;flex:1;min-height:0}
.editor-area{width:100%;flex:1;min-height:300px;background:#181825;color:#cdd6f4;
border:1px solid #313244;border-radius:8px;padding:20px 24px;
font-family:'Monaco','Menlo','Ubuntu Mono',monospace;font-size:14px;line-height:1.7;
resize:none;transition:border-color 150ms ease,box-shadow 150ms ease}
.editor-area:focus{outline:none;border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.15)}
.path-input{width:100%;padding:10px 12px;background:#181825;color:#cdd6f4;
border:1px solid #313244;border-radius:6px;font-size:14px;margin-bottom:12px;
transition:border-color 150ms ease,box-shadow 150ms ease}
.path-input:focus{outline:none;border-color:#94e2d5;box-shadow:0 0 0 2px rgba(148,226,213,0.15)}
.action-bar{display:flex;gap:12px;padding:16px 0;justify-content:center;flex-shrink:0}
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 24px;border-radius:6px;
font-size:14px;font-weight:500;cursor:pointer;border:none;
transition:background 150ms ease,transform 150ms ease}
.btn:hover{transform:translateY(-1px)}
.btn-save{background:#94e2d5;color:#1e1e2e}
.btn-save:hover{background:#a6e3e0}
.btn-discard{background:transparent;color:#7f849c;border:1px solid #313244}
.btn-discard:hover{color:#cdd6f4;border-color:#7f849c}
.unsaved-dot{display:inline-block;width:8px;height:8px;border-radius:50%;
background:#94e2d5;margin-left:4px;vertical-align:middle}

/* right panel */
.meta-heading{font-size:16px;font-weight:600;color:#e0e4f0;margin-bottom:16px}
.meta-field{padding:12px 0;border-bottom:1px solid #313244}
.meta-field:last-child{border-bottom:none}
.meta-field-label{font-size:12px;color:#7f849c;margin-bottom:4px;text-transform:capitalize;
letter-spacing:0.3px}
.meta-field-value{font-size:15px;color:#cdd6f4;font-weight:500}
.meta-field-path{background:#181825;padding:10px 12px;border-radius:6px;
font-family:'Monaco','Menlo','Ubuntu Mono',monospace;font-size:13px;
color:#cdd6f4;word-break:break-all;margin-top:6px}
.meta-stats-heading{font-size:12px;color:#7f849c;margin-bottom:8px;text-transform:capitalize;
letter-spacing:0.3px}
.meta-stat-row{display:flex;justify-content:space-between;font-size:15px;padding:2px 0;
color:#cdd6f4}
.meta-stat-row .label{color:#7f849c}
.meta-stat-row .value{font-weight:500}
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
.btn-rename{display:flex;align-items:center;justify-content:center;gap:6px;
padding:8px 14px;background:transparent;color:#cdd6f4;
border:1px solid #585b70;border-radius:4px;font-weight:500;
font-size:13px;cursor:pointer;transition:background 150ms ease,transform 150ms ease}
.btn-rename:hover{background:rgba(148,226,213,0.08);border-color:#94e2d5;
transform:translateY(-1px)}
.rename-form{display:none}
.rename-input{width:100%;padding:8px 10px;background:#181825;color:#cdd6f4;
border:1px solid #313244;border-radius:4px;font-size:13px;margin-bottom:6px;
transition:border-color 150ms ease,box-shadow 150ms ease}
.rename-input:focus{outline:none;border-color:#94e2d5;
box-shadow:0 0 0 2px rgba(148,226,213,0.15)}
.btn-confirm-rename{padding:6px 12px;background:#94e2d5;color:#1e1e2e;border-radius:4px;
font-size:12px;font-weight:600;border:none;cursor:pointer}
.btn-confirm-rename:hover{background:#a6e3e0}
.btn-cancel-rename{padding:6px 12px;background:#313244;color:#cdd6f4;border-radius:4px;
font-size:12px;border:none;cursor:pointer}
.btn-cancel-rename:hover{background:#3e3e55}

/* headings */
h1{font-size:22px;color:#e0e4f0;margin-bottom:4px;font-weight:600}
h2{font-size:17px;color:#e0e4f0;margin-bottom:12px;font-weight:500}

.empty-msg{color:#7f849c;font-style:italic;padding:20px 0;text-align:center}
.error-msg{color:#f38ba8;background:rgba(243,139,168,0.08);padding:12px;
border-radius:4px;border-left:3px solid #f38ba8;margin-bottom:12px}

/* mermaid diagrams */
.markdown-body .mermaid,.viewer-mermaid .mermaid{background:#181825;
padding:1.5rem;border-radius:6px;margin-bottom:1.5rem;display:flex;
justify-content:center;position:relative}
.mermaid-hint{position:absolute;top:6px;right:10px;font-size:10px;
color:#585b70;pointer-events:none;z-index:1}

/* rich content viewers */
.viewer-image{display:flex;justify-content:center;align-items:center;flex:1;
padding:2rem;min-height:300px}
.viewer-image img{max-width:100%;max-height:80vh;object-fit:contain;
border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.3)}
.viewer-image .image-meta{text-align:center;color:#7f849c;font-size:12px;
margin-top:12px}
.viewer-html-frame{flex:1;border:1px solid #313244;border-radius:6px;
overflow:hidden;min-height:400px;background:#fff}
.viewer-html-frame iframe{width:100%;height:100%;border:none;min-height:600px}
.viewer-mermaid{display:flex;justify-content:center;align-items:center;flex:1;
padding:2rem;min-height:300px}
.viewer-mermaid .mermaid{background:#181825;padding:2rem;border-radius:6px;
display:flex;justify-content:center;width:100%;overflow-x:auto}
.viewer-toolbar{display:flex;align-items:center;gap:8px;padding:8px 0;
margin-bottom:8px;flex-shrink:0}
.viewer-toolbar .badge{display:inline-flex;align-items:center;gap:4px;
padding:4px 10px;background:#272738;border:1px solid #313244;border-radius:4px;
font-size:12px;color:#7f849c}
.viewer-toolbar .badge .icon{color:#94e2d5}
.btn-raw{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;
background:transparent;border:1px solid #313244;border-radius:4px;
font-size:12px;color:#94e2d5;text-decoration:none;
transition:background 150ms ease,border-color 150ms ease}
.btn-raw:hover{background:#2e2e42;border-color:#94e2d5;text-decoration:none}

/* gantt chart */
.viewer-gantt{flex:1;min-height:400px;position:relative}
.gantt-scroll-wrap{overflow:hidden;border-radius:6px;border:1px solid #313244}
.gantt-toolbar{display:flex;align-items:center;gap:12px;padding:8px 0;margin-bottom:8px}
.gantt-title{font-size:16px;font-weight:600;color:#e0e4f0}
.gantt-hint{font-size:11px;color:#7f849c;margin-left:auto}
.gantt-save-btn{padding:5px 14px;background:#94e2d5;color:#1e1e2e;border:none;
border-radius:4px;font-size:12px;font-weight:600;cursor:pointer;
transition:background 150ms ease,opacity 150ms ease}
.gantt-save-btn:hover{background:#a6e3e0}
.gantt-save-btn:disabled{opacity:0.4;cursor:default}
.gantt-tooltip{position:absolute;background:#272738;border:1px solid #313244;
border-radius:6px;padding:10px 14px;font-size:12px;color:#cdd6f4;
pointer-events:none;z-index:100;max-width:260px;line-height:1.5;
box-shadow:0 4px 12px rgba(0,0,0,0.4)}
.gantt-tooltip strong{color:#e0e4f0;font-size:13px}
.gantt-tip-section{color:#94e2d5;font-size:11px}
.gantt-tip-dur{color:#7f849c;font-size:11px}

/* csv table viewer */
.viewer-csv{padding:24px 32px;flex:1;overflow:auto}
.csv-table{width:100%;border-collapse:collapse;font-size:13px;font-family:'Monaco','Menlo','Ubuntu Mono',monospace}
.csv-table thead th{position:sticky;top:0;z-index:1;text-align:left;padding:8px 12px;
background:#272738;color:#e0e4f0;font-weight:600;font-size:12px;
border-bottom:2px solid #313244;white-space:nowrap}
.csv-table tbody td{padding:6px 12px;border-bottom:1px solid #232334;color:#cdd6f4;
white-space:nowrap;max-width:400px;overflow:hidden;text-overflow:ellipsis}
.csv-table tbody tr:hover td{background:#2e2e42}
.csv-row-num{color:#585b70;text-align:right;font-size:11px;user-select:none;
padding-right:16px !important;border-right:1px solid #313244}
.csv-stats{display:flex;gap:16px;font-size:12px;color:#7f849c;margin-top:8px}
.viewer-csv-inline{padding:0;margin-bottom:1.5rem;border:1px solid #313244;border-radius:6px;overflow:auto}
.viewer-csv-inline .csv-table{font-size:12px}
.viewer-csv-inline .csv-stats{padding:6px 12px;border-top:1px solid #313244;background:#1e1e2e}

/* embedded openapi block inside markdown */
.embedded-openapi{margin:1.5rem 0;border:1px solid #313244;border-radius:8px;
background:#181825;overflow:hidden}
.embedded-openapi .viewer-openapi{padding:18px 22px}
.embedded-openapi .oas-header{margin-bottom:1rem}
.embedded-openapi .oas-header h1{font-size:18px}
/* Defaults match a standalone browser render — light background + dark text.
   The source's own body styles (via @scope) override these when set, so dark-
   themed source HTML still renders dark. The point is that neutral source HTML
   (no body bg/color) doesn't disappear into Stash's dark theme. */
.embedded-html{margin:1.5rem 0;padding:18px 22px;border:1px solid #313244;
border-radius:8px;background:#fff;color:#1e1e2e;color-scheme:light;overflow:auto}
/* Trim outside margins along the last-child chain so neither the source's
   own stacking margins (e.g. `section { margin-bottom: 2rem }`) nor UA
   defaults on deep-nested last children (e.g. `<ol>` inside the final
   section) create dead space at the bottom of the wrapper. Same for the
   first-child chain at the top. Specificity (0,2,0) and higher beats the
   source's `:scope <el>` rules (0,1,1). Three levels covers the typical
   nesting: wrapper > section > ol > li. */
.embedded-html > *:first-child,
.embedded-html > *:first-child > *:first-child,
.embedded-html > *:first-child > *:first-child > *:first-child{margin-top:0}
.embedded-html > *:last-child,
.embedded-html > *:last-child > *:last-child,
.embedded-html > *:last-child > *:last-child > *:last-child{margin-bottom:0}

/* openapi schema viewer */
.viewer-openapi{padding:24px 32px}
.oas-header{margin-bottom:2rem}
.oas-header h1{color:#e0e4f0;font-size:26px;margin:0 0 8px}
.oas-meta{display:flex;gap:8px;margin-bottom:8px}
.oas-badge{padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600}
.oas-badge-ver{background:#313244;color:#94e2d5}
.oas-desc{color:#a6adc8;font-size:14px;margin:0}
.oas-tag-group{margin-bottom:2rem}
.oas-tag-title{color:#e0e4f0;font-size:18px;font-weight:600;
margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid #313244}
.oas-op{border:1px solid #313244;border-radius:6px;margin-bottom:6px;
background:#1e1e2e;overflow:hidden}
.oas-op[open]{background:#181825}
.oas-op-summary{display:flex;align-items:center;gap:10px;padding:10px 14px;
cursor:pointer;list-style:none;font-size:13px}
.oas-op-summary::-webkit-details-marker{display:none}
.oas-method{padding:4px 10px;border-radius:4px;font-size:11px;
font-weight:700;font-family:monospace;min-width:56px;text-align:center;
flex-shrink:0}
.oas-schema-badge{background:#585b70 !important;color:#cdd6f4 !important}
.oas-path{color:#cdd6f4;font-family:monospace;font-size:13px}
.oas-summary{color:#7f849c;font-size:13px;margin-left:auto;text-align:right}
.oas-op-body{padding:14px 20px;border-top:1px solid #313244}
.oas-op-desc{color:#a6adc8;font-size:13px;margin:0 0 12px;white-space:pre-wrap}
.oas-op-id{font-size:11px;color:#585b70;margin-bottom:12px;font-family:monospace}
.oas-label{color:#7f849c}
.oas-section{margin-bottom:16px}
.oas-section-title{color:#94e2d5;font-size:13px;font-weight:600;
margin:0 0 8px;display:flex;align-items:center;gap:8px}
.oas-media-type{font-size:11px;color:#7f849c;font-weight:400;font-family:monospace}
.oas-params{width:100%;border-collapse:collapse;font-size:12px}
.oas-params th{text-align:left;padding:6px 10px;color:#7f849c;font-weight:500;
border-bottom:1px solid #313244;font-size:11px;text-transform:uppercase}
.oas-params td{padding:6px 10px;border-bottom:1px solid #232334;color:#cdd6f4}
.oas-pname{font-family:monospace;color:#89b4fa}
.oas-pname.oas-required{color:#f38ba8}
.oas-pname.oas-required::after{content:" *";color:#f38ba8}
.oas-ptype{font-family:monospace;color:#94e2d5;font-size:12px}
.oas-in-badge{padding:2px 6px;border-radius:3px;font-size:10px;
background:#272738;color:#7f849c;font-family:monospace}
.oas-response{display:flex;align-items:center;gap:10px;padding:6px 0;
border-bottom:1px solid #232334}
.oas-response:last-child{border-bottom:none}
.oas-resp-code{font-family:monospace;font-weight:700;font-size:12px;
padding:2px 8px;border-radius:4px;min-width:36px;text-align:center}
.oas-code-2xx{background:rgba(166,227,161,0.15);color:#a6e3a1}
.oas-code-4xx{background:rgba(243,139,168,0.15);color:#f38ba8}
.oas-code-other{background:rgba(127,132,156,0.15);color:#7f849c}
.oas-resp-desc{color:#a6adc8;font-size:13px}
.oas-schema-block{background:#11111b;border:1px solid #232334;
border-radius:4px;padding:10px 14px;overflow-x:auto}
.oas-props{width:100%;border-collapse:collapse;font-size:12px}
.oas-props td{padding:4px 10px;border-bottom:1px solid #232334;color:#cdd6f4}
.oas-ref{font-family:monospace;color:#cba6f7;font-size:12px}
.oas-schema-def .oas-method{min-width:66px}
.toc-count{margin-left:auto;font-size:11px;color:#585b70;
background:#272738;padding:1px 6px;border-radius:8px}
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
function showRename(btn){
  btn.style.display='none';
  btn.nextElementSibling.style.display='block';
}
function hideRename(btn){
  var f=btn.closest('.rename-form');f.style.display='none';
  f.previousElementSibling.style.display='flex';
}
function _getExpandedDirs(){
  try{return JSON.parse(localStorage.getItem('stash_expanded_dirs'))||[];}
  catch(e){return [];}
}
function _saveExpandedDirs(dirs){
  try{localStorage.setItem('stash_expanded_dirs',JSON.stringify(dirs));}catch(e){}
}
function _restoreTreeState(){
  var saved=_getExpandedDirs();
  document.querySelectorAll('.tree-root details[data-path]').forEach(function(d){
    if(saved.indexOf(d.getAttribute('data-path'))!==-1){d.setAttribute('open','');}
  });
}
function _trackTreeToggles(){
  document.querySelector('.tree-root').addEventListener('toggle',function(e){
    var d=e.target;if(d.tagName!=='DETAILS'||!d.dataset.path)return;
    var dirs=_getExpandedDirs();var p=d.dataset.path;
    if(d.open){if(dirs.indexOf(p)===-1)dirs.push(p);}
    else{dirs=dirs.filter(function(x){return x!==p;});}
    _saveExpandedDirs(dirs);
  },true);
}
function filterTree(query){
  var files=document.querySelectorAll('.tree-file');
  var dirs=document.querySelectorAll('.tree-root details');
  query=query.toLowerCase();
  if(!query){
    files.forEach(function(f){f.style.display='flex';});
    dirs.forEach(function(d){d.style.display='';d.removeAttribute('open');});
    _restoreTreeState();
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
var _searchTimer=null;
var _vectorEnabled=!!document.querySelector('[data-vector-search]');
function _escHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
function handleSearch(query){
  if(!_vectorEnabled){filterTree(query);return;}
  clearTimeout(_searchTimer);
  var box=document.getElementById('search-results');
  var tree=document.querySelector('.tree-root');
  if(!query){
    if(box)box.classList.remove('active');
    if(tree)tree.style.display='';
    filterTree('');
    return;
  }
  _searchTimer=setTimeout(function(){
    if(box){
      box.innerHTML='<div class="search-loading">'
        +'<div class="search-spinner"></div>Searching\u2026</div>';
      box.classList.add('active');
      if(tree)tree.style.display='none';
    }
    fetch('/ui/search?q='+encodeURIComponent(query))
      .then(function(r){return r.json();})
      .then(function(data){
        if(!box)return;
        if(data.results&&data.results.length>0){
          var h='';
          data.results.forEach(function(r){
            var snippet=r.content||'';
            if(snippet.length>120)snippet=snippet.substring(0,120)+'\u2026';
            h+='<a class="search-result" href="/ui/browse/'+encodeURIComponent(r.file_path)+'">'
              +'<span class="search-result-path">'+_escHtml(r.file_path)+'</span>'
              +'<span class="search-result-snippet">'+_escHtml(snippet)+'</span>'
              +'</a>';
          });
          box.innerHTML=h;
        }else if(data.indexing){
          box.innerHTML='<div class="search-no-results">'
            +'Search index is being rebuilt\u2026 please try again shortly.</div>';
        }else{
          box.innerHTML='<div class="search-no-results">No results found</div>';
        }
        box.classList.add('active');
        if(tree)tree.style.display='none';
      })
      .catch(function(){filterTree(query);});
  },300);
}
var _unsaved=false;
(function(){
  var ta=document.querySelector('.editor-area');
  if(ta){ta.addEventListener('input',function(){
    _unsaved=true;
    var et=document.querySelector('.mode-tab.active');
    if(et&&!et.querySelector('.unsaved-dot')){
      var dot=document.createElement('span');dot.className='unsaved-dot';et.appendChild(dot);
    }
  });}
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
      var el=document.querySelector('.mode-tab:not(.active)');if(el)el.click();
    }
    if((e.ctrlKey||e.metaKey)&&e.key==='b'){
      e.preventDefault();toggleSidebar();
    }
  });
  _restoreTreeState();
  _trackTreeToggles();
  var _sb=document.querySelector('.sidebar');
  if(_sb){
    var _saved=sessionStorage.getItem('stash_sidebar_scroll');
    if(_saved)_sb.scrollTop=parseInt(_saved,10);
    window.addEventListener('beforeunload',function(){
      sessionStorage.setItem('stash_sidebar_scroll',_sb.scrollTop);
    });
  }
})();

function _initPanZoom(wrap){
  if(!wrap.firstElementChild)return;
  var child=wrap.firstElementChild;
  var scale=1,tx=0,ty=0,panning=false,px=0,py=0,ptx=0,pty=0;
  var MIN=0.2,MAX=5;
  child.style.transformOrigin='0 0';
  function apply(){child.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')';}
  function zoomAt(cx,cy,factor){
    var ns=Math.min(Math.max(scale*factor,MIN),MAX);
    var rect=wrap.getBoundingClientRect();
    var mx=cx-rect.left, my=cy-rect.top;
    tx=mx-(mx-tx)*(ns/scale); ty=my-(my-ty)*(ns/scale);
    scale=ns; apply();
  }
  // Wheel handler:
  //  - ctrlKey set → trackpad pinch (browser convention) or ctrl+wheel: zoom.
  //    Uses an exponential curve so pinch tracks the gesture smoothly instead
  //    of stepping in fixed 10% increments.
  //  - Otherwise → if we're zoomed in, pan the embed using deltaX/deltaY
  //    (handles two-finger trackpad pan). At scale=1 we let the wheel pass
  //    through so the page can scroll normally past the diagram.
  wrap.addEventListener('wheel',function(e){
    if(e.ctrlKey){
      e.preventDefault();
      zoomAt(e.clientX,e.clientY,Math.exp(-e.deltaY*0.01));
      return;
    }
    if(scale>1.001){
      e.preventDefault();
      tx-=e.deltaX; ty-=e.deltaY; apply();
    }
  },{passive:false});
  // Safari trackpad gesture events — same logic, different API.
  var gestureScale=1;
  wrap.addEventListener('gesturestart',function(e){e.preventDefault();gestureScale=scale;});
  wrap.addEventListener('gesturechange',function(e){
    e.preventDefault();
    var ns=Math.min(Math.max(gestureScale*e.scale,MIN),MAX);
    zoomAt(e.clientX,e.clientY,ns/scale);
  });
  wrap.addEventListener('gestureend',function(e){e.preventDefault();});
  wrap.addEventListener('mousedown',function(e){
    if(e.target.closest('a'))return;
    panning=true;px=e.clientX;py=e.clientY;ptx=tx;pty=ty;
    wrap.style.cursor='grabbing';e.preventDefault();
  });
  document.addEventListener('mousemove',function(e){
    if(!panning)return;
    tx=ptx+(e.clientX-px);ty=pty+(e.clientY-py);apply();
  });
  document.addEventListener('mouseup',function(){
    if(panning){panning=false;wrap.style.cursor='grab';}
  });
  // Touch handlers for actual touchscreens (iPad, hybrid laptops). One finger
  // pans; two fingers pinch-zoom around the midpoint.
  var t1=null,t2=null,touchStartDist=0,touchStartScale=1,touchStartMid=null;
  function dist(a,b){var dx=a.clientX-b.clientX,dy=a.clientY-b.clientY;return Math.hypot(dx,dy);}
  function mid(a,b){return{x:(a.clientX+b.clientX)/2,y:(a.clientY+b.clientY)/2};}
  wrap.addEventListener('touchstart',function(e){
    if(e.touches.length===1){
      t1=e.touches[0];t2=null;
      px=t1.clientX;py=t1.clientY;ptx=tx;pty=ty;panning=true;
    }else if(e.touches.length===2){
      panning=false;
      t1=e.touches[0];t2=e.touches[1];
      touchStartDist=dist(t1,t2);touchStartScale=scale;touchStartMid=mid(t1,t2);
    }
    if(e.touches.length>0)e.preventDefault();
  },{passive:false});
  wrap.addEventListener('touchmove',function(e){
    if(e.touches.length===1&&panning){
      e.preventDefault();
      tx=ptx+(e.touches[0].clientX-px);ty=pty+(e.touches[0].clientY-py);apply();
    }else if(e.touches.length===2&&touchStartDist>0){
      e.preventDefault();
      var d=dist(e.touches[0],e.touches[1]);
      var ns=Math.min(Math.max(touchStartScale*(d/touchStartDist),MIN),MAX);
      zoomAt(touchStartMid.x,touchStartMid.y,ns/scale);
    }
  },{passive:false});
  wrap.addEventListener('touchend',function(e){
    if(e.touches.length<2){touchStartDist=0;}
    if(e.touches.length===0){panning=false;}
  });
  wrap.style.cursor='grab';
  wrap.style.overflow='hidden';
}

if(typeof mermaid!=='undefined'){
  mermaid.initialize({
    startOnLoad:false,
    theme:'dark',
    themeVariables:{
      primaryColor:'#94e2d5',
      primaryTextColor:'#cdd6f4',
      primaryBorderColor:'#313244',
      lineColor:'#7f849c',
      secondaryColor:'#272738',
      tertiaryColor:'#1e1e2e',
      background:'#181825',
      mainBkg:'#272738',
      nodeBorder:'#94e2d5',
    }
  });
  document.querySelectorAll('pre code.language-mermaid').forEach(function(block){
    var pre=block.parentElement;
    var container=document.createElement('div');
    container.className='mermaid';
    container.textContent=block.textContent;
    pre.parentElement.replaceChild(container,pre);
  });
  mermaid.run().then(function(){
    document.querySelectorAll('.mermaid').forEach(function(el){
      _initPanZoom(el);
      var hint=document.createElement('span');
      hint.className='mermaid-hint';
      hint.textContent='Pinch or ⌃scroll to zoom · Drag to pan';
      el.appendChild(hint);
    });
  });
}

// Gantt code blocks in markdown
if(typeof StashGantt!=='undefined'){
  document.querySelectorAll('pre code.language-gantt').forEach(function(block){
    var yaml=block.textContent;
    var pre=block.parentElement;
    var container=document.createElement('div');
    container.className='viewer-gantt';
    container.textContent='Loading Gantt chart…';
    pre.parentElement.replaceChild(container,pre);
    fetch('/ui/parse-gantt',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'yaml='+encodeURIComponent(yaml)})
    .then(function(r){if(!r.ok)throw new Error('Server error');return r.json();})
    .then(function(d){container.textContent='';StashGantt.render(container,d,{readOnly:true});})
    .catch(function(e){container.textContent='Gantt parse error: '+e.message;});
  });
}

if(typeof hljs!=='undefined'){hljs.highlightAll();}

// Scroll-spy for TOC
(function(){
  var tocLinks=document.querySelectorAll('#toc-nav .toc a');
  if(!tocLinks.length)return;
  var viewer=document.querySelector('.center-content');
  if(!viewer)return;
  var linkMap={};
  tocLinks.forEach(function(a){
    var href=a.getAttribute('href');
    if(href&&href.startsWith('#')){linkMap[href.slice(1)]=a;}
  });
  var headingIds=Object.keys(linkMap);
  var currentActive=null;
  var observer=new IntersectionObserver(function(entries){
    entries.forEach(function(entry){
      if(entry.isIntersecting){
        if(currentActive)currentActive.classList.remove('active');
        var link=linkMap[entry.target.id];
        if(link){link.classList.add('active');currentActive=link;}
      }
    });
  },{root:viewer,rootMargin:'0px 0px -80% 0px',threshold:0});
  headingIds.forEach(function(id){
    var el=document.getElementById(id);if(el)observer.observe(el);
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
    hide_edit: bool = False,
) -> str:
    """Wrap content in the three-panel layout."""
    right_panel = f'<aside class="right-panel">{right}</aside>' if right else ""

    # Build mode-switch tabs if viewing/editing a file
    mode_tabs = ""
    if path:
        view_cls = "mode-tab active" if mode == "view" else "mode-tab"
        escaped_path = html.escape(path)
        edit_tab = "" if hide_edit else (
            f'<a class="{"mode-tab active" if mode == "edit" else "mode-tab"}" '
            f'href="/ui/edit/{escaped_path}">'
            f'{_icon("pencil")} Edit</a>'
        )
        mode_tabs = (
            '<div class="mode-tabs">'
            f'<a class="{view_cls}" href="/ui/browse/{escaped_path}">'
            f'{_icon("eye")} View</a>'
            f'{edit_tab}'
            "</div>"
        )

    toolbar_right_items = ""
    toolbar_right_items += (
        f'<button class="panel-toggle" onclick="toggleSidebar()" '
        f'title="Toggle sidebar">{_icon("panel-left")}</button>'
    )
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
<link rel="stylesheet" href="{_static_url("vendor/github-dark.min.css")}">
<script src="{_static_url("vendor/highlight.min.js")}"></script>
<script src="{_static_url("vendor/languages/terraform.min.js")}"></script>
<script src="{_static_url("vendor/mermaid.min.js")}"></script>
<script src="{_static_url("vendor/stash-gantt.js")}"></script>
</head>
<body>
<div class="app">
<header class="top-bar">
<div class="top-bar-left">
<svg class="app-wordmark" width="220" height="44" viewBox="0 0 320 64" fill="none" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="8" width="38" height="48" rx="8" fill="#272738" stroke="#94e2d5" stroke-width="2"/><rect x="7" y="14" width="28" height="34" rx="5" fill="#1e1e2e" stroke="#313244" stroke-width="1"/><path d="M13 18 L13 42 L31 42 L31 24 L25 18 Z" fill="#272738" stroke="#94e2d5" stroke-width="1.2" stroke-linejoin="round"/><path d="M25 18 L25 24 L31 24" fill="none" stroke="#94e2d5" stroke-width="1.2" stroke-linejoin="round"/><line x1="16" y1="28" x2="27" y2="28" stroke="#585b70" stroke-width="1.2" stroke-linecap="round"/><line x1="16" y1="32" x2="28" y2="32" stroke="#4a4b5e" stroke-width="1" stroke-linecap="round"/><line x1="16" y1="36" x2="24" y2="36" stroke="#4a4b5e" stroke-width="1" stroke-linecap="round"/><circle cx="52" cy="16" r="5" fill="#272738" stroke="#94e2d5" stroke-width="1.5"/><circle cx="52" cy="16" r="2" fill="#94e2d5"/><circle cx="52" cy="32" r="5" fill="#272738" stroke="#94e2d5" stroke-width="1.5"/><circle cx="52" cy="32" r="2" fill="#94e2d5"/><circle cx="52" cy="48" r="5" fill="#272738" stroke="#94e2d5" stroke-width="1.5"/><circle cx="52" cy="48" r="2" fill="#94e2d5"/><line x1="40" y1="18" x2="47" y2="16" stroke="#94e2d5" stroke-width="1" opacity="0.4"/><line x1="40" y1="32" x2="47" y2="32" stroke="#94e2d5" stroke-width="1" opacity="0.4"/><line x1="40" y1="46" x2="47" y2="48" stroke="#94e2d5" stroke-width="1" opacity="0.4"/><circle cx="21" cy="14" r="2.5" fill="#1e1e2e" stroke="#94e2d5" stroke-width="1"/><circle cx="21" cy="14" r="1" fill="#94e2d5"/><text x="70" y="41" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',sans-serif" font-size="32" font-weight="600" fill="#cdd6f4" letter-spacing="-0.5">stash</text><text x="147" y="41" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',sans-serif" font-size="32" font-weight="300" fill="#94e2d5" letter-spacing="-0.5">-mcp</text></svg>
</div>
<div class="top-bar-right">{toolbar_right_items}</div>
</header>
<div class="layout">
<nav class="sidebar">{sidebar}</nav>
<div class="center">
{mode_tabs}
<div class="center-content"><div class="center-inner">{center}</div></div>
</div>
{right_panel}
</div>
</div>
<script>{_JS}</script>
</body></html>"""


def _sidebar_html(
    filesystem: FileSystem,
    active: str = "",
    search_enabled: bool = False,
    read_only: bool = False,
) -> str:
    """Build sidebar HTML with header + search + tree."""
    tree = _build_tree_html(filesystem, active=active)
    vector_attr = ' data-vector-search="true"' if search_enabled else ""
    placeholder = "Search content\u2026" if search_enabled else "Search files..."
    results_div = '<div id="search-results" class="search-results"></div>' if search_enabled else ""
    new_doc_btn = (
        "" if read_only else f'<a href="/ui/new" class="btn-new">{_icon("plus")} New Document</a>'
    )
    return (
        '<div class="sidebar-header">'
        f'{new_doc_btn}'
        f'<div class="search-box"{vector_attr}>'
        f'<input type="text" id="tree-search" class="search-input" '
        f'placeholder="{placeholder}" aria-label="Search" '
        f'oninput="handleSearch(this.value)">'
        f"{results_div}"
        "</div>"
        "</div>"
        f'<div class="tree-root">{tree if tree else "<p class=empty-msg>No files yet</p>"}</div>'
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def create_ui_router(
    filesystem: FileSystem,
    search_engine=None,
    read_only: bool = False,
) -> APIRouter:
    """Create UI router with content browser & editor.

    Args:
        filesystem: Filesystem instance
        search_engine: Optional SearchEngine for vector search
        read_only: When True, editing UI elements are hidden and write
            endpoints return HTTP 403.

    Returns:
        FastAPI router for UI
    """
    _search_enabled = search_engine is not None
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
        sidebar = _sidebar_html(filesystem, active=path, search_enabled=_search_enabled, read_only=read_only)
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
            entries = _sort_entries(entries)
            rows = ""
            for name, is_dir in entries:
                child = f"{path}/{name}" if path else name
                escaped = html.escape(name)
                escaped_child = html.escape(child)
                if is_dir:
                    rows += (
                        f'<tr><td class="dir"><a href="/ui/browse/{escaped_child}">'
                        f"{_icon('folder')} {escaped}/</a></td>"
                        "<td>directory</td><td>\u2014</td><td>\u2014</td></tr>"
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
                        size = "\u2014"
                        mtime = "\u2014"
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
            suffix = PurePosixPath(path).suffix.lower()
            is_binary = suffix in _IMAGE_EXTENSIONS
            content = ""
            if not is_binary:
                try:
                    content = filesystem.read_file(path)
                except Exception as exc:
                    center = (
                        f'<div class="breadcrumbs">{breadcrumbs}</div>'
                        f'<div class="error-msg">Error reading file: {html.escape(str(exc))}</div>'
                    )
                    return _page("Error", sidebar, center)

            escaped_content = html.escape(content) if content else ""
            toc_html = ""
            escaped_path = html.escape(path)

            if suffix in _IMAGE_EXTENSIONS:
                raw_url = f"/ui/raw/{escaped_path}"
                mime = _mime_type(path)
                center = (
                    f'<div class="viewer-toolbar">'
                    f'<span class="badge">{_icon("image")} {html.escape(mime)}</span>'
                    f'<a href="{raw_url}" target="_blank" class="btn-raw">'
                    f'{_icon("external-link")} Open original</a></div>'
                    f'<div class="viewer-image">'
                    f'<div><img src="{raw_url}" alt="{html.escape(PurePosixPath(path).name)}">'
                    f'</div></div>'
                )
            elif suffix in _SVG_EXTENSIONS:
                raw_url = f"/ui/raw/{escaped_path}"
                center = (
                    f'<div class="viewer-toolbar">'
                    f'<span class="badge">{_icon("image")} image/svg+xml</span>'
                    f'<a href="{raw_url}" target="_blank" class="btn-raw">'
                    f'{_icon("external-link")} Open original</a></div>'
                    f'<div class="viewer-image">'
                    f'<div><img src="{raw_url}" alt="{html.escape(PurePosixPath(path).name)}">'
                    f'</div></div>'
                )
            elif suffix in _HTML_EXTENSIONS:
                b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
                raw_url = f"/ui/raw/{escaped_path}"
                center = (
                    f'<div class="viewer-toolbar">'
                    f'<span class="badge">{_icon("globe")} text/html</span>'
                    f'<a href="{raw_url}" target="_blank" class="btn-raw">'
                    f'{_icon("external-link")} Open in new tab</a></div>'
                    f'<div class="viewer-html-frame">'
                    f'<iframe src="data:text/html;base64,{b64}" '
                    f'sandbox="allow-scripts" '
                    f'title="{html.escape(PurePosixPath(path).name)}"></iframe></div>'
                )
            elif suffix in _MERMAID_EXTENSIONS:
                center = (
                    f'<div class="viewer-toolbar">'
                    f'<span class="badge">{_icon("git-branch")} Mermaid diagram</span></div>'
                    f'<div class="viewer-mermaid">'
                    f'<div class="mermaid">{escaped_content}</div></div>'
                )
            elif suffix in _GANTT_EXTENSIONS:
                gantt_data = None
                gantt_error = False
                try:
                    gantt_data = _yaml.safe_load(content)
                except Exception as exc:
                    gantt_error = True
                    center = (
                        f'<div class="error-msg">Invalid YAML: {html.escape(str(exc))}</div>'
                        f'<div class="viewer-content"><pre>{escaped_content}</pre></div>'
                    )
                if gantt_data is not None:
                    js_data = _json.dumps(gantt_data, default=str).replace("</", "<\\/")
                    js_path = _json.dumps(path).replace("</", "<\\/")
                    ro_flag = "true" if read_only else "false"
                    center = (
                        f'<div class="viewer-gantt" id="gantt-root"></div>'
                        f'<script>'
                        f'document.addEventListener("DOMContentLoaded",function(){{'
                        f'StashGantt.render(document.getElementById("gantt-root"),'
                        f'{js_data},{{savePath:{js_path},readOnly:{ro_flag}}});'
                        f'}});</script>'
                    )
                elif not gantt_error:
                    center = (
                        f'<div class="viewer-content"><pre>{escaped_content}</pre></div>'
                    )
            elif path.endswith((".md", ".markdown")):
                base_dir = str(PurePosixPath(path).parent)
                if base_dir == ".":
                    base_dir = ""
                rendered, toc_html = _render_markdown(content, filesystem, base_dir)
                rendered = _rewrite_relative_urls(rendered, base_dir)
                center = (
                    f'<div class="viewer-content markdown-body">{rendered}</div>'
                )
            elif suffix == ".json":
                oas_rendered = False
                try:
                    parsed = _json.loads(content)
                    if isinstance(parsed, dict) and "openapi" in parsed:
                        center, toc_html = _render_openapi(parsed)
                        oas_rendered = True
                except (ValueError, TypeError):
                    pass
                if not oas_rendered:
                    center = (
                        f'<div class="viewer-content"><pre>{escaped_content}</pre></div>'
                    )
            elif suffix in _CSV_EXTENSIONS:
                try:
                    center, toc_html = _render_csv(content, suffix)
                except Exception:
                    center = (
                        f'<div class="viewer-content"><pre>{escaped_content}</pre></div>'
                    )
            else:
                center = (
                    f'<div class="viewer-content"><pre>{escaped_content}</pre></div>'
                )

            # right panel — TOC (markdown only) + metadata accordion + actions
            try:
                st = full.stat()
                size = _human_size(st.st_size)
                mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).strftime(
                    "%b %-d, %Y, %I:%M %p"
                )
            except Exception:
                size = "\u2014"
                mtime = "\u2014"
            _meta_body = (
                '<div class="meta-field">'
                '<div class="meta-field-label">File Path</div>'
                f'<div class="meta-field-path">{html.escape(path)}</div>'
                '</div>'
                '<div class="meta-field">'
                '<div class="meta-field-label">File Size</div>'
                f'<div class="meta-field-value">{size}</div>'
                '</div>'
                '<div class="meta-field">'
                '<div class="meta-field-label">MIME Type</div>'
                f'<div class="meta-field-value">{html.escape(_mime_type(path))}</div>'
                '</div>'
                '<div class="meta-field">'
                '<div class="meta-field-label">Last Modified</div>'
                f'<div class="meta-field-value">{mtime}</div>'
                '</div>'
            )
            if not is_binary:
                words = len(content.split())
                chars = len(content)
                _meta_body += (
                    '<div class="meta-field">'
                    '<div class="meta-stats-heading">Content Stats</div>'
                    f'<div class="meta-stat-row"><span class="label">Characters:</span>'
                    f'<span class="value">{chars}</span></div>'
                    f'<div class="meta-stat-row"><span class="label">Words:</span>'
                    f'<span class="value">{words}</span></div>'
                    '</div>'
                )
            _action_stack = "" if read_only else (
                '<div class="action-stack">'
                f'<button class="btn-rename" onclick="showRename(this)">'
                f'{_icon("pen-line")} Rename / Move</button>'
                f'<form method="post" action="/ui/move/{html.escape(path)}" '
                f'class="rename-form">'
                f'<input type="text" name="destination" class="rename-input" '
                f'value="{html.escape(path)}">'
                '<div class="confirm-row">'
                '<button type="submit" class="btn-confirm-rename">Confirm</button>'
                '<button type="button" class="btn-cancel-rename" '
                'onclick="hideRename(this)">Cancel</button>'
                "</div></form>"
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
            if toc_html:
                # Markdown with headings: scrollable TOC + collapsed accordion
                right = (
                    '<div class="right-toc">'
                    f'<h2 class="toc-heading">{_icon("list")} On This Page</h2>'
                    f'<nav class="toc-nav" id="toc-nav">{toc_html}</nav>'
                    '</div>'
                    '<div class="right-meta-accordion">'
                    '<details class="meta-accordion">'
                    f'<summary class="meta-accordion-header">Document Metadata {_icon("chevron-right")}</summary>'
                    f'<div class="meta-accordion-body">{_meta_body}</div>'
                    '</details>'
                    '</div>'
                    f'<div class="right-bottom">{_action_stack}</div>'
                )
            else:
                # Non-markdown or no headings: no TOC, metadata expanded
                right = (
                    '<div class="right-meta-accordion">'
                    '<details class="meta-accordion" open>'
                    f'<summary class="meta-accordion-header">Document Metadata {_icon("chevron-right")}</summary>'
                    f'<div class="meta-accordion-body">{_meta_body}</div>'
                    '</details>'
                    '</div>'
                    f'<div class="right-bottom">{_action_stack}</div>'
                )
            hide_edit = read_only or is_binary
            return _page(
                PurePosixPath(path).name, sidebar, center, right, mode="view", path=path,
                hide_edit=hide_edit,
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

    # --- vector search (JSON for sidebar) ---
    if search_engine is not None:
        from fastapi.responses import JSONResponse

        @router.get("/ui/search")
        async def ui_search(q: str = "", max_results: int = 10):
            """Search content using the vector search engine."""
            if not q.strip():
                return JSONResponse({"results": [], "total": 0})
            results = await search_engine.search(
                q.strip(), max_results=max_results
            )
            return JSONResponse(
                {
                    "results": [
                        {
                            "file_path": r.file_path,
                            "content": r.content[:200] if r.content else "",
                            "score": round(r.score, 3),
                        }
                        for r in results
                    ],
                    "total": len(results),
                    "indexing": search_engine.indexing,
                }
            )

    # --- parse gantt YAML (for markdown embeds) ---
    @router.post("/ui/parse-gantt")
    async def ui_parse_gantt(request: Request, yaml: str = Form(...)):
        """Parse Gantt YAML and return JSON for the client-side renderer."""
        from fastapi.responses import JSONResponse
        try:
            data = _yaml.safe_load(yaml)
            return JSONResponse(_json.loads(_json.dumps(data, default=str)))
        except Exception as exc:
            logger.warning("Gantt YAML parse error: %s", exc)
            return JSONResponse({"error": "Invalid Gantt YAML"}, status_code=400)

    # --- raw file serving (images, SVG, HTML) ---
    @router.get("/ui/raw/{path:path}")
    async def ui_raw(path: str):
        """Serve a raw file with its native MIME type."""
        path = path.strip("/")
        try:
            full = filesystem._resolve_path(path)
        except Exception:
            return Response(content="Invalid path", status_code=400)
        if not full.is_file():
            return Response(content="Not found", status_code=404)
        mime = _mime_type(path)
        try:
            data = full.read_bytes()
        except Exception as exc:
            return Response(content=f"Error: {exc}", status_code=500)
        suffix = PurePosixPath(path).suffix.lower()
        headers: dict[str, str] = {}
        if suffix in _HTML_EXTENSIONS or suffix in _SVG_EXTENSIONS:
            headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
            headers["Content-Disposition"] = "inline"
        return Response(content=data, media_type=mime, headers=headers)

    # --- edit ---
    @router.get("/ui/edit/{path:path}", response_class=HTMLResponse)
    async def ui_edit(path: str) -> str:
        """Edit an existing file."""
        if read_only:
            return Response(content="This Stash-MCP instance is read-only. Set STASH_READ_ONLY=false to enable editing.", status_code=403)
        path = path.strip("/")
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in _IMAGE_EXTENSIONS:
            return RedirectResponse(url=f"/ui/browse/{path}", status_code=302)
        sidebar = _sidebar_html(filesystem, active=path, search_enabled=_search_enabled, read_only=read_only)
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
            f'<form class="editor-form" method="post" action="/ui/save">'
            f'<input type="hidden" name="path" value="{html.escape(path)}">'
            f'<textarea class="editor-area" name="content">{escaped}</textarea>'
            '<div class="action-bar">'
            f'<button type="submit" class="btn btn-save">{_icon("save")} Save</button>'
            f'<a href="/ui/browse/{html.escape(path)}" class="btn btn-discard">'
            f'{_icon("x")} Discard</a>'
            "</div></form>"
        )

        # right panel — no TOC in edit view; metadata expanded by default
        full = filesystem._resolve_path(path)
        try:
            st = full.stat()
            size = _human_size(st.st_size)
            mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).strftime(
                "%b %-d, %Y, %I:%M %p"
            )
        except Exception:
            size = "\u2014"
            mtime = "\u2014"
        words = len(content.split())
        chars = len(content)
        _meta_body = (
            '<div class="meta-field">'
            '<div class="meta-field-label">File Path</div>'
            f'<div class="meta-field-path">{html.escape(path)}</div>'
            '</div>'
            '<div class="meta-field">'
            '<div class="meta-field-label">File Size</div>'
            f'<div class="meta-field-value">{size}</div>'
            '</div>'
            '<div class="meta-field">'
            '<div class="meta-field-label">MIME Type</div>'
            f'<div class="meta-field-value">{html.escape(_mime_type(path))}</div>'
            '</div>'
            '<div class="meta-field">'
            '<div class="meta-field-label">Last Modified</div>'
            f'<div class="meta-field-value">{mtime}</div>'
            '</div>'
            '<div class="meta-field">'
            '<div class="meta-stats-heading">Content Stats</div>'
            f'<div class="meta-stat-row"><span class="label">Characters:</span>'
            f'<span class="value">{chars}</span></div>'
            f'<div class="meta-stat-row"><span class="label">Words:</span>'
            f'<span class="value">{words}</span></div>'
            '</div>'
        )
        right = (
            '<div class="right-meta-accordion">'
            '<details class="meta-accordion" open>'
            f'<summary class="meta-accordion-header">Document Metadata {_icon("chevron-right")}</summary>'
            f'<div class="meta-accordion-body">{_meta_body}</div>'
            '</details>'
            '</div>'
            '<div class="right-bottom">'
            '<div class="action-stack">'
            f'<button class="btn-rename" onclick="showRename(this)">'
            f'{_icon("pen-line")} Rename / Move</button>'
            f'<form method="post" action="/ui/move/{html.escape(path)}" '
            f'class="rename-form">'
            f'<input type="text" name="destination" class="rename-input" '
            f'value="{html.escape(path)}">'
            '<div class="confirm-row">'
            '<button type="submit" class="btn-confirm-rename">Confirm</button>'
            '<button type="button" class="btn-cancel-rename" '
            'onclick="hideRename(this)">Cancel</button>'
            "</div></form>"
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
            "</div></div>"
        )
        return _page(
            f"Edit {path}", sidebar, center, right, mode="edit", path=path,
            hide_edit=read_only,
        )

    # --- new file ---
    @router.get("/ui/new", response_class=HTMLResponse)
    async def ui_new() -> str:
        """Create a new file form."""
        if read_only:
            return Response(content="This Stash-MCP instance is read-only. Set STASH_READ_ONLY=false to enable editing.", status_code=403)
        sidebar = _sidebar_html(filesystem, search_enabled=_search_enabled, read_only=read_only)
        breadcrumbs = _breadcrumbs_html("")
        center = (
            f'<div class="breadcrumbs">{breadcrumbs}</div>'
            "<h1>New Document</h1>"
            '<form method="post" action="/ui/save">'
            '<input class="path-input" type="text" name="path" '
            'placeholder="e.g. notes/meeting.md" required>'
            '<textarea class="editor-area" name="content" '
            'placeholder="Start writing\u2026"></textarea>'
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
        if read_only:
            return Response(content="This Stash-MCP instance is read-only. Set STASH_READ_ONLY=false to enable editing.", status_code=403)
        path = path.strip("/")
        try:
            is_new = not filesystem.file_exists(path)
            filesystem.write_file(path, content)
            emit(CONTENT_CREATED if is_new else CONTENT_UPDATED, path)
        except Exception as exc:
            logger.error(f"UI save error: {exc}")
            # Fall back to edit page with error shown via redirect
            return RedirectResponse(url=f"/ui/edit/{path}", status_code=303)
        return RedirectResponse(url=f"/ui/browse/{path}", status_code=303)

    # --- move / rename ---
    @router.post("/ui/move/{path:path}")
    async def ui_move(path: str, destination: str = Form(...)):
        """Move/rename a file and redirect to the new location."""
        if read_only:
            return Response(content="This Stash-MCP instance is read-only. Set STASH_READ_ONLY=false to enable editing.", status_code=403)
        path = path.strip("/")
        destination = destination.strip("/")
        try:
            filesystem.move_file(path, destination)
            emit(CONTENT_MOVED, destination, source_path=path)
        except Exception as exc:
            logger.error(f"UI move error: {exc}")
            return RedirectResponse(url=f"/ui/browse/{path}", status_code=303)
        return RedirectResponse(url=f"/ui/browse/{destination}", status_code=303)

    # --- delete ---
    @router.post("/ui/delete/{path:path}")
    async def ui_delete(path: str):
        """Delete a file and redirect to parent directory."""
        if read_only:
            return Response(content="This Stash-MCP instance is read-only. Set STASH_READ_ONLY=false to enable editing.", status_code=403)
        path = path.strip("/")
        parent = str(PurePosixPath(path).parent)
        if parent == ".":
            parent = ""
        try:
            filesystem.delete_file(path)
            emit(CONTENT_DELETED, path)
        except Exception as exc:
            logger.error(f"UI delete error: {exc}")
        return RedirectResponse(url=f"/ui/browse/{parent}", status_code=303)

    return router
