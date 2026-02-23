"""Tests for MCP server implementation."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stash_mcp.filesystem import FileNotFoundError, FileSystem
from stash_mcp.mcp_server import EditOperation, FileEditOperation, _get_mime_type, create_mcp_server


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_fs():
    """Create a temporary filesystem for testing."""
    with TemporaryDirectory() as tmpdir:
        fs = FileSystem(Path(tmpdir))
        yield fs


@pytest.fixture
def mcp_server(temp_fs):
    """Create a FastMCP server with temporary filesystem."""
    temp_fs.write_file("README.md", "# Root README")
    temp_fs.write_file("docs/README.md", "# Docs README\nSome docs")
    temp_fs.write_file("data.json", '{"key": "value"}')
    return create_mcp_server(temp_fs)


@pytest.fixture
def mock_context():
    """Set up a mock Context in FastMCP's _current_context ContextVar."""
    from fastmcp.server.context import Context, _current_context

    ctx = MagicMock(spec=Context)
    ctx.session = AsyncMock()
    ctx.send_resource_list_changed = AsyncMock()
    token = _current_context.set(ctx)
    yield ctx
    _current_context.reset(token)


# --- Mime type tests ---


def test_get_mime_type_markdown():
    """Test mime type detection for markdown files."""
    assert _get_mime_type("file.md") == "text/markdown"
    assert _get_mime_type("file.markdown") == "text/markdown"


def test_get_mime_type_json():
    """Test mime type detection for JSON files."""
    assert _get_mime_type("file.json") == "application/json"


def test_get_mime_type_yaml():
    """Test mime type detection for YAML files."""
    assert _get_mime_type("file.yaml") == "application/x-yaml"
    assert _get_mime_type("file.yml") == "application/x-yaml"


def test_get_mime_type_default():
    """Test default mime type for unknown extensions."""
    assert _get_mime_type("file.xyz") == "text/plain"
    assert _get_mime_type("file") == "text/plain"


# --- Resource tests ---


async def test_list_resources(mcp_server):
    """Test listing resources returns only README.md files."""
    resources = await mcp_server.get_resources()
    uris = list(resources.keys())
    # Only README.md files should be registered as resources
    assert "stash://README.md" in uris
    assert "stash://docs/README.md" in uris
    # Other files should NOT be in the resource list
    assert "stash://data.json" not in uris


async def test_resource_mime_types(mcp_server):
    """Test that resources have correct mime types."""
    resources = await mcp_server.get_resources()
    md_resource = resources.get("stash://README.md")
    assert md_resource is not None
    assert md_resource.mime_type == "text/markdown"

    # Non-README files should not be registered
    json_resource = resources.get("stash://data.json")
    assert json_resource is None


async def test_resource_templates(mcp_server):
    """Test that resource template is registered."""
    templates = await mcp_server.get_resource_templates()
    assert "stash://{path}" in templates


async def test_read_resource_via_template(mcp_server):
    """Test reading a resource through the resource template."""
    # README.md is registered, so it can be accessed
    resource = await mcp_server.get_resource("stash://README.md")
    content = resource.fn()
    assert content == "# Root README"


# --- Tool tests ---


async def test_list_tools(mcp_server):
    """Test listing tools returns all expected tools."""
    tools = await mcp_server.get_tools()
    tool_names = list(tools.keys())
    assert "create_content" in tool_names
    assert "read_content" in tool_names
    assert "replace_content" in tool_names
    assert "edit_content" in tool_names
    assert "multi_edit_content" in tool_names
    assert "delete_content" in tool_names
    assert "list_content" in tool_names
    assert "read_content_batch" in tool_names
    assert "move_content" in tool_names


async def test_create_content_tool(temp_fs, mock_context):
    """Test create_content tool creates a file."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    result = await tool.run({"path": "new.md", "content": "# New File"})
    assert "Created: new.md" in str(result.content)
    assert temp_fs.file_exists("new.md")
    assert temp_fs.read_file("new.md") == "# New File"


async def test_create_content_tool_nested_path(temp_fs, mock_context):
    """Test create_content tool creates missing parent directories."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    result = await tool.run({"path": "a/b/c/new.md", "content": "# Nested"})
    assert "Created: a/b/c/new.md" in str(result.content)
    assert temp_fs.file_exists("a/b/c/new.md")
    assert temp_fs.read_file("a/b/c/new.md") == "# Nested"


async def test_create_content_tool_existing_file(mcp_server, temp_fs, mock_context):
    """Test create_content tool errors on existing file."""
    tool = await mcp_server.get_tool("create_content")
    with pytest.raises(ValueError, match="already exists"):
        await tool.run({"path": "README.md", "content": "overwrite"})


async def test_read_content_tool(mcp_server):
    """Test read_content tool reads a file and returns sha."""
    tool = await mcp_server.get_tool("read_content")
    result = await tool.run({"path": "README.md"})
    text = str(result.content)
    assert "# Root README" in text
    assert "sha" in text


async def test_read_content_tool_not_found(mcp_server):
    """Test read_content tool errors on missing file."""
    tool = await mcp_server.get_tool("read_content")
    with pytest.raises(FileNotFoundError):
        await tool.run({"path": "nonexistent.md"})


# --- read_content_batch tests ---


async def test_read_content_batch_happy_path(mcp_server):
    """Test read_content_batch returns content and sha for multiple files."""
    tool = await mcp_server.get_tool("read_content_batch")
    result = await tool.run({"paths": ["README.md", "data.json"]})
    text = str(result.content)
    assert "# Root README" in text
    assert _sha("# Root README") in text
    assert "data.json" in text
    assert _sha('{"key": "value"}') in text


async def test_read_content_batch_partial_failure(mcp_server):
    """Test read_content_batch returns error for missing files without aborting."""
    tool = await mcp_server.get_tool("read_content_batch")
    result = await tool.run({"paths": ["README.md", "nonexistent.md"]})
    text = str(result.content)
    # Existing file should be returned successfully
    assert "# Root README" in text
    assert _sha("# Root README") in text
    # Missing file should have an error entry
    assert "nonexistent.md" in text
    assert "error" in text


async def test_read_content_batch_empty_list(mcp_server):
    """Test read_content_batch rejects empty path list."""
    tool = await mcp_server.get_tool("read_content_batch")
    with pytest.raises(ValueError, match="At least one path is required"):
        await tool.run({"paths": []})


async def test_read_content_batch_over_limit(mcp_server):
    """Test read_content_batch rejects more than 10 paths."""
    tool = await mcp_server.get_tool("read_content_batch")
    with pytest.raises(ValueError, match="Maximum 10 files per batch read"):
        await tool.run({"paths": [f"file{i}.md" for i in range(11)]})


async def test_read_content_batch_duplicate_paths(mcp_server):
    """Test read_content_batch rejects duplicate paths."""
    tool = await mcp_server.get_tool("read_content_batch")
    with pytest.raises(ValueError, match="Duplicate paths are not allowed"):
        await tool.run({"paths": ["README.md", "README.md"]})


async def test_read_content_batch_order_preserved(mcp_server, temp_fs):
    """Test read_content_batch returns results in the same order as input paths."""
    tool = await mcp_server.get_tool("read_content_batch")
    result = await tool.run({"paths": ["data.json", "README.md", "docs/README.md"]})
    # Extract result order from the content string
    text = str(result.content)
    pos_data = text.find("data.json")
    pos_root = text.find('"README.md"')
    pos_docs = text.find("docs/README.md")
    assert pos_data < pos_root < pos_docs


async def test_read_content_batch_all_missing(mcp_server):
    """Test read_content_batch with all missing files returns errors for each."""
    tool = await mcp_server.get_tool("read_content_batch")
    result = await tool.run({"paths": ["missing1.md", "missing2.md"]})
    text = str(result.content)
    assert "missing1.md" in text
    assert "missing2.md" in text
    # No content should be present, only errors
    assert "error" in text


async def test_replace_content_tool(mcp_server, temp_fs, mock_context):
    """Test replace_content tool updates an existing file."""
    tool = await mcp_server.get_tool("replace_content")
    result = await tool.run({"path": "README.md", "content": "# Updated", "sha": _sha("# Root README")})
    assert "Updated: README.md" in str(result.content)
    assert temp_fs.read_file("README.md") == "# Updated"


async def test_delete_content_tool(mcp_server, temp_fs, mock_context):
    """Test delete_content tool deletes a file."""
    tool = await mcp_server.get_tool("delete_content")
    result = await tool.run({"path": "README.md", "sha": _sha("# Root README")})
    assert "Deleted: README.md" in str(result.content)
    assert not temp_fs.file_exists("README.md")


async def test_list_content_tool_recursive(mcp_server):
    """Test list_content tool with recursive option."""
    tool = await mcp_server.get_tool("list_content")
    result = await tool.run({"recursive": True})
    text = str(result.content)
    assert "README.md" in text
    assert "docs/README.md" in text
    assert "data.json" in text


async def test_list_content_tool_non_recursive(mcp_server):
    """Test list_content tool without recursive option."""
    tool = await mcp_server.get_tool("list_content")
    result = await tool.run({"path": "", "recursive": False})
    text = str(result.content)
    assert "README.md" in text
    assert "docs" in text


async def test_move_content_tool(mcp_server, temp_fs, mock_context):
    """Test move_content tool moves a file."""
    tool = await mcp_server.get_tool("move_content")
    result = await tool.run({"source_path": "README.md", "dest_path": "moved.md"})
    assert "Moved: README.md -> moved.md" in str(result.content)
    assert not temp_fs.file_exists("README.md")
    assert temp_fs.file_exists("moved.md")
    assert temp_fs.read_file("moved.md") == "# Root README"


async def test_move_content_tool_nested_dest(mcp_server, temp_fs, mock_context):
    """Test move_content tool creates missing directories for destination."""
    tool = await mcp_server.get_tool("move_content")
    result = await tool.run({"source_path": "data.json", "dest_path": "x/y/z/data.json"})
    assert "Moved: data.json -> x/y/z/data.json" in str(result.content)
    assert not temp_fs.file_exists("data.json")
    assert temp_fs.file_exists("x/y/z/data.json")


# --- Notification tests ---


async def test_create_registers_resource(temp_fs, mock_context):
    """Test that create_content registers README.md files as resources."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    # Create a README.md file
    await tool.run({"path": "README.md", "content": "# New"})
    resources = await mcp.get_resources()
    assert "stash://README.md" in resources

    # Create a non-README file
    await tool.run({"path": "other.md", "content": "# Other"})
    resources = await mcp.get_resources()
    # Non-README files should not be registered
    assert "stash://other.md" not in resources


async def test_create_sends_list_changed(temp_fs, mock_context):
    """Test that create_content sends resource_list_changed only for README.md files."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    
    # Creating README.md should send notification
    await tool.run({"path": "README.md", "content": "# New"})
    mock_context.send_resource_list_changed.assert_awaited_once()
    
    # Reset mock
    mock_context.send_resource_list_changed.reset_mock()
    
    # Creating non-README file should NOT send notification
    await tool.run({"path": "other.md", "content": "# Other"})
    mock_context.send_resource_list_changed.assert_not_awaited()


async def test_replace_existing_sends_resource_updated(mcp_server, mock_context):
    """Test that replacing README.md sends resource_updated notification."""
    tool = await mcp_server.get_tool("replace_content")

    # Replace README.md should send resource_updated
    await tool.run({"path": "README.md", "content": "# Changed", "sha": _sha("# Root README")})
    mock_context.session.send_resource_updated.assert_awaited_once()
    call_kwargs = mock_context.session.send_resource_updated.call_args
    assert str(call_kwargs.kwargs["uri"]) == "stash://README.md"

    # Reset mock
    mock_context.session.send_resource_updated.reset_mock()

    # Replace non-README file should NOT send resource_updated
    await tool.run({"path": "data.json", "content": '{"updated": true}', "sha": _sha('{"key": "value"}')})
    mock_context.session.send_resource_updated.assert_not_awaited()


async def test_replace_content_rejects_nonexistent_file(temp_fs, mock_context):
    """Test that replace_content errors when file does not exist."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("replace_content")

    with pytest.raises(FileNotFoundError):
        await tool.run({"path": "nonexistent.md", "content": "# New", "sha": "abc"})


async def test_replace_content_rejects_wrong_sha(mcp_server, temp_fs, mock_context):
    """Test that replace_content errors when SHA does not match."""
    tool = await mcp_server.get_tool("replace_content")

    with pytest.raises(ValueError, match="SHA mismatch"):
        await tool.run({"path": "README.md", "content": "# Changed", "sha": "wrong"})


async def test_delete_unregisters_resource(mcp_server, temp_fs, mock_context):
    """Test that delete_content removes README.md from registry."""
    resources_before = await mcp_server.get_resources()
    assert "stash://README.md" in resources_before

    tool = await mcp_server.get_tool("delete_content")
    await tool.run({"path": "README.md", "sha": _sha("# Root README")})

    resources_after = await mcp_server.get_resources()
    assert "stash://README.md" not in resources_after


async def test_delete_sends_list_changed(mcp_server, temp_fs, mock_context):
    """Test that delete_content sends notification only for README.md."""
    tool = await mcp_server.get_tool("delete_content")

    # Deleting README.md should send notification
    await tool.run({"path": "README.md", "sha": _sha("# Root README")})
    mock_context.send_resource_list_changed.assert_awaited_once()

    # Reset mock
    mock_context.send_resource_list_changed.reset_mock()

    # Deleting non-README file should NOT send notification
    await tool.run({"path": "data.json", "sha": _sha('{"key": "value"}')})
    mock_context.send_resource_list_changed.assert_not_awaited()


async def test_move_updates_resources(mcp_server, temp_fs, mock_context):
    """Test that move_content updates resource registry for README.md."""
    tool = await mcp_server.get_tool("move_content")
    
    # Moving README.md to another README.md location
    await tool.run({"source_path": "README.md", "dest_path": "other/README.md"})
    resources = await mcp_server.get_resources()
    assert "stash://README.md" not in resources
    assert "stash://other/README.md" in resources


async def test_move_sends_list_changed(mcp_server, temp_fs, mock_context):
    """Test that move_content sends notification when README.md is involved."""
    tool = await mcp_server.get_tool("move_content")
    
    # Moving README.md to another location should send notification
    await tool.run({"source_path": "README.md", "dest_path": "other/README.md"})
    mock_context.send_resource_list_changed.assert_awaited_once()
    
    # Reset mock
    mock_context.send_resource_list_changed.reset_mock()
    
    # Moving non-README file should NOT send notification
    await tool.run({"source_path": "data.json", "dest_path": "moved.json"})
    mock_context.send_resource_list_changed.assert_not_awaited()


async def test_resources_filtered_by_include_patterns(temp_fs):
    """Test that only README.md files matching patterns are registered as MCP resources."""
    # Write files of different types
    temp_fs.write_file("docs/README.md", "# Docs README")
    temp_fs.write_file("docs/guide.md", "# Guide")
    temp_fs.write_file("notes/README.md", "# Notes README")
    temp_fs.write_file("data.json", '{"key": "value"}')

    # Create a new filesystem with patterns, using the same content directory
    filtered_fs = FileSystem(temp_fs.content_dir, include_patterns=["docs/**/*.md"])
    mcp = create_mcp_server(filtered_fs)

    resources = await mcp.get_resources()
    uris = list(resources.keys())

    # Only docs/README.md should be registered (it's both README.md and matches pattern)
    assert "stash://docs/README.md" in uris
    # These should NOT be registered (either not README.md or don't match pattern)
    assert "stash://docs/guide.md" not in uris  # Not README.md
    assert "stash://notes/README.md" not in uris  # Doesn't match pattern
    assert "stash://data.json" not in uris  # Not README.md


async def test_tools_emit_events(mcp_server, temp_fs, mock_context):
    """Test that MCP tools emit events via the event bus."""
    with patch("stash_mcp.mcp_server.emit") as mock_emit:
        # Test create
        tool = await mcp_server.get_tool("create_content")
        await tool.run({"path": "evt.md", "content": "event test"})
        mock_emit.assert_called_with("content_created", "evt.md")

        mock_emit.reset_mock()

        # Test replace (existing file)
        tool = await mcp_server.get_tool("replace_content")
        await tool.run({"path": "evt.md", "content": "updated", "sha": _sha("event test")})
        mock_emit.assert_called_with("content_updated", "evt.md")

        mock_emit.reset_mock()

        # Test move
        tool = await mcp_server.get_tool("move_content")
        await tool.run({"source_path": "evt.md", "dest_path": "evt2.md"})
        mock_emit.assert_called_with("content_moved", "evt2.md", source_path="evt.md")

        mock_emit.reset_mock()

        # Test delete
        tool = await mcp_server.get_tool("delete_content")
        await tool.run({"path": "evt2.md", "sha": _sha("updated")})
        mock_emit.assert_called_with("content_deleted", "evt2.md")


# --- edit_content tests ---


async def test_edit_content_single_replacement(mcp_server, temp_fs, mock_context):
    """Test edit_content with a single replacement."""
    tool = await mcp_server.get_tool("edit_content")
    original = "# Root README"
    result = await tool.run({
        "file_path": "README.md",
        "sha": _sha(original),
        "edits": [EditOperation(old_string="Root", new_string="Updated")],
    })
    text = str(result.content)
    assert '"result": "ok"' in text or "ok" in text
    assert temp_fs.read_file("README.md") == "# Updated README"
    new_sha = _sha("# Updated README")
    assert new_sha in text


async def test_edit_content_multiple_sequential_edits(mcp_server, temp_fs, mock_context):
    """Test edit_content with multiple edits applied sequentially."""
    tool = await mcp_server.get_tool("edit_content")
    original = "# Root README"
    result = await tool.run({
        "file_path": "README.md",
        "sha": _sha(original),
        "edits": [
            EditOperation(old_string="Root", new_string="My"),
            EditOperation(old_string="README", new_string="Document"),
        ],
    })
    assert temp_fs.read_file("README.md") == "# My Document"


async def test_edit_content_replace_all(mcp_server, temp_fs, mock_context):
    """Test edit_content with replace_all=True for multiple occurrences."""
    temp_fs.write_file("repeat.md", "foo bar foo baz foo")
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("edit_content")
    await tool.run({
        "file_path": "repeat.md",
        "sha": _sha("foo bar foo baz foo"),
        "edits": [EditOperation(old_string="foo", new_string="qux", replace_all=True)],
    })
    assert temp_fs.read_file("repeat.md") == "qux bar qux baz qux"


async def test_edit_content_wrong_sha(mcp_server, temp_fs, mock_context):
    """Test edit_content rejects wrong SHA."""
    tool = await mcp_server.get_tool("edit_content")
    with pytest.raises(ValueError, match="SHA mismatch"):
        await tool.run({
            "file_path": "README.md",
            "sha": "wrong",
            "edits": [EditOperation(old_string="Root", new_string="X")],
        })


async def test_edit_content_old_string_not_found(mcp_server, temp_fs, mock_context):
    """Test edit_content raises when old_string is not in file."""
    tool = await mcp_server.get_tool("edit_content")
    with pytest.raises(ValueError, match="old_string not found"):
        await tool.run({
            "file_path": "README.md",
            "sha": _sha("# Root README"),
            "edits": [EditOperation(old_string="NONEXISTENT", new_string="X")],
        })


async def test_edit_content_ambiguous_match(mcp_server, temp_fs, mock_context):
    """Test edit_content raises on ambiguous match when replace_all=False."""
    temp_fs.write_file("dup.md", "aaa bbb aaa")
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("edit_content")
    with pytest.raises(ValueError, match="appears 2 times"):
        await tool.run({
            "file_path": "dup.md",
            "sha": _sha("aaa bbb aaa"),
            "edits": [EditOperation(old_string="aaa", new_string="ccc", replace_all=False)],
        })


async def test_edit_content_nonexistent_file(mcp_server, temp_fs, mock_context):
    """Test edit_content raises FileNotFoundError for missing file."""
    tool = await mcp_server.get_tool("edit_content")
    with pytest.raises(FileNotFoundError):
        await tool.run({
            "file_path": "nonexistent.md",
            "sha": "abc",
            "edits": [EditOperation(old_string="x", new_string="y")],
        })


async def test_edit_content_sends_resource_updated_for_readme(mcp_server, temp_fs, mock_context):
    """Test edit_content sends resource_updated for README.md but not other files."""
    tool = await mcp_server.get_tool("edit_content")

    # Edit README.md should send resource_updated
    await tool.run({
        "file_path": "README.md",
        "sha": _sha("# Root README"),
        "edits": [EditOperation(old_string="Root", new_string="Edited")],
    })
    mock_context.session.send_resource_updated.assert_awaited_once()

    mock_context.session.send_resource_updated.reset_mock()

    # Edit non-README file should NOT send resource_updated
    await tool.run({
        "file_path": "data.json",
        "sha": _sha('{"key": "value"}'),
        "edits": [EditOperation(old_string="value", new_string="updated")],
    })
    mock_context.session.send_resource_updated.assert_not_awaited()


async def test_edit_content_emits_event(mcp_server, temp_fs, mock_context):
    """Test edit_content emits CONTENT_UPDATED event."""
    with patch("stash_mcp.mcp_server.emit") as mock_emit:
        tool = await mcp_server.get_tool("edit_content")
        await tool.run({
            "file_path": "README.md",
            "sha": _sha("# Root README"),
            "edits": [EditOperation(old_string="Root", new_string="Evt")],
        })
        mock_emit.assert_called_with("content_updated", "README.md")


# --- multi_edit_content tests ---


async def test_multi_edit_content_two_files(mcp_server, temp_fs, mock_context):
    """Test multi_edit_content edits two files successfully."""
    tool = await mcp_server.get_tool("multi_edit_content")
    result = await tool.run({
        "edit_operations": [
            FileEditOperation(
                file_path="README.md",
                sha=_sha("# Root README"),
                edits=[EditOperation(old_string="Root", new_string="Multi")],
            ),
            FileEditOperation(
                file_path="data.json",
                sha=_sha('{"key": "value"}'),
                edits=[EditOperation(old_string="value", new_string="new_value")],
            ),
        ],
    })
    assert temp_fs.read_file("README.md") == "# Multi README"
    assert temp_fs.read_file("data.json") == '{"key": "new_value"}'
    text = str(result.content)
    assert "ok" in text


async def test_multi_edit_content_atomicity_bad_sha(mcp_server, temp_fs, mock_context):
    """Test multi_edit_content aborts all if one file has bad SHA."""
    tool = await mcp_server.get_tool("multi_edit_content")
    with pytest.raises(ValueError, match="SHA mismatch"):
        await tool.run({
            "edit_operations": [
                FileEditOperation(
                    file_path="README.md",
                    sha=_sha("# Root README"),
                    edits=[EditOperation(old_string="Root", new_string="Changed")],
                ),
                FileEditOperation(
                    file_path="data.json",
                    sha="wrong_sha",
                    edits=[EditOperation(old_string="value", new_string="x")],
                ),
            ],
        })
    # Neither file should have been modified
    assert temp_fs.read_file("README.md") == "# Root README"
    assert temp_fs.read_file("data.json") == '{"key": "value"}'


async def test_multi_edit_content_atomicity_bad_edit(mcp_server, temp_fs, mock_context):
    """Test multi_edit_content aborts all if one file's edit fails."""
    tool = await mcp_server.get_tool("multi_edit_content")
    with pytest.raises(ValueError, match="old_string not found"):
        await tool.run({
            "edit_operations": [
                FileEditOperation(
                    file_path="README.md",
                    sha=_sha("# Root README"),
                    edits=[EditOperation(old_string="Root", new_string="Changed")],
                ),
                FileEditOperation(
                    file_path="data.json",
                    sha=_sha('{"key": "value"}'),
                    edits=[EditOperation(old_string="NONEXISTENT", new_string="x")],
                ),
            ],
        })
    # Neither file should have been modified
    assert temp_fs.read_file("README.md") == "# Root README"
    assert temp_fs.read_file("data.json") == '{"key": "value"}'


async def test_multi_edit_content_duplicate_paths(mcp_server, temp_fs, mock_context):
    """Test multi_edit_content rejects duplicate file paths."""
    tool = await mcp_server.get_tool("multi_edit_content")
    with pytest.raises(ValueError, match="Duplicate"):
        await tool.run({
            "edit_operations": [
                FileEditOperation(
                    file_path="README.md",
                    sha=_sha("# Root README"),
                    edits=[EditOperation(old_string="Root", new_string="A")],
                ),
                FileEditOperation(
                    file_path="README.md",
                    sha=_sha("# Root README"),
                    edits=[EditOperation(old_string="Root", new_string="B")],
                ),
            ],
        })


async def test_multi_edit_content_returns_per_file_results(mcp_server, temp_fs, mock_context):
    """Test multi_edit_content returns correct per-file result structure."""
    tool = await mcp_server.get_tool("multi_edit_content")
    result = await tool.run({
        "edit_operations": [
            FileEditOperation(
                file_path="README.md",
                sha=_sha("# Root README"),
                edits=[EditOperation(old_string="Root", new_string="Result")],
            ),
            FileEditOperation(
                file_path="data.json",
                sha=_sha('{"key": "value"}'),
                edits=[EditOperation(old_string="value", new_string="done")],
            ),
        ],
    })
    text = str(result.content)
    assert "README.md" in text
    assert "data.json" in text
    assert _sha("# Result README") in text
    assert _sha('{"key": "done"}') in text


# --- Read-only mode tests ---

WRITE_TOOL_NAMES = {
    "create_content",
    "replace_content",
    "edit_content",
    "multi_edit_content",
    "delete_content",
    "move_content",
}
# search_content is omitted here because it is only registered when a
# search_engine is passed to create_mcp_server(); it is not a write tool.
READ_TOOL_NAMES = {"read_content", "read_content_batch", "list_content"}


async def test_read_only_mode_omits_write_tools(temp_fs):
    """Test that write tools are not registered when READ_ONLY=True."""
    with patch("stash_mcp.mcp_server.Config.READ_ONLY", True):
        mcp = create_mcp_server(temp_fs)
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        for name in WRITE_TOOL_NAMES:
            assert name not in tool_names, f"Write tool '{name}' should not be in read-only mode"
        for name in READ_TOOL_NAMES:
            assert name in tool_names, f"Read tool '{name}' should be registered in read-only mode"


async def test_default_mode_includes_all_tools(temp_fs):
    """Test that all tools are registered when READ_ONLY=False (default)."""
    with patch("stash_mcp.mcp_server.Config.READ_ONLY", False):
        mcp = create_mcp_server(temp_fs)
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        for name in WRITE_TOOL_NAMES | READ_TOOL_NAMES:
            assert name in tool_names, f"Tool '{name}' should be registered in default mode"


# --- Server name config tests ---


def test_server_name_from_env():
    """Test that STASH_SERVER_NAME env var is reflected in Config.SERVER_NAME."""
    import importlib

    import stash_mcp.config as config_module

    with patch.dict("os.environ", {"STASH_SERVER_NAME": "my-custom-server"}):
        importlib.reload(config_module)
        assert config_module.Config.SERVER_NAME == "my-custom-server"
    importlib.reload(config_module)


def test_server_name_default():
    """Test that SERVER_NAME defaults to 'stash-mcp' when env var is not set."""
    import importlib
    import os

    import stash_mcp.config as config_module

    env = {k: v for k, v in os.environ.items() if k != "STASH_SERVER_NAME"}
    with patch.dict("os.environ", env, clear=True):
        importlib.reload(config_module)
        assert config_module.Config.SERVER_NAME == "stash-mcp"
    importlib.reload(config_module)


async def test_server_name_used_in_mcp_server(temp_fs):
    """Test that the MCP server uses Config.SERVER_NAME."""
    with patch("stash_mcp.mcp_server.Config.SERVER_NAME", "test-server"):
        mcp = create_mcp_server(temp_fs)
        assert mcp.name == "test-server"
