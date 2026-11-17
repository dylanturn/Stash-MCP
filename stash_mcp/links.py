"""Link extraction and a cached link graph over the content store.

Markdown and HTML documents are scanned for references to other files in the
store — links, images, and ``stash-embed`` blocks. The resulting graph is kept
per source document (``source -> {target: kind}``), which answers "what links
here?" for the UI and is the same data a document map needs.
"""

import logging
import posixpath
import re
import threading
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote

import markdown as md
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

# Same shape the viewer uses to find stash-embed blocks before rendering.
_EMBED_FENCE_RE = re.compile(
    r"^```stash-embed\s*\n(?P<body>.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)
# The block-level extensions the viewer renders with. They decide what is
# code, a list, or a table — and so which link-shaped text is really a link.
_MARKDOWN_BLOCK_EXTENSIONS = ["fenced_code", "tables", "sane_lists"]

# The one attribute on each element that references another resource, and
# whether following it leaves the page (a link) or pulls the resource in.
_REFERENCE_ATTRIBUTES = {
    "a": ("href", LINK),
    "area": ("href", LINK),
    "img": ("src", EMBED),
    "source": ("src", EMBED),
    "video": ("src", EMBED),
    "audio": ("src", EMBED),
    "iframe": ("src", EMBED),
    "embed": ("src", EMBED),
    "script": ("src", EMBED),
    "link": ("href", EMBED),
    "object": ("data", EMBED),
}


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
class Reference:
    """One reference exactly as a document wrote it.

    `literal` marks a stash-embed `src`, which the viewer reads as a
    filesystem path rather than a URL: `#`, `?` and `%` are ordinary
    characters in it.
    """

    raw: str
    kind: str
    literal: bool = False

    def resolve(self, base_dir: str) -> str | None:
        """Resolve to a content-root path, or None if it leaves the store."""
        if self.literal:
            return _resolve_embed_target(self.raw, base_dir)
        return resolve_target(self.raw, base_dir)


@dataclass(frozen=True)
class LinkSnapshot:
    """Every reference in the store at one moment, plus what exists.

    `references` maps each source document to its `(reference, target)`
    pairs: the reference as written and the content-root path it resolved
    to. Keeping the written form lets a move be judged one reference at a
    time — two links to the same file, one relative and one root-absolute,
    fare differently. `directories` holds every folder that contains a file,
    since a link may point at a folder.
    """

    references: dict[str, tuple[tuple[Reference, str], ...]]
    files: frozenset[str]
    directories: frozenset[str]


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
    references: tuple[tuple[Reference, str], ...]


def _base_dir(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def resolve_target(target: str, base_dir: str) -> str | None:
    """Resolve a raw link target to a content-store-relative path.

    Returns None for anything that does not address a file in the store:
    external URLs, in-page anchors, and paths that climb out of the root.
    A leading `/` is rooted at the content store, as it is for embeds.
    `target` is a URL with any HTML entities already decoded.
    """
    target = target.strip()
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


def resolve_embed_src(src: str, base_dir: str) -> str:
    """Resolve a stash-embed `src` to a content-store-relative path.

    Absolute (`/specs/api.json`) is rooted at the content store; otherwise the
    src is interpreted relative to the embedding document's directory. The
    src is a literal path, not a URL: nothing in it is decoded or stripped.

    The result is normalized (`.`/`..` segments collapsed) so downstream
    consumers — `filesystem.read_file`, embed-error messages, and the URL
    rewriter that uses the parent dir to anchor relative `<img>`/`<a>`
    targets — get a clean path. A `src` that escapes the content root with
    leading `..` segments still yields a path starting with `..`, which the
    filesystem layer rejects with `InvalidPathError`; the caller catches that
    and produces a dedicated embed error.
    """
    if src.startswith("/"):
        joined = src.lstrip("/")
    elif base_dir:
        joined = str(PurePosixPath(base_dir) / src)
    else:
        joined = src
    normalized = posixpath.normpath(joined) if joined else ""
    # normpath("") -> "." — collapse that to "" so callers see "no path"
    # consistently when the input was empty.
    return "" if normalized == "." else normalized


def _resolve_embed_target(src: str, base_dir: str) -> str | None:
    """`resolve_embed_src`, with None for a src that names nothing in the store."""
    path = resolve_embed_src(src, base_dir)
    if not path or path == ".." or path.startswith("../"):
        return None
    return path


def _embed_src(body: str) -> str | None:
    try:
        config = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    src = config.get("src") if isinstance(config, dict) else None
    return src if isinstance(src, str) and src else None


class _ReferenceParser(HTMLParser):
    """Collect references from real start tags, and the text of a title tag.

    Parsing, rather than searching the markup, is what tells `href` from
    `data-href`, accepts an unquoted attribute value, and keeps link-shaped
    text in a `<script>`, a `<style>` or a comment from counting.
    """

    def __init__(self, title_tag: str):
        super().__init__(convert_charrefs=True)
        self.references: list[Reference] = []
        self.title: str | None = None
        self._title_tag = title_tag
        self._title_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        reference_attribute = _REFERENCE_ATTRIBUTES.get(tag)
        if reference_attribute is not None:
            name, kind = reference_attribute
            # A repeated attribute is ignored by browsers; the first one counts.
            value = next((v for k, v in attrs if k == name), None)
            if value:
                self.references.append(Reference(value, kind))
        if tag == self._title_tag and self.title is None and self._title_parts is None:
            self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._title_tag and self._title_parts is not None:
            self.title = " ".join("".join(self._title_parts).split()) or None
            self._title_parts = None


def _scan_html(text: str, title_tag: str) -> tuple[list[Reference], str | None]:
    parser = _ReferenceParser(title_tag)
    parser.feed(text)
    parser.close()
    return parser.references, parser.title


def _scan_markdown(text: str) -> tuple[list[Reference], str | None]:
    """Find references by rendering the document the way the viewer does.

    Recognizing links by pattern-matching the source gets the edges wrong:
    indented code, unused reference definitions, and list continuations all
    look like something they are not. Rendering settles every such case the
    same way the reader sees it — code comes out escaped, an unused
    definition produces nothing, `![logo][img]` is an image — so the
    references are whatever anchors and embeds end up in the HTML.
    """
    embeds: list[Reference] = []

    # stash-embed blocks pull another file into the page. The viewer swaps
    # them out before rendering; take their `src` the same way.
    def _take_embed(m: re.Match) -> str:
        src = _embed_src(m.group("body"))
        if src:
            embeds.append(Reference(src, EMBED, literal=True))
        return ""

    text = _EMBED_FENCE_RE.sub(_take_embed, text)
    rendered = md.Markdown(extensions=_MARKDOWN_BLOCK_EXTENSIONS).convert(text)
    references, title = _scan_html(rendered, title_tag="h1")
    return embeds + references, title


def extract_references(path: str, content: str) -> tuple[list[Reference], str | None]:
    """Extract every reference a document makes, as written.

    Returns `(references, title)`. `references` holds one `Reference` per
    link, image, or embed. External URLs and anchors are included;
    `Reference.resolve` filters them. `title` is the document's first
    top-level heading or `<title>`, if any.
    """
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _MARKDOWN_EXTENSIONS:
        return _scan_markdown(content)
    if suffix in _HTML_EXTENSIONS:
        return _scan_html(content, title_tag="title")
    return [], None


def _resolve_references(
    path: str, references: list[Reference]
) -> tuple[dict[str, str], tuple[tuple[Reference, str], ...]]:
    """Resolve references against `path`'s directory.

    Returns the document's `links` (target -> kind, without self-links; a
    target that is both linked and embedded counts as a link) and its
    distinct `(reference, target)` pairs, self-links included — a
    root-absolute link to itself breaks when the document moves.
    """
    base_dir = _base_dir(path)
    links: dict[str, str] = {}
    resolved: dict[tuple[Reference, str], None] = {}
    for reference in references:
        target = reference.resolve(base_dir)
        if target is None:
            continue
        resolved[(reference, target)] = None
        if target != path and links.get(target) != LINK:
            links[target] = reference.kind
    return links, tuple(resolved)


def extract_links(path: str, content: str) -> tuple[dict[str, str], str | None]:
    """Extract the references a document makes to other files in the store.

    Returns `(links, title)`. `links` maps each content-relative target path
    to how it is referenced — `LINK` or `EMBED` (images, media, stash-embed
    blocks); a target that is both linked and embedded counts as a link.
    `title` is the document's first top-level heading or `<title>`, if any.
    Targets are not checked for existence.
    """
    references, title = extract_references(path, content)
    return _resolve_references(path, references)[0], title


def broken_by_moves(
    before: LinkSnapshot,
    moves: dict[str, str],
    directory_moves: dict[str, str] | None = None,
) -> list[BrokenLink]:
    """Return the links that a move broke.

    `moves` maps each moved file's old path to its new one. `directory_moves`
    does the same for folders moved as a whole, so that links to a moved
    folder — or to a folder inside it — are followed too.

    A move changes where files are, never what documents say, so each
    reference can be judged from the snapshot taken before it: resolve it
    from the linking document's new directory and compare that with where
    its old target now lives. That covers both directions — other documents
    pointing at a vacated path, and a moved document whose relative links
    now resolve somewhere else — while leaving alone links that survive,
    such as relative links between files moved together. Links that reached
    nothing before the move are not reported.
    """
    directory_moves = directory_moves or {}

    def relocated(path: str) -> str:
        if path in moves:
            return moves[path]
        if path in before.directories:
            for old, new in directory_moves.items():
                if path == old or path.startswith(old + "/"):
                    return new + path[len(old):]
        return path

    broken = set()
    for source, references in before.references.items():
        new_source = moves.get(source, source)
        new_dir = _base_dir(new_source)
        for reference, target in references:
            if target not in before.files and target not in before.directories:
                continue
            new_target = relocated(target)
            if new_source == source and new_target == target:
                continue
            if reference.resolve(new_dir) != new_target:
                broken.add(BrokenLink(new_source, target, new_target))
    return sorted(broken, key=lambda b: (b.file, b.old_target))


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
            references: tuple[tuple[Reference, str], ...] = ()
            title = None
            if st.st_size <= _MAX_SCAN_BYTES:
                content = self._filesystem.try_read_text(path)
                if content is not None:
                    try:
                        raw_references, title = extract_references(path, content)
                    except Exception:
                        # One document the renderer chokes on must not take
                        # the whole graph down with it.
                        logger.warning("Could not scan '%s' for links", path, exc_info=True)
                    else:
                        links, references = _resolve_references(path, raw_references)
            documents[path] = _Document(signature, title, links, references)

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
        """Capture every reference and file, to judge a move against."""
        with self._lock:
            self._refresh()
            directories = {
                parent.as_posix()
                for path in self._files
                for parent in PurePosixPath(path).parents
            }
            directories.discard(".")
            return LinkSnapshot(
                {source: doc.references for source, doc in self._documents.items()},
                self._files,
                frozenset(directories),
            )

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
