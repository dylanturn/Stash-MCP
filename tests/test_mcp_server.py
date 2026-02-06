"""Tests for MCP server implementation."""

from pathlib import Path
from tempfile import TemporaryDirectory

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
    temp_fs.write_file("test.md", "# Test Content")
    temp_fs.write_file("docs/readme.md", "# README\nSome docs")
    temp_fs.write_file("data.json", '{"key": "value"}')
    return create_mcp_server(temp_fs)


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
    """Test listing resources returns all files."""
    resources = await mcp_server.get_resources()
    uris = list(resources.keys())
    assert "stash://test.md" in uris
    assert "stash://docs/readme.md" in uris
    assert "stash://data.json" in uris


async def test_resource_mime_types(mcp_server):
    """Test that resources have correct mime types."""
    resources = await mcp_server.get_resources()
    md_resource = resources.get("stash://test.md")
    assert md_resource is not None
    assert md_resource.mime_type == "text/markdown"

    json_resource = resources.get("stash://data.json")
    assert json_resource is not None
    assert json_resource.mime_type == "application/json"


async def test_resource_templates(mcp_server):
    """Test that resource template is registered."""
    templates = await mcp_server.get_resource_templates()
    assert "stash://{path}" in templates


async def test_read_resource_via_template(mcp_server):
    """Test reading a resource through the resource template."""
    resource = await mcp_server.get_resource("stash://test.md")
    # The resource object's fn reads the content
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


async def test_create_content_tool(temp_fs):
    """Test create_content tool creates a file."""
    mcp = create_mcp_server(temp_fs)
    tool = await mcp.get_tool("create_content")
    result = await tool.run({"path": "new.md", "content": "# New File"})
    assert "Created: new.md" in str(result.content)
    assert temp_fs.file_exists("new.md")
    assert temp_fs.read_file("new.md") == "# New File"


async def test_create_content_tool_existing_file(mcp_server, temp_fs):
    """Test create_content tool errors on existing file."""
    tool = await mcp_server.get_tool("create_content")
    with pytest.raises(ValueError, match="already exists"):
        await tool.run({"path": "test.md", "content": "overwrite"})


async def test_update_content_tool(mcp_server, temp_fs):
    """Test update_content tool updates a file."""
    tool = await mcp_server.get_tool("update_content")
    result = await tool.run({"path": "test.md", "content": "# Updated"})
    assert "Updated: test.md" in str(result.content)
    assert temp_fs.read_file("test.md") == "# Updated"


async def test_delete_content_tool(mcp_server, temp_fs):
    """Test delete_content tool deletes a file."""
    tool = await mcp_server.get_tool("delete_content")
    result = await tool.run({"path": "test.md"})
    assert "Deleted: test.md" in str(result.content)
    assert not temp_fs.file_exists("test.md")


async def test_list_content_tool_recursive(mcp_server):
    """Test list_content tool with recursive option."""
    tool = await mcp_server.get_tool("list_content")
    result = await tool.run({"recursive": True})
    text = str(result.content)
    assert "test.md" in text
    assert "docs/readme.md" in text
    assert "data.json" in text


async def test_list_content_tool_non_recursive(mcp_server):
    """Test list_content tool without recursive option."""
    tool = await mcp_server.get_tool("list_content")
    result = await tool.run({"path": "", "recursive": False})
    text = str(result.content)
    assert "test.md" in text
    assert "docs" in text


async def test_move_content_tool(mcp_server, temp_fs):
    """Test move_content tool moves a file."""
    tool = await mcp_server.get_tool("move_content")
    result = await tool.run({"source_path": "test.md", "dest_path": "moved.md"})
    assert "Moved: test.md -> moved.md" in str(result.content)
    assert not temp_fs.file_exists("test.md")
    assert temp_fs.file_exists("moved.md")
    assert temp_fs.read_file("moved.md") == "# Test Content"
