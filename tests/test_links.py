"""Tests for link extraction and the backlink index."""

import os

import pytest

from stash_mcp.filesystem import FileSystem
from stash_mcp.links import (
    EMBED,
    LINK,
    BrokenLink,
    LinkIndex,
    OutgoingLink,
    extract_links,
    resolve_target,
)


class TestResolveTarget:
    @pytest.mark.parametrize(
        ("target", "base_dir", "expected"),
        [
            ("b.md", "docs", "docs/b.md"),
            ("b.md", "", "b.md"),
            ("./b.md", "docs", "docs/b.md"),
            ("../b.md", "docs/guides", "docs/b.md"),
            ("/specs/api.json", "docs", "specs/api.json"),
            ("/ui/browse/docs/b.md", "notes", "docs/b.md"),
            ("/ui/raw/img/a.png", "notes", "img/a.png"),
            ("b.md#section", "docs", "docs/b.md"),
            ("b.md?raw=1", "docs", "docs/b.md"),
            ("my%20notes.md", "docs", "docs/my notes.md"),
            ("what%3F%23.md", "docs", "docs/what?#.md"),
            ("a&amp;b.md", "", "a&b.md"),
        ],
    )
    def test_resolves_paths_in_the_store(self, target, base_dir, expected):
        assert resolve_target(target, base_dir) == expected

    @pytest.mark.parametrize(
        "target",
        [
            "https://example.com/b.md",
            "mailto:someone@example.com",
            "//cdn.example.com/x.js",
            "#section",
            "",
            "../outside.md",
            "data:image/png;base64,AAAA",
            "/",
        ],
    )
    def test_ignores_targets_outside_the_store(self, target):
        assert resolve_target(target, "") is None


class TestExtractLinks:
    def test_markdown_links_images_and_embeds(self):
        content = (
            "# The *Guide* to `things`\n\n"
            "See [setup](setup.md) and [API](../api/spec.json \"the spec\").\n"
            "![diagram](img/flow.png)\n\n"
            "```stash-embed\nsrc: /mockups/board.html\nselector: .board\n```\n"
        )
        links, title = extract_links("docs/guide.md", content)
        assert links == {
            "docs/setup.md": LINK,
            "api/spec.json": LINK,
            "docs/img/flow.png": EMBED,
            "mockups/board.html": EMBED,
        }
        assert title == "The Guide to things"

    def test_linked_image_yields_both_targets(self):
        links, _ = extract_links("a.md", "[![badge](badge.png)](target.md)")
        assert links == {"badge.png": EMBED, "target.md": LINK}

    def test_link_wins_when_a_target_is_both_linked_and_embedded(self):
        links, _ = extract_links("a.md", "![x](pic.svg) and [open it](pic.svg)")
        assert links == {"pic.svg": LINK}

    def test_reference_definitions_and_angle_targets(self):
        content = (
            "Read [the notes][n] or [this](<my notes.md>).\n\n"
            "[n]: notes/today.md\n"
            "[^1]: footnote.md is not a link\n"
        )
        links, _ = extract_links("a.md", content)
        assert links == {"notes/today.md": LINK, "my notes.md": LINK}

    def test_targets_with_parentheses(self):
        links, _ = extract_links("a.md", "[copy](report(1).md)")
        assert links == {"report(1).md": LINK}

    def test_raw_html_in_markdown(self):
        content = '<a href="other.md">other</a> <img src="pic.png" alt="">'
        links, _ = extract_links("docs/a.md", content)
        assert links == {"docs/other.md": LINK, "docs/pic.png": EMBED}

    def test_code_is_not_scanned(self):
        content = (
            "Write links as `[text](inline.md)`.\n\n"
            "```markdown\n[example](fenced.md)\n```\n\n"
            "~~~\n[example](tilde.md)\n~~~\n"
        )
        links, _ = extract_links("a.md", content)
        assert links == {}

    def test_external_anchor_and_self_links_are_dropped(self):
        content = "[web](https://example.com) [top](#top) [me](a.md) [me too](./a.md#x)"
        links, _ = extract_links("a.md", content)
        assert links == {}

    def test_html_documents(self):
        content = (
            "<html><head><title>Board &amp; Stories</title>"
            '<link rel="stylesheet" href="style.css"></head>'
            '<body><a href="../docs/plan.md">plan</a>'
            '<img src="shot.png"><a href="https://example.com">x</a></body></html>'
        )
        links, title = extract_links("mockups/board.html", content)
        assert links == {
            "mockups/style.css": EMBED,
            "docs/plan.md": LINK,
            "mockups/shot.png": EMBED,
        }
        assert title == "Board & Stories"

    def test_other_file_types_have_no_links(self):
        assert extract_links("data.json", '{"see": "[x](a.md)"}') == ({}, None)


class TestLinkIndex:
    @pytest.fixture
    def fs(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("index.md", "# Home\n\n[guide](docs/guide.md) ![logo](img/logo.png)")
        fs.write_file("docs/guide.md", "# Guide\n\nBack to [home](../index.md).")
        fs.write_file("docs/notes.md", "No heading. See the [guide](guide.md).")
        fs.write_file("img/logo.png", "not really a png")
        return fs

    def test_backlinks_are_sorted_with_titles_and_kinds(self, fs):
        index = LinkIndex(fs)
        guide = index.backlinks("docs/guide.md")
        assert [(b.path, b.title, b.kind) for b in guide] == [
            ("docs/notes.md", None, LINK),
            ("index.md", "Home", LINK),
        ]
        logo = index.backlinks("img/logo.png")
        assert [(b.path, b.kind) for b in logo] == [("index.md", EMBED)]
        assert index.backlinks("docs/notes.md") == []

    def test_picks_up_edits_new_files_and_deletions(self, fs):
        index = LinkIndex(fs)
        assert [b.path for b in index.backlinks("index.md")] == ["docs/guide.md"]

        fs.write_file("docs/notes.md", "Now links [home](/index.md).")
        fs.write_file("extra.md", "[home](index.md)")
        assert [b.path for b in index.backlinks("index.md")] == [
            "docs/guide.md", "docs/notes.md", "extra.md",
        ]
        assert [b.path for b in index.backlinks("docs/guide.md")] == ["index.md"]

        fs.delete_file("docs/guide.md")
        assert [b.path for b in index.backlinks("index.md")] == ["docs/notes.md", "extra.md"]

    def test_unchanged_documents_are_not_reread(self, fs, monkeypatch):
        index = LinkIndex(fs)
        index.backlinks("index.md")

        reads = []
        original = fs.try_read_text
        monkeypatch.setattr(
            fs, "try_read_text", lambda path: reads.append(path) or original(path)
        )
        index.backlinks("index.md")
        assert reads == []

        # Same size, new mtime: only this document is read again.
        full = fs.content_dir / "docs/notes.md"
        st = full.stat()
        os.utime(full, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        index.backlinks("index.md")
        assert reads == ["docs/notes.md"]

    def test_hidden_and_filtered_documents_are_not_sources(self, tmp_path):
        fs = FileSystem(tmp_path, include_patterns=["docs/**"])
        fs.write_file("docs/target.md", "# Target")
        fs.write_file("docs/visible.md", "[t](target.md)")
        fs.write_file("docs/.hidden.md", "[t](target.md)")
        fs.write_file("private/secret.md", "[t](../docs/target.md)")
        index = LinkIndex(fs)
        assert [b.path for b in index.backlinks("docs/target.md")] == ["docs/visible.md"]

    def test_undecodable_documents_are_skipped(self, fs):
        (fs.content_dir / "broken.md").write_bytes(b"\xff\xfe[x](index.md)")
        index = LinkIndex(fs)
        assert [b.path for b in index.backlinks("index.md")] == ["docs/guide.md"]

    def test_graph_has_every_document_and_only_existing_targets(self, fs):
        fs.write_file("orphan.md", "# Orphan")
        fs.write_file("docs/notes.md", "[gone](missing.md) [folder](../img/) [guide](guide.md)")
        graph = LinkIndex(fs).graph()
        assert graph["nodes"] == [
            {"path": "docs/guide.md", "title": "Guide", "document": True},
            {"path": "docs/notes.md", "title": None, "document": True},
            {"path": "img/logo.png", "title": None, "document": False},
            {"path": "index.md", "title": "Home", "document": True},
            {"path": "orphan.md", "title": "Orphan", "document": True},
        ]
        assert graph["edges"] == [
            {"source": "docs/guide.md", "target": "index.md", "kind": LINK},
            {"source": "docs/notes.md", "target": "docs/guide.md", "kind": LINK},
            {"source": "index.md", "target": "docs/guide.md", "kind": LINK},
            {"source": "index.md", "target": "img/logo.png", "kind": EMBED},
        ]

    def test_graph_sees_newly_added_targets(self, fs):
        fs.write_file("docs/notes.md", "![later](later.png)")
        index = LinkIndex(fs)
        assert "docs/later.png" not in [n["path"] for n in index.graph()["nodes"]]
        fs.write_file("docs/later.png", "x")
        assert {"path": "docs/later.png", "title": None, "document": False} in (
            index.graph()["nodes"]
        )

    def test_outgoing_marks_broken_links(self, fs):
        fs.write_file("docs/notes.md", "[guide](guide.md) [gone](missing.md) [dir](../img/)")
        index = LinkIndex(fs)
        assert index.outgoing("docs/notes.md") == [
            OutgoingLink("docs/guide.md", LINK, True),
            OutgoingLink("docs/missing.md", LINK, False),
            OutgoingLink("img", LINK, True),
        ]
        assert index.outgoing("img/logo.png") == []


class TestBrokenByMoves:
    def test_links_to_a_moved_file_are_reported(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("a.md", "# A")
        fs.write_file("docs/b.md", "[a](../a.md)")
        fs.write_file("c.md", "[a](a.md) and [b](docs/b.md)")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("a.md", "archive/a.md")
        assert index.broken_by_moves(before, {"a.md": "archive/a.md"}) == [
            BrokenLink("c.md", "a.md", "archive/a.md"),
            BrokenLink("docs/b.md", "a.md", "archive/a.md"),
        ]

    def test_relative_links_inside_a_moved_file_are_reported(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/a.md", "[sibling](b.md) [rooted](/docs/b.md#x) ![pic](pic.png)")
        fs.write_file("docs/b.md", "# B")
        fs.write_file("docs/pic.png", "x")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("docs/a.md", "archive/a.md")
        # The root-absolute link to b.md still works, so b.md is not reported.
        assert index.broken_by_moves(before, {"docs/a.md": "archive/a.md"}) == [
            BrokenLink("archive/a.md", "docs/pic.png", "docs/pic.png"),
        ]

    def test_files_moved_together_keep_their_relative_links(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/a.md", "[b](b.md) [home](../index.md) [abs](/docs/b.md)")
        fs.write_file("docs/b.md", "[a](a.md)")
        fs.write_file("index.md", "[a](docs/a.md)")
        index = LinkIndex(fs)
        before = index.snapshot()
        moved = dict(fs.move_directory("docs", "guides"))
        assert index.broken_by_moves(before, moved) == [
            # Root-absolute link inside the moved directory still names the old path.
            BrokenLink("guides/a.md", "docs/b.md", "guides/b.md"),
            BrokenLink("index.md", "docs/a.md", "guides/a.md"),
        ]

    def test_links_that_were_already_broken_are_not_reported(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("a.md", "[gone](missing.md)")
        fs.write_file("b.md", "[gone](a-old.md)")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("a.md", "sub/a.md")
        assert index.broken_by_moves(before, {"a.md": "sub/a.md"}) == []
