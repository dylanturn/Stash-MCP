"""Tests for MCP server implementation."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stash_mcp.filesystem import FileSystem
from stash_mcp.mcp_server import _get_mime_type, create_mcp_server


@pytest.fixture
def temp_fs():
    """Create a temporary filesystem for testing."""
    with TemporaryDirectory() as tmpdir:
        fs = FileSystem(Path(tmpdir))
        yield fs


@pytest.fixture
def mcp_server(temp_fs):
    """Create a FastMCP server with temporary filesystem."""
    temp_fs.write_file("README.md", "# Test Content")
    temp_fs.write_file("docs/README.md", "# README\nSome docs")
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
    # Only README.md files should be registered as explicit resources
    assert "stash://README.md" in uris
    assert "stash://docs/README.md" in uris
    # Non-README files should NOT be registered as explicit resources
    assert "stash://data.json" not in uris


async def test_resource_mime_types(mcp_server):
    """Test that resources have correct mime types."""
    resources = await mcp_server.get_resources()
    md_resource = resources.get("stash://README.md")
    assert md_resource is not None
    assert md_resource.mime_type == "text/markdown"


async def test_resource_templates(mcp_server):
    """Test that resource template is registered."""
    templates = await mcp_server.get_resource_templates()
    assert "stash://{path}" in templates


async def test_read_resource_via_template(mcp_server):
    """Test reading a resource through the resource template."""
    # README.md is registered as explicit resource, can be read
    resource = await mcp_server.get_resource("stash://README.md")
    content = resource.fn()
    assert content == "# Test Content"


# --- Tool tests ---


async def test_list_tools(mcp_server):
    """Test listing tools returns all expected tools."""
    tools = await mcp_server.get_tools()
    tool_names = list(tools.keys())
    assert "create_content" in tool_names
    assert "update_content" in tool_names
    assert "delete_content" in tool_names
    assert "list_content" in tool_names
    assert "move_content" in tool_names


async def test_create_content_tool(temp_fs, mock_context):
    """Test create_content tool creates a file."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    result = await tool.run({"path": "new/README.md", "content": "# New File"})
    assert "Created: new/README.md" in str(result.content)
    assert temp_fs.file_exists("new/README.md")
    assert temp_fs.read_file("new/README.md") == "# New File"


async def test_create_content_tool_existing_file(mcp_server, temp_fs, mock_context):
    """Test create_content tool errors on existing file."""
    tool = await mcp_server.get_tool("create_content")
    with pytest.raises(ValueError, match="already exists"):
        await tool.run({"path": "README.md", "content": "overwrite"})


async def test_update_content_tool(mcp_server, temp_fs, mock_context):
    """Test update_content tool updates a file."""
    tool = await mcp_server.get_tool("update_content")
    result = await tool.run({"path": "README.md", "content": "# Updated"})
    assert "Updated: README.md" in str(result.content)
    assert temp_fs.read_file("README.md") == "# Updated"


async def test_delete_content_tool(mcp_server, temp_fs, mock_context):
    """Test delete_content tool deletes a file."""
    tool = await mcp_server.get_tool("delete_content")
    result = await tool.run({"path": "README.md"})
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
    result = await tool.run({"source_path": "README.md", "dest_path": "moved/README.md"})
    assert "Moved: README.md -> moved/README.md" in str(result.content)
    assert not temp_fs.file_exists("README.md")
    assert temp_fs.file_exists("moved/README.md")
    assert temp_fs.read_file("moved/README.md") == "# Test Content"


# --- Notification tests ---


async def test_create_registers_resource(temp_fs, mock_context):
    """Test that create_content registers new README.md resources."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    await tool.run({"path": "project/README.md", "content": "# New"})
    resources = await mcp.get_resources()
    # README.md should be registered as an explicit resource
    assert "stash://project/README.md" in resources


async def test_create_sends_list_changed(temp_fs, mock_context):
    """Test that create_content sends resource_list_changed notification for README.md."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    await tool.run({"path": "another/README.md", "content": "# New"})
    mock_context.send_resource_list_changed.assert_awaited_once()


async def test_update_existing_sends_resource_updated(mcp_server, mock_context):
    """Test that updating an existing README.md file sends resource_updated notification."""
    tool = await mcp_server.get_tool("update_content")
    await tool.run({"path": "README.md", "content": "# Changed"})
    mock_context.session.send_resource_updated.assert_awaited_once()
    call_kwargs = mock_context.session.send_resource_updated.call_args
    assert str(call_kwargs.kwargs["uri"]) == "stash://README.md"


async def test_update_new_file_registers_resource(temp_fs, mock_context):
    """Test that updating a non-existent README.md file registers it as a new resource."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("update_content")
    await tool.run({"path": "brand_new/README.md", "content": "# Brand New"})
    resources = await mcp.get_resources()
    # README.md should be registered as an explicit resource
    assert "stash://brand_new/README.md" in resources
    mock_context.session.send_resource_updated.assert_not_awaited()


async def test_update_new_file_sends_list_changed(temp_fs, mock_context):
    """Test that updating a non-existent README.md file sends resource_list_changed notification."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("update_content")
    await tool.run({"path": "brand_new/README.md", "content": "# Brand New"})
    mock_context.send_resource_list_changed.assert_awaited_once()


async def test_delete_unregisters_resource(mcp_server, temp_fs, mock_context):
    """Test that delete_content removes the README.md resource from registry."""
    resources_before = await mcp_server.get_resources()
    assert "stash://README.md" in resources_before

    tool = await mcp_server.get_tool("delete_content")
    await tool.run({"path": "README.md"})

    resources_after = await mcp_server.get_resources()
    assert "stash://README.md" not in resources_after


async def test_delete_sends_list_changed(mcp_server, temp_fs, mock_context):
    """Test that delete_content sends resource_list_changed notification for README.md."""
    tool = await mcp_server.get_tool("delete_content")
    await tool.run({"path": "README.md"})
    mock_context.send_resource_list_changed.assert_awaited_once()


async def test_move_updates_resources(mcp_server, temp_fs, mock_context):
    """Test that move_content removes old README.md resource and adds new one."""
    tool = await mcp_server.get_tool("move_content")
    await tool.run({"source_path": "README.md", "dest_path": "moved/README.md"})

    resources = await mcp_server.get_resources()
    assert "stash://README.md" not in resources
    assert "stash://moved/README.md" in resources


async def test_move_sends_list_changed(mcp_server, temp_fs, mock_context):
    """Test that move_content sends resource_list_changed notification for README.md."""
    tool = await mcp_server.get_tool("move_content")
    await tool.run({"source_path": "README.md", "dest_path": "moved/README.md"})
    mock_context.send_resource_list_changed.assert_awaited_once()


async def test_resources_filtered_by_include_patterns(temp_fs):
    """Test that when patterns are set, only matching README.md files are
    registered as MCP resources."""
    # Write files of different types
    temp_fs.write_file("docs/README.md", "# Docs Guide")
    temp_fs.write_file("docs/other.md", "# Other Doc")
    temp_fs.write_file("api/README.md", "# API")
    temp_fs.write_file("notes/README.md", "# Notes")
    temp_fs.write_file("data.json", '{"key": "value"}')

    # Create a new filesystem with patterns, using the same content directory
    # Pattern matches docs directory, but only README.md should be registered
    filtered_fs = FileSystem(temp_fs.content_dir, include_patterns=["docs/**/*"])
    mcp = create_mcp_server(filtered_fs)

    resources = await mcp.get_resources()
    uris = list(resources.keys())

    # Only docs/README.md should be registered (matches pattern AND is README.md)
    assert "stash://docs/README.md" in uris
    # These should NOT be registered
    assert "stash://docs/other.md" not in uris  # matches pattern but not README.md
    assert "stash://api/README.md" not in uris  # is README.md but outside pattern
    assert "stash://notes/README.md" not in uris  # is README.md but outside pattern
    assert "stash://data.json" not in uris  # outside pattern and not README.md


async def test_tools_emit_events(mcp_server, temp_fs, mock_context):
    """Test that MCP tools emit events via the event bus."""
    with patch("stash_mcp.mcp_server.emit") as mock_emit:
        # Test create
        tool = await mcp_server.get_tool("create_content")
        await tool.run({"path": "events/README.md", "content": "event test"})
        mock_emit.assert_called_with("content_created", "events/README.md")

        mock_emit.reset_mock()

        # Test update (existing file)
        tool = await mcp_server.get_tool("update_content")
        await tool.run({"path": "events/README.md", "content": "updated"})
        mock_emit.assert_called_with("content_updated", "events/README.md")

        mock_emit.reset_mock()

        # Test move
        tool = await mcp_server.get_tool("move_content")
        await tool.run({
            "source_path": "events/README.md",
            "dest_path": "events2/README.md"
        })
        mock_emit.assert_called_with(
            "content_moved",
            "events2/README.md",
            source_path="events/README.md"
        )

        mock_emit.reset_mock()

        # Test delete
        tool = await mcp_server.get_tool("delete_content")
        await tool.run({"path": "events2/README.md"})
        mock_emit.assert_called_with("content_deleted", "events2/README.md")
