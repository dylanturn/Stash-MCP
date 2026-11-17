"""Link extraction and a cached link graph over the content store.

Markdown and HTML documents are scanned for references to other files in the
store — links, images, and ``stash-embed`` blocks. The resulting graph is kept
per source document (``source -> {target: kind}``), which answers "what links
here?" for the UI and is the same data a document map needs.
"""

import html
import logging
import posixpath
import re
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote

import yaml

from .filesystem import FileSystem

logger = logging.getLogger(__name__)

LINK = "link"
EMBED = "embed"

_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
_HTML_EXTENSIONS = frozenset({".html", ".htm"})
#: File types that are scanned for outgoing references.
SOURCE_EXTENSIONS = _MARKDOWN_EXTENSIONS | _HTML_EXTENSIONS

# Documents larger than this are not scanned; reading them on every change
# would cost more than their links are worth.
_MAX_SCAN_BYTES = 2_000_000

# UI routes that address a content path directly, e.g. `/ui/browse/docs/a.md`.
_UI_ROUTE_RE = re.compile(r"^/ui/(?:browse|raw|edit|history)/")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")

_FENCE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n(?P<body>.*?)^(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)

# `](target)` / `](target "title")` / `](<target with spaces>)`. Anchored on
# the closing bracket so a linked image — `[![alt](img.png)](page.md)` —
# yields both targets. One level of balanced parentheses is allowed in a bare
# target, matching what the markdown renderer accepts.
_MD_LINK_RE = re.compile(
    r"\](?P<paren>\()[ \t]*"
    r"(?:<(?P<angle>[^<>\n]*)>|(?P<bare>(?:[^()\s]|\([^()\s]*\))+))"
    r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?[ \t]*\)"
)
_MD_IMAGE_RE = re.compile(r"!\[(?:[^\[\]]|\[[^\[\]]*\])*\](?P<paren>\()")
# `[id]: target` reference definitions. `[^1]:` is a footnote, not a link.
_MD_REFERENCE_RE = re.compile(
    r"^ {0,3}\[(?!\^)[^\]\n]+\]:[ \t]*(?:<(?P<angle>[^<>\n]*)>|(?P<bare>\S+))",
    re.MULTILINE,
)
_HTML_LINK_RE = re.compile(
    r"<(?:a|area)\b[^>]*?\bhref\s*=\s*(?P<q>[\"'])(?P<target>.*?)(?P=q)",
    re.IGNORECASE | re.DOTALL,
)
_HTML_EMBED_RE = re.compile(
    r"<(?:img|source|video|audio|iframe|embed|script)\b[^>]*?\bsrc\s*=\s*"
    r"(?P<q>[\"'])(?P<target>.*?)(?P=q)"
    r"|<link\b[^>]*?\bhref\s*=\s*(?P<q2>[\"'])(?P<target2>.*?)(?P=q2)"
    r"|<object\b[^>]*?\bdata\s*=\s*(?P<q3>[\"'])(?P<target3>.*?)(?P=q3)",
    re.IGNORECASE | re.DOTALL,
)

_MD_TITLE_RE = re.compile(r"^ {0,3}#[ \t]+(?P<title>.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_HTML_TITLE_RE = re.compile(r"<title\b[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_MD_LINK_TEXT_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


@dataclass(frozen=True)
class Backlink:
    """A document that references another document."""

    path: str
    title: str | None
    kind: str


@dataclass(frozen=True)
class OutgoingLink:
    """A file that a document references. `exists` is False for a broken link."""

    path: str
    kind: str
    exists: bool


@dataclass(frozen=True)
class LinkSnapshot:
    """The link graph at one moment: `source -> {target: kind}` plus all files."""

    links: dict[str, dict[str, str]]
    files: frozenset[str]


@dataclass(frozen=True)
class BrokenLink:
    """A link that stopped reaching its target because of a move.

    `file` is the document to edit (at its current path), `old_target` the
    path the link reached before the move, and `new_target` where that
    content lives now. The two targets are equal when it was the linking
    document that moved, taking its relative links with it.
    """

    file: str
    old_target: str
    new_target: str


@dataclass(frozen=True)
class _Document:
    signature: tuple[int, int]
    title: str | None
    links: dict[str, str]


def resolve_target(target: str, base_dir: str) -> str | None:
    """Resolve a raw link target to a content-store-relative path.

    Returns None for anything that does not address a file in the store:
    external URLs, in-page anchors, and paths that climb out of the root.
    A leading `/` is rooted at the content store, as it is for embeds.
    """
    target = html.unescape(target).strip()
    if not target or target.startswith(("#", "//")) or _SCHEME_RE.match(target):
        return None
    target = unquote(re.split(r"[#?]", target, maxsplit=1)[0])
    if not target:
        return None
    if target.startswith("/"):
        joined = _UI_ROUTE_RE.sub("", target).lstrip("/")
    elif base_dir:
        joined = posixpath.join(base_dir, target)
    else:
        joined = target
    if not joined:
        return None
    normalized = posixpath.normpath(joined)
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        return None
    return normalized


def _clean_title(raw: str) -> str | None:
    title = _MD_LINK_TEXT_RE.sub(r"\1", raw)
    title = re.sub(r"[`*]", "", title)
    title = " ".join(html.unescape(title).split())
    return title or None


def _embed_src(body: str) -> str | None:
    try:
        config = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    src = config.get("src") if isinstance(config, dict) else None
    return src if isinstance(src, str) and src else None


def _scan_html(text: str) -> list[tuple[str, str]]:
    found = [(m.group("target"), LINK) for m in _HTML_LINK_RE.finditer(text)]
    for m in _HTML_EMBED_RE.finditer(text):
        found.append((m.group("target") or m.group("target2") or m.group("target3") or "", EMBED))
    return found


def _scan_markdown(text: str) -> tuple[list[tuple[str, str]], str | None]:
    found: list[tuple[str, str]] = []

    # Code is not prose: drop fenced blocks, keeping only the `src` of
    # stash-embed blocks, which pull another file into the page.
    def _strip_fence(m: re.Match) -> str:
        if m.group("info").strip() == "stash-embed":
            src = _embed_src(m.group("body"))
            if src:
                found.append((src, EMBED))
        return ""

    text = _FENCE_RE.sub(_strip_fence, text)
    title_match = _MD_TITLE_RE.search(text)
    title = _clean_title(title_match.group("title")) if title_match else None
    text = _INLINE_CODE_RE.sub("", text)

    image_parens = {m.start("paren") for m in _MD_IMAGE_RE.finditer(text)}
    for m in _MD_LINK_RE.finditer(text):
        target = m.group("angle") if m.group("angle") is not None else m.group("bare")
        found.append((target, EMBED if m.start("paren") in image_parens else LINK))
    for m in _MD_REFERENCE_RE.finditer(text):
        target = m.group("angle") if m.group("angle") is not None else m.group("bare")
        found.append((target, LINK))
    found.extend(_scan_html(text))
    return found, title


def extract_links(path: str, content: str) -> tuple[dict[str, str], str | None]:
    """Extract the references a document makes to other files in the store.

    Returns `(links, title)`. `links` maps each content-relative target path
    to how it is referenced — `LINK` or `EMBED` (images, media, stash-embed
    blocks); a target that is both linked and embedded counts as a link.
    `title` is the document's first top-level heading or `<title>`, if any.
    Targets are not checked for existence.
    """
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _MARKDOWN_EXTENSIONS:
        found, title = _scan_markdown(content)
    elif suffix in _HTML_EXTENSIONS:
        found = _scan_html(content)
        title_match = _HTML_TITLE_RE.search(content)
        title = _clean_title(title_match.group("title")) if title_match else None
    else:
        return {}, None

    parent = PurePosixPath(path).parent.as_posix()
    base_dir = "" if parent == "." else parent
    links: dict[str, str] = {}
    for raw, kind in found:
        target = resolve_target(raw, base_dir)
        if target is None or target == path:
            continue
        if links.get(target) != LINK:
            links[target] = kind
    return links, title


class LinkIndex:
    """Link graph over the content store, refreshed incrementally.

    Every query re-walks the store and stats each scannable document, but only
    re-reads the ones whose size or mtime changed — so edits made outside the
    server (a `git pull`, another process) are picked up without an
    invalidation hook, and a steady-state query costs one directory walk.
    """

    def __init__(self, filesystem: FileSystem):
        self._filesystem = filesystem
        self._documents: dict[str, _Document] = {}
        self._files: frozenset[str] = frozenset()
        self._incoming: dict[str, list[Backlink]] = {}
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        content_dir = self._filesystem.content_dir
        documents: dict[str, _Document] = {}
        changed = False
        files = self._filesystem.list_all_files()
        self._files = frozenset(files)
        for path in files:
            if PurePosixPath(path).suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            try:
                st = (content_dir / path).stat()
            except OSError:
                continue
            signature = (st.st_mtime_ns, st.st_size)
            cached = self._documents.get(path)
            if cached is not None and cached.signature == signature:
                documents[path] = cached
                continue
            changed = True
            links: dict[str, str] = {}
            title = None
            if st.st_size <= _MAX_SCAN_BYTES:
                content = self._filesystem.try_read_text(path)
                if content is not None:
                    links, title = extract_links(path, content)
            documents[path] = _Document(signature, title, links)

        if not changed and documents.keys() == self._documents.keys():
            return
        incoming: dict[str, list[Backlink]] = {}
        for source in sorted(documents):
            doc = documents[source]
            for target, kind in doc.links.items():
                incoming.setdefault(target, []).append(Backlink(source, doc.title, kind))
        self._documents = documents
        self._incoming = incoming

    def backlinks(self, path: str) -> list[Backlink]:
        """Return the documents that reference `path`, sorted by path."""
        with self._lock:
            self._refresh()
            return list(self._incoming.get(path, ()))

    def outgoing(self, path: str) -> list[OutgoingLink]:
        """Return the files `path` references, sorted by path."""
        with self._lock:
            self._refresh()
            doc = self._documents.get(path)
            if doc is None:
                return []
            content_dir = self._filesystem.content_dir
            return [
                OutgoingLink(
                    target, kind, target in self._files or (content_dir / target).exists()
                )
                for target, kind in sorted(doc.links.items())
            ]

    def snapshot(self) -> LinkSnapshot:
        """Capture the current graph, to compare against after a move."""
        with self._lock:
            self._refresh()
            return LinkSnapshot(
                {source: doc.links for source, doc in self._documents.items()}, self._files
            )

    def broken_by_moves(self, before: LinkSnapshot, moves: dict[str, str]) -> list[BrokenLink]:
        """Return the links that `moves` (old path -> new path) broke.

        Every link that reached an existing file in `before` and touched a
        moved file is followed through the move: it is intact if the linking
        document, at its new path, still reaches the target at its new path.
        That covers both directions — other documents pointing at the old
        location, and a moved document whose relative links now resolve
        somewhere else — while leaving alone links that survive, such as
        relative links between files moved together.
        """
        after = self.snapshot()
        broken = set()
        for source, links in before.links.items():
            for target in links:
                if target not in before.files or (source not in moves and target not in moves):
                    continue
                new_source = moves.get(source, source)
                new_target = moves.get(target, target)
                now = after.links.get(new_source, {})
                # Broken if nothing reaches the new location, or if a link
                # still names the vacated path (the same target written two
                # ways, only one of which followed the move).
                stale = target in moves and target in now and target not in after.files
                if new_target not in now or stale:
                    broken.add(BrokenLink(new_source, target, new_target))
        return sorted(broken, key=lambda b: (b.file, b.old_target))

    def graph(self) -> dict:
        """Return the whole link graph as JSON-ready nodes and edges.

        Nodes are every scannable document — linked or not — plus any other
        file one of them references (an image, a spec). Edges are
        `{source, target, kind}` by path and only point at files that exist,
        so broken links and links to folders are left out.
        """
        with self._lock:
            self._refresh()
            edges = [
                {"source": source, "target": target, "kind": kind}
                for source in sorted(self._documents)
                for target, kind in self._documents[source].links.items()
                if target in self._files
            ]
            paths = sorted(self._documents.keys() | {edge["target"] for edge in edges})
            nodes = []
            for path in paths:
                doc = self._documents.get(path)
                nodes.append({
                    "path": path,
                    "title": doc.title if doc else None,
                    "document": doc is not None,
                })
            return {"nodes": nodes, "edges": edges}
