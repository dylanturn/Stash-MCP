"""Tests for UI routes."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from stash_mcp.api import create_api
from stash_mcp.filesystem import FileSystem
from stash_mcp.ui import create_ui_router


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
        assert "<h1>Hello World</h1>" in body
        assert "markdown-body" in body
        # Should show metadata panel
        assert "text/markdown" in body
        # Should have edit link
        assert "/ui/edit/hello.md" in body

    def test_browse_file_has_breadcrumbs(self, ui_client):
        """File view includes breadcrumb navigation."""
        response = ui_client.get("/ui/browse/docs/readme.md")
        assert response.status_code == 200
        body = response.text
        # Should have breadcrumb links
        assert "Home" in body
        assert "docs" in body
        assert "readme.md" in body

    def test_browse_file_has_metadata(self, ui_client):
        """File view shows metadata in right panel."""
        response = ui_client.get("/ui/browse/hello.md")
        assert response.status_code == 200
        body = response.text
        assert "File Info" in body
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
        assert "<h1>New File</h1>" in view_resp.text

    def test_save_updates_existing_file(self, ui_client):
        """POST /ui/save updates existing file content."""
        response = ui_client.post(
            "/ui/save",
            data={"path": "hello.md", "content": "# Updated"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        view_resp = ui_client.get("/ui/browse/hello.md")
        assert "<h1>Updated</h1>" in view_resp.text

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


class TestUIMarkdown:
    """Tests for markdown rendering."""

    def test_markdown_file_rendered_as_html(self, ui_client):
        """Markdown files should be rendered to HTML, not shown raw."""
        response = ui_client.get("/ui/browse/hello.md")
        body = response.text
        assert "markdown-body" in body
        assert "<h1>Hello World</h1>" in body

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
        assert "<h1>README</h1>" in body
        assert "Some content here." in body


class TestUISearch:
    """Tests for sidebar search functionality."""

    def test_sidebar_has_search_input(self, ui_client):
        """Sidebar should contain a search input."""
        response = ui_client.get("/ui/browse/")
        body = response.text
        assert "tree-search" in body
        assert "Search files..." in body
        assert "filterTree" in body


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

    def test_sticky_save_bar_css(self, ui_client):
        """Action bar CSS should include sticky positioning."""
        response = ui_client.get("/ui/edit/hello.md")
        body = response.text
        assert "position:sticky" in body
        assert "backdrop-filter" in body

    def test_scrollbar_css(self, ui_client):
        """Page should include custom scrollbar styles."""
        response = ui_client.get("/ui/browse/")
        body = response.text
        assert "scrollbar-width:thin" in body
        assert "::-webkit-scrollbar" in body
