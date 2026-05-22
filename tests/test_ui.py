"""Tests for UI routes."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from stash_mcp.api import create_api
from stash_mcp.filesystem import FileSystem
from stash_mcp.ui import create_ui_router


# Simple mock embedding for search-enabled UI tests
async def _mock_embed(texts: list[str]) -> list[list[float]]:
    keywords = [
        "auth", "oauth", "flow", "meeting", "notes",
        "config", "database", "test", "search", "content",
        "section", "project", "file", "data", "code", "doc",
    ]
    embeddings = []
    for text in texts:
        text_lower = text.lower()
        vec = [float(text_lower.count(kw)) for kw in keywords]
        vec[0] += 0.1
        embeddings.append(vec)
    return embeddings


@pytest.fixture
def ui_client():
    """Create a test client with UI router and temporary filesystem."""
    with TemporaryDirectory() as tmpdir:
        fs = FileSystem(Path(tmpdir))
        fs.write_file("hello.md", "# Hello World")
        fs.write_file("docs/readme.md", "# README\nSome content here.")
        fs.write_file("data/config.json", '{"key": "value"}')

        app = create_api(fs)
        router = create_ui_router(fs)
        app.include_router(router)
        client = TestClient(app)
        yield client


class TestUIHome:
    """Tests for /ui redirect."""

    def test_ui_redirects_to_browse(self, ui_client):
        """GET /ui redirects to /ui/browse/."""
        response = ui_client.get("/ui", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/ui/browse/"


class TestUIBrowse:
    """Tests for /ui/browse/ routes."""

    def test_browse_root_lists_files(self, ui_client):
        """GET /ui/browse/ shows root directory listing."""
        response = ui_client.get("/ui/browse/")
        assert response.status_code == 200
        body = response.text
        assert "hello.md" in body
        assert "docs" in body
        assert "data" in body

    def test_browse_subdirectory(self, ui_client):
        """GET /ui/browse/docs lists directory contents."""
        response = ui_client.get("/ui/browse/docs")
        assert response.status_code == 200
        body = response.text
        assert "readme.md" in body

    def test_browse_file_shows_content(self, ui_client):
        """GET /ui/browse/hello.md shows file content rendered as markdown."""
        response = ui_client.get("/ui/browse/hello.md")
        assert response.status_code == 200
        body = response.text
        # Markdown files are rendered to HTML
        assert "Hello World</h1>" in body
        assert "markdown-body" in body
        # Should show metadata panel
        assert "text/markdown" in body
        # Should have edit link
        assert "/ui/edit/hello.md" in body

    def test_browse_file_no_breadcrumbs(self, ui_client):
        """File view does not include breadcrumb navigation."""
        response = ui_client.get("/ui/browse/docs/readme.md")
        assert response.status_code == 200
        body = response.text
        assert "breadcrumbs" not in body or 'class="breadcrumbs"' not in body

    def test_browse_file_has_metadata(self, ui_client):
        """File view shows metadata in right panel."""
        response = ui_client.get("/ui/browse/hello.md")
        assert response.status_code == 200
        body = response.text
        assert "Document Metadata" in body
        assert "Words" in body
        assert "Characters" in body

    def test_browse_directory_has_sidebar_tree(self, ui_client):
        """Browse page includes sidebar with file tree."""
        response = ui_client.get("/ui/browse/")
        assert response.status_code == 200
        body = response.text
        assert "Stash-MCP" in body
        assert "New Document" in body


class TestUIEdit:
    """Tests for /ui/edit/ routes."""

    def test_edit_shows_editor(self, ui_client):
        """GET /ui/edit/hello.md shows editor with file content."""
        response = ui_client.get("/ui/edit/hello.md")
        assert response.status_code == 200
        body = response.text
        assert "# Hello World" in body
        assert "textarea" in body.lower()
        assert "Save" in body
        assert "Cancel" in body

    def test_edit_nonexistent_shows_error(self, ui_client):
        """GET /ui/edit/nonexistent.md shows error message."""
        response = ui_client.get("/ui/edit/nonexistent.md")
        assert response.status_code == 200
        body = response.text
        assert "Error" in body


class TestUINew:
    """Tests for /ui/new route."""

    def test_new_shows_creation_form(self, ui_client):
        """GET /ui/new shows a new document form."""
        response = ui_client.get("/ui/new")
        assert response.status_code == 200
        body = response.text
        assert "New Document" in body
        assert "textarea" in body.lower()
        assert 'name="path"' in body
        assert "Create" in body


class TestUISave:
    """Tests for POST /ui/save."""

    def test_save_creates_new_file(self, ui_client):
        """POST /ui/save creates a file and redirects to browse."""
        response = ui_client.post(
            "/ui/save",
            data={"path": "new-file.md", "content": "# New File"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "/ui/browse/new-file.md" in response.headers["location"]

        # Verify file was created (markdown rendered to HTML)
        view_resp = ui_client.get("/ui/browse/new-file.md")
        assert "New File</h1>" in view_resp.text

    def test_save_updates_existing_file(self, ui_client):
        """POST /ui/save updates existing file content."""
        response = ui_client.post(
            "/ui/save",
            data={"path": "hello.md", "content": "# Updated"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        view_resp = ui_client.get("/ui/browse/hello.md")
        assert "Updated</h1>" in view_resp.text

    def test_save_creates_nested_path(self, ui_client):
        """POST /ui/save creates parent directories as needed."""
        response = ui_client.post(
            "/ui/save",
            data={"path": "deep/nested/file.md", "content": "nested content"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        view_resp = ui_client.get("/ui/browse/deep/nested/file.md")
        assert "nested content" in view_resp.text


class TestUIDelete:
    """Tests for POST /ui/delete/."""

    def test_delete_removes_file(self, ui_client):
        """POST /ui/delete/hello.md removes the file and redirects to parent."""
        response = ui_client.post("/ui/delete/hello.md", follow_redirects=False)
        assert response.status_code == 303
        # Should redirect to root (parent of hello.md)
        assert "/ui/browse/" in response.headers["location"]

        # File should be gone
        view_resp = ui_client.get("/ui/browse/hello.md")
        assert "not found" in view_resp.text.lower() or "Path not found" in view_resp.text

    def test_delete_nested_redirects_to_parent(self, ui_client):
        """POST /ui/delete/docs/readme.md redirects to /ui/browse/docs."""
        response = ui_client.post("/ui/delete/docs/readme.md", follow_redirects=False)
        assert response.status_code == 303
        assert "/ui/browse/docs" in response.headers["location"]

    def test_delete_nonexistent_redirects_gracefully(self, ui_client):
        """POST /ui/delete/nonexistent.md still redirects without error."""
        response = ui_client.post("/ui/delete/nonexistent.md", follow_redirects=False)
        assert response.status_code == 303


class TestUIMove:
    """Tests for POST /ui/move/."""

    def test_move_renames_file(self, ui_client):
        """POST /ui/move/hello.md renames the file and redirects to new location."""
        response = ui_client.post(
            "/ui/move/hello.md",
            data={"destination": "renamed.md"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "/ui/browse/renamed.md" in response.headers["location"]

        # Verify file is at new location
        view_resp = ui_client.get("/ui/browse/renamed.md")
        assert "Hello World</h1>" in view_resp.text

        # Verify old path is gone
        old_resp = ui_client.get("/ui/browse/hello.md")
        assert "not found" in old_resp.text.lower() or "Path not found" in old_resp.text

    def test_move_nested_file(self, ui_client):
        """POST /ui/move/docs/readme.md moves to a new path and redirects."""
        response = ui_client.post(
            "/ui/move/docs/readme.md",
            data={"destination": "notes/readme.md"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "/ui/browse/notes/readme.md" in response.headers["location"]

    def test_move_form_present(self, ui_client):
        """GET browse page for a file shows the rename form."""
        response = ui_client.get("/ui/browse/hello.md")
        body = response.text
        assert "Rename / Move" in body
        assert "rename-form" in body
        assert "/ui/move/hello.md" in body
        assert 'name="destination"' in body


class TestUIMarkdown:
    """Tests for markdown rendering."""

    def test_markdown_file_rendered_as_html(self, ui_client):
        """Markdown files should be rendered to HTML, not shown raw."""
        response = ui_client.get("/ui/browse/hello.md")
        body = response.text
        assert "markdown-body" in body
        assert "Hello World</h1>" in body

    def test_non_markdown_file_shown_as_preformatted(self, ui_client):
        """Non-markdown files should be shown in pre tags."""
        response = ui_client.get("/ui/browse/data/config.json")
        body = response.text
        assert "<pre>" in body
        assert "&quot;key&quot;" in body

    def test_markdown_with_formatting(self, ui_client):
        """Markdown with headings and content renders properly."""
        response = ui_client.get("/ui/browse/docs/readme.md")
        body = response.text
        assert "README</h1>" in body
        assert "Some content here." in body


_SAMPLE_OPENAPI = """{
  "openapi": "3.0.0",
  "info": {"title": "Orders API", "version": "1.0.0"},
  "paths": {
    "/orders": {
      "get": {"tags": ["orders"], "summary": "List orders",
              "operationId": "listOrders", "responses": {"200": {"description": "OK"}}},
      "post": {"tags": ["orders"], "summary": "Create order",
               "operationId": "createOrder", "responses": {"201": {"description": "Created"}}}
    },
    "/health": {
      "get": {"tags": ["health"], "summary": "Healthcheck",
              "operationId": "health", "responses": {"200": {"description": "OK"}}}
    }
  },
  "components": {"schemas": {"Order": {"type": "object"}}}
}
"""


@pytest.fixture
def embed_client():
    """UI client with an OpenAPI spec and markdown documents that embed it."""
    with TemporaryDirectory() as tmpdir:
        fs = FileSystem(Path(tmpdir))
        fs.write_file("specs/orders.json", _SAMPLE_OPENAPI)
        fs.write_file(
            "plans/q2.md",
            "# Q2 Plan\n\n"
            "```stash-embed\n"
            "src: /specs/orders.json\n"
            "tag: orders\n"
            "```\n\n"
            "More notes.\n",
        )
        fs.write_file(
            "plans/relative.md",
            "```stash-embed\n"
            "src: ../specs/orders.json\n"
            "path: /health\n"
            "```\n",
        )
        fs.write_file(
            "plans/missing.md",
            "```stash-embed\nsrc: specs/nope.json\n```\n",
        )
        fs.write_file(
            "plans/notapi.md",
            "```stash-embed\nsrc: /plans/q2.md\n```\n",
        )
        fs.write_file(
            "plans/nomatch.md",
            "```stash-embed\nsrc: /specs/orders.json\ntag: ghost\n```\n",
        )
        fs.write_file(
            "plans/badyaml.md",
            "```stash-embed\nsrc: /specs/orders.json\n  tag: : :\n  - bad\n```\n",
        )
        fs.write_file(
            "plans/nosrc.md",
            "```stash-embed\ntag: orders\n```\n",
        )

        app = create_api(fs)
        router = create_ui_router(fs)
        app.include_router(router)
        yield TestClient(app)


class TestUIEmbed:
    """Tests for ```stash-embed``` OpenAPI fragment embedding."""

    def test_embed_by_tag_renders_inline_openapi(self, embed_client):
        body = embed_client.get("/ui/browse/plans/q2.md").text
        assert "embedded-openapi" in body
        assert "Orders API</h1>" in body
        # Surrounding markdown is preserved.
        assert "Q2 Plan</h1>" in body
        assert "More notes." in body
        # Tag filter kept orders operations and excluded health.
        assert "List orders" in body
        assert "Create order" in body
        assert "Healthcheck" not in body
        # Filtered embeds drop the schemas block.
        assert "SCHEMA" not in body

    def test_embed_resolves_relative_src(self, embed_client):
        body = embed_client.get("/ui/browse/plans/relative.md").text
        assert "embedded-openapi" in body
        # path filter kept only /health.
        assert "Healthcheck" in body
        assert "List orders" not in body
        assert "Create order" not in body

    def test_embed_missing_source_shows_error(self, embed_client):
        body = embed_client.get("/ui/browse/plans/missing.md").text
        assert "Embed error" in body
        assert "source not found" in body

    def test_embed_non_openapi_source_shows_error(self, embed_client):
        body = embed_client.get("/ui/browse/plans/notapi.md").text
        assert "Embed error" in body
        # The dispatcher can't infer a type from a markdown source.
        assert "could not determine embed type" in body

    def test_embed_no_matches_shows_error(self, embed_client):
        body = embed_client.get("/ui/browse/plans/nomatch.md").text
        assert "Embed error" in body
        assert "no operations" in body

    def test_embed_invalid_yaml_shows_error(self, embed_client):
        body = embed_client.get("/ui/browse/plans/badyaml.md").text
        assert "Embed error" in body

    def test_embed_missing_src_shows_error(self, embed_client):
        body = embed_client.get("/ui/browse/plans/nosrc.md").text
        assert "Embed error" in body
        assert "src" in body and "field" in body


_SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Q2 Report</title></head>
<body>
<section id="summary"><h2>Summary</h2><p>Things are on track.</p></section>
<section id="risks" class="callout"><h2>Risks</h2>
<ul><li>backfill throughput</li><li>region drift</li></ul></section>
<section id="links"><a href="/internal">internal</a></section>
</body>
</html>
"""


@pytest.fixture
def html_embed_client():
    """UI client with an HTML doc and markdown that embeds slices of it."""
    with TemporaryDirectory() as tmpdir:
        fs = FileSystem(Path(tmpdir))
        fs.write_file("reports/q2.html", _SAMPLE_HTML)
        fs.write_file(
            "plans/with_selector.md",
            "# Plan\n\n"
            "```stash-embed\n"
            "src: /reports/q2.html\n"
            "selector: \"#risks\"\n"
            "```\n",
        )
        fs.write_file(
            "plans/no_selector.md",
            "```stash-embed\nsrc: /reports/q2.html\n```\n",
        )
        fs.write_file(
            "plans/no_match.md",
            "```stash-embed\nsrc: /reports/q2.html\nselector: \"#ghost\"\n```\n",
        )
        fs.write_file(
            "plans/class_selector.md",
            "```stash-embed\nsrc: /reports/q2.html\nselector: \".callout li\"\n```\n",
        )
        # Force a non-html-extension file to be treated as html via the override.
        fs.write_file("snippets/raw.txt", "<div id=\"note\">forced</div>")
        fs.write_file(
            "plans/type_override.md",
            "```stash-embed\n"
            "src: /snippets/raw.txt\n"
            "type: html\n"
            "selector: \"#note\"\n"
            "```\n",
        )
        # Ambiguous file (plain .txt) without an override should error.
        fs.write_file("snippets/plain.txt", "just some text")
        fs.write_file(
            "plans/ambiguous.md",
            "```stash-embed\nsrc: /snippets/plain.txt\n```\n",
        )

        app = create_api(fs)
        router = create_ui_router(fs)
        app.include_router(router)
        yield TestClient(app)


class TestUIEmbedHTML:
    """Tests for HTML fragment embedding via ```stash-embed```."""

    def test_embed_html_by_id_selector(self, html_embed_client):
        body = html_embed_client.get("/ui/browse/plans/with_selector.md").text
        assert "embedded-html" in body
        # Selector kept #risks and its contents.
        assert "Risks</h2>" in body
        assert "backfill throughput" in body
        # Other sections were excluded.
        assert "Summary</h2>" not in body
        assert "Things are on track" not in body

    def test_embed_html_compound_selector(self, html_embed_client):
        body = html_embed_client.get("/ui/browse/plans/class_selector.md").text
        assert "embedded-html" in body
        assert "backfill throughput" in body
        assert "region drift" in body
        # Headings outside the selector are gone.
        assert "Risks</h2>" not in body

    def test_embed_html_without_selector_returns_body(self, html_embed_client):
        import re as _re
        body = html_embed_client.get("/ui/browse/plans/no_selector.md").text
        match = _re.search(
            r'<div class="embedded-html[^"]*">(.*?)</div>\s*<', body, _re.DOTALL,
        )
        assert match, "embedded-html block not found"
        embed_inner = match.group(1)
        # All three sections present when no selector filters them.
        assert "Summary</h2>" in embed_inner
        assert "Risks</h2>" in embed_inner
        # We return body's *contents*, not the <body> tag itself.
        assert "<body" not in embed_inner

    def test_embed_html_no_match_shows_error(self, html_embed_client):
        body = html_embed_client.get("/ui/browse/plans/no_match.md").text
        assert "Embed error" in body
        assert "no elements" in body
        assert "#ghost" in body

    def test_embed_type_override_forces_html(self, html_embed_client):
        body = html_embed_client.get("/ui/browse/plans/type_override.md").text
        assert "embedded-html" in body
        assert "forced" in body

    def test_embed_ambiguous_src_without_type_errors(self, html_embed_client):
        body = html_embed_client.get("/ui/browse/plans/ambiguous.md").text
        assert "Embed error" in body
        assert "could not determine embed type" in body

    def test_embed_html_rewrites_root_selectors_to_scope(self):
        """`body { color }` in the source should become `:scope { color }` so
        it applies to the embed wrapper, not to a (nonexistent) <body> inside
        the embed. Other selectors also get a `:scope ` prefix to gain
        class-level specificity (see test_embed_html_boosts_selector_specificity)."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "src.html",
                "<!DOCTYPE html><html><head>"
                "<style>"
                "body { color: #1e1e2e; font-family: serif; }"
                "html, body { margin: 0; }"
                ":root { --accent: red; }"
                ".body-text { color: blue; }"
                "p body { not-a-real-rule: 1; }"
                "</style></head><body>"
                "<section id=\"a\">hi</section>"
                "</body></html>",
            )
            fs.write_file("host.md", "```stash-embed\nsrc: /src.html\nselector: \"#a\"\n```\n")
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/host.md").text

        # Root selectors got rewritten to :scope.
        assert ":scope { color: #1e1e2e; font-family: serif; }" in body
        assert ":scope, :scope { margin: 0; }" in body
        assert ":scope { --accent: red; }" in body
        # Non-root selectors get the specificity-boost prefix; the `body`
        # substring inside class names and non-leading positions is preserved.
        assert ":scope .body-text { color: blue; }" in body
        assert ":scope p body { not-a-real-rule: 1; }" in body

    def test_embed_html_emits_host_style_reset(self):
        """A reset block forces text-bearing elements to revert host styles so
        rules like `.markdown-body th { background }` and `.markdown-body code
        { background }` don't bleed into the embed. The reset uses `all: revert`
        with specificity (0,1,1) — ties host's `.markdown-body <el>` rules and
        wins by source order. Source class rules (0,2,0+) still override it."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "src.html",
                "<head><style>body { color: green; } h2 { margin-top: 0; } "
                ".metric { color: red; }</style></head>"
                "<body><section id=\"a\"><h2>x</h2></section></body>",
            )
            fs.write_file("host.md", "```stash-embed\nsrc: /src.html\nselector: \"#a\"\n```\n")
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/host.md").text

        # Reset is present and uses `all: revert`.
        reset_idx = body.find(":scope h1, :scope h2")
        source_h2_idx = body.find(":scope h2 { margin-top: 0; }")
        source_root_idx = body.find(":scope { color: green; }")
        assert reset_idx >= 0
        assert "all: revert" in body
        # Reset comes before the source's own rules so source wins by order.
        assert source_h2_idx > reset_idx
        assert source_root_idx > reset_idx
        # The reset covers common host-bleed elements: headings, lists, tables,
        # code blocks, inline emphasis.
        for token in ["h1", "h2", "h3", "p", "a", "li", "th", "td",
                      "blockquote", "code", "pre", "strong"]:
            assert f":scope {token}" in body

    def test_embed_html_emits_reset_even_without_source_styles(self):
        """A source with no <style> block still needs the reset so host
        markdown rules like `.markdown-body code { background: #181825 }`
        don't leak through to bare HTML snippets."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "snippet.html",
                "<div id=\"note\">Use <code>x</code> here.</div>",
            )
            fs.write_file(
                "host.md",
                "```stash-embed\nsrc: /snippet.html\nselector: \"#note\"\n```\n",
            )
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/host.md").text

        # Even with no <style> in the source, the @scope block + reset is emitted.
        assert "<style>@scope (.embed-" in body
        assert "all: revert" in body
        assert ":scope code" in body

    def test_embed_html_boosts_selector_specificity(self):
        """Every non-root selector gets a `:scope ` prefix so source rules tie
        with host rules like `.markdown-body h2 { color: ... }` and win on
        source order. Without this, naked `h2 { ... }` in the source has
        specificity (0,0,1) and loses to the host's (0,1,1)."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "src.html",
                "<head><style>"
                "h2 { color: green; }"
                "section.callout { background: yellow; }"
                ".metric { font-weight: 700; }"
                "</style></head><body>"
                "<section id=\"a\" class=\"callout\"><h2>hi</h2></section>"
                "</body>",
            )
            fs.write_file("host.md", "```stash-embed\nsrc: /src.html\nselector: \"#a\"\n```\n")
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/host.md").text

        assert ":scope h2 { color: green; }" in body
        assert ":scope section.callout { background: yellow; }" in body
        assert ":scope .metric { font-weight: 700; }" in body

    def test_embed_html_styled_source(self):
        """Standalone test: source with <style> emits a scoped @scope block."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "src.html",
                "<!DOCTYPE html><html><head>"
                "<style>section { border-left: 3px solid red; } "
                ".callout { background: yellow; }</style>"
                "</head><body>"
                "<section id=\"a\" class=\"callout\">hello</section>"
                "</body></html>",
            )
            fs.write_file(
                "host.md",
                "```stash-embed\nsrc: /src.html\nselector: \"#a\"\n```\n",
            )
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/host.md").text

        # The fragment is present.
        assert "hello" in body
        # The source's <style> rules were copied across, with :scope prefix.
        assert ":scope section { border-left: 3px solid red" in body
        assert ":scope .callout { background: yellow" in body
        # And they were wrapped in an @scope rule keyed to this embed.
        assert "@scope (.embed-" in body
        # The fragment carries the matching scope class on its wrapper.
        import re as _re
        scope_match = _re.search(r"@scope \(\.(embed-[a-f0-9]+)\)", body)
        assert scope_match
        scope_class = scope_match.group(1)
        assert f'class="embedded-html {scope_class}"' in body

    def test_embed_html_preserves_keyframes(self):
        """`@keyframes` step lists (`0%`, `from`, `to`) are NOT CSS selectors —
        they must not be prefixed with `:scope` or the animation breaks."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "src.html",
                "<head><style>"
                "@keyframes fade { 0% { opacity: 0; } 100% { opacity: 1; } }"
                "@-webkit-keyframes slide { from { left: 0; } to { left: 10px; } }"
                ".box { animation: fade 1s; }"
                "</style></head>"
                "<body><section id=\"a\"><div class=\"box\">hi</div></section></body>",
            )
            fs.write_file(
                "host.md",
                "```stash-embed\nsrc: /src.html\nselector: \"#a\"\n```\n",
            )
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/host.md").text

        # Keyframe step lists pass through unchanged — no `:scope` prefix
        # injected into `0%`, `100%`, `from`, `to`.
        assert "0% { opacity: 0; }" in body
        assert "100% { opacity: 1; }" in body
        assert "from { left: 0; }" in body
        assert "to { left: 10px; }" in body
        assert ":scope 0%" not in body
        assert ":scope from " not in body
        assert ":scope to " not in body
        # The keyframes at-rule prelude itself is also intact.
        assert "@keyframes fade" in body
        assert "@-webkit-keyframes slide" in body
        # Non-keyframe selectors still get scoped.
        assert ":scope .box" in body

    def test_embed_html_strips_scripts(self):
        """`<script>` elements and `on*` event handlers from embedded HTML are
        stripped so they can't execute in the host document's origin (standalone
        `.html` views run in a sandboxed iframe; embeds inject directly)."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "src.html",
                "<body>"
                "<script>window.pwned = 1;</script>"
                "<div id=\"a\" onclick=\"alert(1)\" onmouseover=\"x()\">"
                "<a href=\"javascript:alert(2)\">bad</a>"
                "<a href=\"/safe\">good</a>"
                "</div></body>",
            )
            fs.write_file(
                "host.md",
                "```stash-embed\nsrc: /src.html\nselector: \"#a\"\n```\n",
            )
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/host.md").text

        # Isolate the embed wrapper — the host UI has its own onclick handlers
        # on sidebar buttons, so we can't assert against the whole page.
        import re as _re
        m = _re.search(r'<div class="embedded-html[^"]*">(.*?)</div>', body, _re.DOTALL)
        assert m, "embedded-html wrapper not found"
        embed = m.group(1)

        # No <script>, no event handler attrs, no javascript: URL.
        assert "window.pwned" not in body
        assert "<script" not in embed
        assert "onclick" not in embed
        assert "onmouseover" not in embed
        assert "javascript:alert" not in embed
        # But the safe link and surrounding content are kept.
        assert 'href="/safe"' in embed
        assert ">good<" in embed

    def test_embed_html_rewrites_relative_urls_to_source_dir(self):
        """Relative `src`/`href` inside an embedded fragment must resolve
        relative to the *source HTML's* directory, not the embedding markdown's
        directory. Otherwise `<img src="images/foo.png">` in `reports/q2.html`
        embedded from `plans/draft.md` points at `/ui/raw/plans/images/foo.png`."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file(
                "reports/q2.html",
                "<body><div id=\"a\">"
                "<img src=\"images/foo.png\">"
                "<a href=\"sibling.html\">sib</a>"
                "</div></body>",
            )
            fs.write_file(
                "plans/draft.md",
                "```stash-embed\nsrc: /reports/q2.html\nselector: \"#a\"\n```\n",
            )
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/plans/draft.md").text

        # img src rewritten under reports/, not plans/.
        assert 'src="/ui/raw/reports/images/foo.png"' in body
        assert "/ui/raw/plans/images/" not in body
        # anchor href rewritten under reports/ via /ui/browse/.
        assert 'href="/ui/browse/reports/sibling.html"' in body


class TestUIEmbedOpenAPIYamlOverride:
    """Edge case: `type: openapi` with a YAML spec under a non-yaml extension."""

    def test_openapi_yaml_under_txt_with_explicit_type(self):
        """YAML 1.1 parses JSON as a subset, so a single `yaml.safe_load` should
        handle openapi specs regardless of file extension when the user sets
        `type: openapi` explicitly."""
        yaml_spec = (
            "openapi: 3.0.0\n"
            "info:\n"
            "  title: X\n"
            "  version: '1.0'\n"
            "paths:\n"
            "  /things:\n"
            "    get:\n"
            "      operationId: listThings\n"
            "      responses:\n"
            "        '200':\n"
            "          description: OK\n"
        )
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            # Stored under .txt — `_infer_embed_type` would not pick this up
            # automatically; the user must override with `type: openapi`.
            fs.write_file("specs/things.txt", yaml_spec)
            fs.write_file(
                "plans/use.md",
                "```stash-embed\n"
                "src: /specs/things.txt\n"
                "type: openapi\n"
                "```\n",
            )
            app = create_api(fs)
            app.include_router(create_ui_router(fs))
            body = TestClient(app).get("/ui/browse/plans/use.md").text

        # Parsed correctly: operation appears in the embed.
        assert "Embed error" not in body
        assert "listThings" in body
        assert "embedded-openapi" in body


class TestUISearch:
    """Tests for sidebar search functionality."""

    def test_sidebar_has_search_input(self, ui_client):
        """Sidebar should contain a search input."""
        response = ui_client.get("/ui/browse/")
        body = response.text
        assert "tree-search" in body
        assert "handleSearch" in body

    def test_sidebar_without_search_engine_has_filename_filter(self, ui_client):
        """Without search engine, sidebar uses file name placeholder."""
        response = ui_client.get("/ui/browse/")
        body = response.text
        assert "Search files..." in body
        assert 'data-vector-search="true"' not in body
        assert 'id="search-results"' not in body

    def test_sidebar_with_search_engine_has_vector_search(self):
        """With search engine, sidebar uses vector search placeholder and container."""
        from stash_mcp.search import SearchEngine

        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as idx_dir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file("hello.md", "# Hello World")
            engine = SearchEngine(
                content_dir=Path(tmpdir),
                index_dir=Path(idx_dir),
                embed_fn=_mock_embed,
            )
            app = create_api(fs)
            router = create_ui_router(fs, search_engine=engine)
            app.include_router(router)
            client = TestClient(app)
            response = client.get("/ui/browse/")
            body = response.text
            assert "Search content" in body
            assert "data-vector-search" in body
            assert 'id="search-results"' in body
            assert "data.indexing" in body
            assert "index is being rebuilt" in body
            assert "search-spinner" in body
            assert "search-loading" in body

    def test_ui_search_endpoint_returns_results(self):
        """GET /ui/search returns vector search results as JSON."""
        from stash_mcp.search import SearchEngine

        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as idx_dir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file("docs/auth.md", "# Auth\n\nOAuth2 flow here.")
            fs.write_file("notes.md", "# Meeting Notes\n\nDiscussed timeline.")
            engine = SearchEngine(
                content_dir=Path(tmpdir),
                index_dir=Path(idx_dir),
                embed_fn=_mock_embed,
                filesystem=fs,
            )
            app = create_api(fs)
            router = create_ui_router(fs, search_engine=engine)
            app.include_router(router)
            client = TestClient(app)

            # Build index first
            import asyncio
            asyncio.run(engine.build_index(fs.list_all_files()))

            response = client.get("/ui/search", params={"q": "authentication OAuth"})
            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert data["total"] > 0
            assert "indexing" in data
            assert data["indexing"] is False
            result = data["results"][0]
            assert "file_path" in result
            assert "content" in result
            assert "score" in result

    def test_ui_search_empty_query_returns_empty(self):
        """GET /ui/search with empty query returns empty results."""
        from stash_mcp.search import SearchEngine

        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as idx_dir:
            fs = FileSystem(Path(tmpdir))
            engine = SearchEngine(
                content_dir=Path(tmpdir),
                index_dir=Path(idx_dir),
                embed_fn=_mock_embed,
            )
            app = create_api(fs)
            router = create_ui_router(fs, search_engine=engine)
            app.include_router(router)
            client = TestClient(app)

            response = client.get("/ui/search", params={"q": ""})
            assert response.status_code == 200
            data = response.json()
            assert data["results"] == []
            assert data["total"] == 0

    def test_no_search_endpoint_without_engine(self, ui_client):
        """GET /ui/search returns 404 when search engine is not enabled."""
        response = ui_client.get("/ui/search", params={"q": "test"})
        assert response.status_code in (404, 405)


class TestUIFeatures:
    """Tests for UI enhancement features."""

    def test_keyboard_shortcuts_in_js(self, ui_client):
        """Page should include keyboard shortcut handlers."""
        response = ui_client.get("/ui/browse/hello.md")
        body = response.text
        assert "keydown" in body
        assert "ctrlKey" in body

    def test_unsaved_changes_warning_in_js(self, ui_client):
        """Edit page should include unsaved changes warning."""
        response = ui_client.get("/ui/edit/hello.md")
        body = response.text
        assert "beforeunload" in body
        assert "_unsaved" in body

    def test_save_bar_css(self, ui_client):
        """Action bar CSS should be present in edit page."""
        response = ui_client.get("/ui/edit/hello.md")
        body = response.text
        assert "action-bar" in body
        assert "btn-save" in body

    def test_scrollbar_css(self, ui_client):
        """Page should include custom scrollbar styles."""
        response = ui_client.get("/ui/browse/")
        body = response.text
        assert "scrollbar-width:thin" in body
        assert "::-webkit-scrollbar" in body


class TestUIEvents:
    """Tests for event emission from UI mutation routes."""

    @pytest.fixture
    def ui_client_with_listener(self):
        """Create a test client with event listener attached."""
        from unittest.mock import MagicMock

        from stash_mcp.events import _listeners, add_listener

        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file("hello.md", "# Hello World")

            app = create_api(fs)
            router = create_ui_router(fs)
            app.include_router(router)
            client = TestClient(app)

            listener = MagicMock()
            add_listener(listener)
            yield client, listener
            _listeners.remove(listener)

    def test_ui_save_new_file_emits_created(self, ui_client_with_listener):
        """POST /ui/save for a new file emits content_created event."""
        client, listener = ui_client_with_listener
        client.post(
            "/ui/save",
            data={"path": "new.md", "content": "# New"},
            follow_redirects=False,
        )
        listener.assert_called_once()
        args = listener.call_args[0]
        assert args[0] == "content_created"
        assert args[1] == "new.md"

    def test_ui_save_existing_file_emits_updated(self, ui_client_with_listener):
        """POST /ui/save for an existing file emits content_updated event."""
        client, listener = ui_client_with_listener
        client.post(
            "/ui/save",
            data={"path": "hello.md", "content": "# Updated"},
            follow_redirects=False,
        )
        listener.assert_called_once()
        args = listener.call_args[0]
        assert args[0] == "content_updated"
        assert args[1] == "hello.md"

    def test_ui_delete_emits_deleted(self, ui_client_with_listener):
        """POST /ui/delete emits content_deleted event."""
        client, listener = ui_client_with_listener
        client.post("/ui/delete/hello.md", follow_redirects=False)
        listener.assert_called_once()
        args = listener.call_args[0]
        assert args[0] == "content_deleted"
        assert args[1] == "hello.md"

    def test_ui_move_emits_moved(self, ui_client_with_listener):
        """POST /ui/move emits content_moved event with correct kwargs."""
        client, listener = ui_client_with_listener
        client.post(
            "/ui/move/hello.md",
            data={"destination": "renamed.md"},
            follow_redirects=False,
        )
        listener.assert_called_once()
        args = listener.call_args[0]
        kwargs = listener.call_args[1]
        assert args[0] == "content_moved"
        assert args[1] == "renamed.md"
        assert kwargs.get("source_path") == "hello.md"


class TestUIReadOnly:
    """Tests for read-only mode (STASH_READ_ONLY=true) in the UI."""

    @pytest.fixture
    def ro_client(self):
        """Create a test client with UI router in read-only mode."""
        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            fs.write_file("hello.md", "# Hello World")
            fs.write_file("docs/readme.md", "# README")

            app = create_api(fs)
            router = create_ui_router(fs, read_only=True)
            app.include_router(router)
            client = TestClient(app)
            yield client

    # --- UI elements hidden in read-only mode ---

    def test_no_new_document_button(self, ro_client):
        """Sidebar should not show the New Document button in read-only mode."""
        response = ro_client.get("/ui/browse/")
        assert response.status_code == 200
        assert 'href="/ui/new"' not in response.text
        assert "New Document" not in response.text

    def test_no_edit_tab_in_browse(self, ro_client):
        """File view should not show the Edit tab in read-only mode."""
        response = ro_client.get("/ui/browse/hello.md")
        assert response.status_code == 200
        assert 'href="/ui/edit/hello.md"' not in response.text

    def test_no_rename_button_in_browse(self, ro_client):
        """File view should not show the Rename/Move button in read-only mode."""
        response = ro_client.get("/ui/browse/hello.md")
        assert response.status_code == 200
        assert 'class="btn-rename"' not in response.text
        assert "Rename / Move" not in response.text

    def test_no_delete_button_in_browse(self, ro_client):
        """File view should not show the Delete button in read-only mode."""
        response = ro_client.get("/ui/browse/hello.md")
        assert response.status_code == 200
        assert 'class="btn-delete"' not in response.text

    # --- Write endpoints return 403 in read-only mode ---

    def test_edit_page_returns_403(self, ro_client):
        """GET /ui/edit/ returns 403 in read-only mode."""
        response = ro_client.get("/ui/edit/hello.md")
        assert response.status_code == 403

    def test_new_page_returns_403(self, ro_client):
        """GET /ui/new returns 403 in read-only mode."""
        response = ro_client.get("/ui/new")
        assert response.status_code == 403

    def test_save_returns_403(self, ro_client):
        """POST /ui/save returns 403 in read-only mode."""
        response = ro_client.post(
            "/ui/save",
            data={"path": "new.md", "content": "# New"},
            follow_redirects=False,
        )
        assert response.status_code == 403

    def test_move_returns_403(self, ro_client):
        """POST /ui/move returns 403 in read-only mode."""
        response = ro_client.post(
            "/ui/move/hello.md",
            data={"destination": "renamed.md"},
            follow_redirects=False,
        )
        assert response.status_code == 403

    def test_delete_returns_403(self, ro_client):
        """POST /ui/delete returns 403 in read-only mode."""
        response = ro_client.post("/ui/delete/hello.md", follow_redirects=False)
        assert response.status_code == 403

    # --- Read operations still work in read-only mode ---

    def test_browse_still_works(self, ro_client):
        """GET /ui/browse/ still works in read-only mode."""
        response = ro_client.get("/ui/browse/")
        assert response.status_code == 200
        assert "hello.md" in response.text

    def test_browse_file_still_works(self, ro_client):
        """GET /ui/browse/<file> still works in read-only mode."""
        response = ro_client.get("/ui/browse/hello.md")
        assert response.status_code == 200
        assert "Hello World" in response.text
