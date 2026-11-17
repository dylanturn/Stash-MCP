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
    Reference,
    broken_by_moves,
    extract_links,
    extract_references,
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
            "~~~\n[example](tilde.md)\n~~~\n\n"
            "Example:\n\n    [sample](indented.md)\n    <a href=\"raw.md\">raw</a>\n"
        )
        links, _ = extract_links("a.md", content)
        assert links == {}

    def test_indented_list_continuations_are_still_prose(self):
        content = (
            "- First item\n\n"
            "    Continued with a [real link](real.md).\n\n"
            "        [inside code](code.md)\n"
        )
        links, _ = extract_links("a.md", content)
        assert links == {"real.md": LINK}

    def test_unused_reference_definitions_are_not_links(self):
        links, _ = extract_links("a.md", "Nothing uses this.\n\n[unused]: target.md\n")
        assert links == {}

    def test_reference_style_images_are_embeds(self):
        content = "![logo][img] and [the guide][g] and [shortcut]\n\n" \
            "[img]: logo.png\n[g]: guide.md\n[shortcut]: short.md\n"
        links, _ = extract_links("docs/a.md", content)
        assert links == {
            "docs/logo.png": EMBED,
            "docs/guide.md": LINK,
            "docs/short.md": LINK,
        }

    def test_html_comments_are_not_scanned(self):
        links, _ = extract_links("a.md", "<!-- <a href=\"old.md\">old</a> -->\n\n[new](new.md)")
        assert links == {"new.md": LINK}
        links, _ = extract_links("a.html", "<!-- <img src=\"old.png\"> --><img src=\"new.png\">")
        assert links == {"new.png": EMBED}

    def test_setext_heading_is_the_title(self):
        _, title = extract_links("a.md", "Release *Notes*\n=============\n\nBody.")
        assert title == "Release Notes"

    def test_references_keep_each_target_as_written(self):
        references, _ = extract_references(
            "docs/a.md", "[one](b.md) [two](/docs/b.md) [web](https://example.com)"
        )
        assert references == [
            Reference("b.md", LINK),
            Reference("/docs/b.md", LINK),
            Reference("https://example.com", LINK),
        ]

    def test_html_is_parsed_not_pattern_matched(self):
        content = (
            "<a href=unquoted.md>ok</a> <A HREF='upper.md'>ok</A> "
            '<a href="a&amp;b.md">entity</a> '
            '<a data-href="ghost.md">not a link</a> '
            '<a href="first.md" href="second.md">first attribute wins</a> '
            "<script>var s = '<a href=\"script.md\">x</a>';</script> "
            "<style>a::after { content: '<img src=\"style.png\">'; }</style> "
            '<!-- <a href="comment.md">x</a> --> '
            '<script src="app.js"></script>'
        )
        expected = {
            "unquoted.md": LINK,
            "upper.md": LINK,
            "a&b.md": LINK,
            "first.md": LINK,
            "app.js": EMBED,
        }
        assert extract_links("page.html", content)[0] == expected
        # Raw HTML inside markdown goes through the same parser.
        assert extract_links("page.md", content)[0] == expected

    def test_stash_embed_src_is_a_literal_path(self):
        content = (
            "```stash-embed\nsrc: \"/mockups/board#1.html\"\n```\n\n"
            "```stash-embed\nsrc: my%20file?.html\n```\n\n"
            "```stash-embed\nsrc: /ui/browse/kept.html\n```\n\n"
            "```stash-embed\nsrc: ../../outside.html\n```\n\n"
            "[a link is a URL](other%20page.md#section)\n"
        )
        links, _ = extract_links("docs/a.md", content)
        assert links == {
            "mockups/board#1.html": EMBED,
            "docs/my%20file?.html": EMBED,
            "ui/browse/kept.html": EMBED,
            "docs/other page.md": LINK,
        }

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

        import stash_mcp.links as links_module

        reads = []
        original = links_module.extract_references
        monkeypatch.setattr(
            links_module,
            "extract_references",
            lambda path, content: reads.append(path) or original(path, content),
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
        fs = FileSystem(tmp_path, include_patterns=["docs/**/*.md"])
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
        # Skipped is not the same as "has no links": the gap is reported.
        assert index.unscanned() == ["broken.md"]
        assert index.snapshot().unscanned == frozenset({"broken.md"})

    def test_oversized_documents_are_reported_as_unscanned(self, fs, monkeypatch):
        import stash_mcp.links as links_module

        monkeypatch.setattr(links_module, "_MAX_SCAN_BYTES", 40)
        fs.write_file("big.md", "[home](index.md) " + "padding " * 10)
        index = LinkIndex(fs)
        assert index.unscanned() == ["big.md", "index.md"]
        assert "big.md" not in [b.path for b in index.backlinks("index.md")]

    def test_document_the_renderer_fails_on_is_unscanned_until_it_changes(
        self, fs, monkeypatch
    ):
        import stash_mcp.links as links_module

        calls = []
        original = links_module.extract_references

        def flaky(path, content):
            calls.append(path)
            if path == "docs/notes.md" and "fixed" not in content:
                raise RuntimeError("renderer bug")
            return original(path, content)

        monkeypatch.setattr(links_module, "extract_references", flaky)
        index = LinkIndex(fs)
        assert index.unscanned() == ["docs/notes.md"]
        assert [b.path for b in index.backlinks("docs/guide.md")] == ["index.md"]

        # Deterministic for the same content, so it is not rendered again...
        calls.clear()
        assert index.unscanned() == ["docs/notes.md"]
        assert calls == []

        # ...until the file changes.
        fs.write_file("docs/notes.md", "fixed: see the [guide](guide.md).")
        assert index.unscanned() == []
        assert [b.path for b in index.backlinks("docs/guide.md")] == [
            "docs/notes.md", "index.md",
        ]

    def test_transient_read_failure_is_retried(self, fs, monkeypatch):
        from pathlib import Path

        failing = {"on": True}
        original = Path.read_text

        def read_text(self, *args, **kwargs):
            if failing["on"] and self.name == "notes.md":
                raise OSError("temporarily unavailable")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read_text)
        index = LinkIndex(fs)
        assert index.unscanned() == ["docs/notes.md"]
        assert [b.path for b in index.backlinks("docs/guide.md")] == ["index.md"]

        # The file itself has not changed, but the next query tries again.
        failing["on"] = False
        assert index.unscanned() == []
        assert [b.path for b in index.backlinks("docs/guide.md")] == [
            "docs/notes.md", "index.md",
        ]

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
        assert broken_by_moves(before, {"a.md": "archive/a.md"}) == [
            BrokenLink("c.md", "a.md", "archive/a.md"),
            BrokenLink("docs/b.md", "a.md", "archive/a.md"),
        ]

    def test_relative_links_inside_a_moved_file_are_reported(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/a.md", "[sibling](b.md) [rooted](/docs/c.md#x) ![pic](pic.png)")
        fs.write_file("docs/b.md", "# B")
        fs.write_file("docs/c.md", "# C")
        fs.write_file("docs/pic.png", "x")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("docs/a.md", "archive/a.md")
        # The root-absolute link to c.md still works, so c.md is not reported.
        assert broken_by_moves(before, {"docs/a.md": "archive/a.md"}) == [
            BrokenLink("archive/a.md", "docs/b.md", "docs/b.md"),
            BrokenLink("archive/a.md", "docs/pic.png", "docs/pic.png"),
        ]

    def test_each_link_to_the_same_target_is_judged_separately(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/a.md", "[relative](b.md) [rooted](/docs/b.md)")
        fs.write_file("docs/b.md", "# B")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("docs/a.md", "archive/a.md")
        # The rooted link survives; the relative one to the same file does not.
        assert broken_by_moves(before, {"docs/a.md": "archive/a.md"}) == [
            BrokenLink("archive/a.md", "docs/b.md", "docs/b.md"),
        ]

    def test_root_absolute_self_link_breaks_when_the_file_moves(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/a.md", "[top](/docs/a.md#top) [also me](a.md#x)")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("docs/a.md", "archive/a.md")
        assert broken_by_moves(before, {"docs/a.md": "archive/a.md"}) == [
            BrokenLink("archive/a.md", "docs/a.md", "archive/a.md"),
        ]

    def test_files_moved_together_keep_their_relative_links(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/a.md", "[b](b.md) [home](../index.md) [abs](/docs/b.md)")
        fs.write_file("docs/b.md", "[a](a.md)")
        fs.write_file("index.md", "[a](docs/a.md)")
        index = LinkIndex(fs)
        before = index.snapshot()
        moved = dict(fs.move_directory("docs", "guides"))
        assert broken_by_moves(before, moved) == [
            # Root-absolute link inside the moved directory still names the old path.
            BrokenLink("guides/a.md", "docs/b.md", "guides/b.md"),
            BrokenLink("index.md", "docs/a.md", "guides/a.md"),
        ]

    def test_moved_stash_embed_source_is_reported_by_its_literal_path(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("mockups/board#1.html", "<p>board</p>")
        fs.write_file("docs/a.md", "```stash-embed\nsrc: \"/mockups/board#1.html\"\n```\n")
        index = LinkIndex(fs)
        assert [b.path for b in index.backlinks("mockups/board#1.html")] == ["docs/a.md"]
        before = index.snapshot()
        fs.move_file("mockups/board#1.html", "archive/board#1.html")
        moves = {"mockups/board#1.html": "archive/board#1.html"}
        assert broken_by_moves(before, moves) == [
            BrokenLink("docs/a.md", "mockups/board#1.html", "archive/board#1.html"),
        ]

    def test_links_to_moved_directories_are_reported(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/guide.md", "[up](./) [nested](sub/) [home](../index.md)")
        fs.write_file("docs/sub/deep.md", "# Deep")
        fs.write_file("other/keep.md", "# Keep")
        fs.write_file(
            "index.md",
            "[docs](/ui/browse/docs/) [sub](docs/sub) [other](other/) [gone](nowhere/)",
        )
        index = LinkIndex(fs)
        before = index.snapshot()
        moved = dict(fs.move_directory("docs", "guides"))
        # Links to the moved folder and to a folder inside it are reported;
        # the moved document's own relative folder links still resolve.
        assert broken_by_moves(before, moved, {"docs": "guides"}) == [
            BrokenLink("index.md", "docs", "guides"),
            BrokenLink("index.md", "docs/sub", "guides/sub"),
        ]

    def test_links_to_an_empty_moved_directory_are_reported(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/guide.md", "# Guide")
        fs.create_directory("docs/empty")
        fs.write_file("index.md", "[empty](docs/empty/) [gone](docs/missing/)")
        index = LinkIndex(fs)
        before = index.snapshot()
        assert "docs/empty" in before.directories
        assert "docs/missing" not in before.directories
        moved = dict(fs.move_directory("docs", "guides"))
        assert broken_by_moves(before, moved, {"docs": "guides"}) == [
            BrokenLink("index.md", "docs/empty", "guides/empty"),
        ]

    def test_relative_link_to_a_directory_breaks_when_the_file_moves(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("docs/a.md", "[assets](assets/)")
        fs.write_file("docs/assets/pic.png", "x")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("docs/a.md", "archive/a.md")
        assert broken_by_moves(before, {"docs/a.md": "archive/a.md"}) == [
            BrokenLink("archive/a.md", "docs/assets", "docs/assets"),
        ]

    def test_links_that_were_already_broken_are_not_reported(self, tmp_path):
        fs = FileSystem(tmp_path)
        fs.write_file("a.md", "[gone](missing.md)")
        fs.write_file("b.md", "[gone](a-old.md)")
        index = LinkIndex(fs)
        before = index.snapshot()
        fs.move_file("a.md", "sub/a.md")
        assert broken_by_moves(before, {"a.md": "sub/a.md"}) == []
