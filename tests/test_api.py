"""Tests for REST API."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from stash_mcp.api import create_api
from stash_mcp.filesystem import FileSystem


@pytest.fixture
def test_client():
    """Create a test client with temporary filesystem."""
    with TemporaryDirectory() as tmpdir:
        fs = FileSystem(Path(tmpdir))
        # Add some test content
        fs.write_file("test.md", "# Test Content")
        fs.write_file("docs/readme.md", "# README")

        app = create_api(fs)
        client = TestClient(app)
        yield client


def test_root_endpoint(test_client):
    """Test root endpoint returns API info."""
    response = test_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Stash-MCP API"
    assert "endpoints" in data


def test_list_content(test_client):
    """Test listing all content."""
    response = test_client.get("/api/content")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 2
    paths = [item["path"] for item in data["items"]]
    assert "test.md" in paths
    assert "docs/readme.md" in paths


def test_read_content(test_client):
    """Test reading a specific file."""
    response = test_client.get("/api/content/test.md")
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == "test.md"
    assert data["content"] == "# Test Content"
    assert data["is_directory"] is False


def test_read_nonexistent_content(test_client):
    """Test reading a nonexistent file returns 404."""
    response = test_client.get("/api/content/nonexistent.md")
    assert response.status_code == 404


def test_create_content(test_client):
    """Test creating new content."""
    response = test_client.put(
        "/api/content/new.md",
        json={"content": "# New Content"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "saved successfully" in data["message"]

    # Verify content was created
    response = test_client.get("/api/content/new.md")
    assert response.status_code == 200
    assert response.json()["content"] == "# New Content"


def test_update_content(test_client):
    """Test updating existing content."""
    response = test_client.put(
        "/api/content/test.md",
        json={"content": "# Updated Content"}
    )
    assert response.status_code == 200

    # Verify content was updated
    response = test_client.get("/api/content/test.md")
    assert response.status_code == 200
    assert response.json()["content"] == "# Updated Content"


def test_delete_content(test_client):
    """Test deleting content."""
    response = test_client.delete("/api/content/test.md")
    assert response.status_code == 200
    data = response.json()
    assert "deleted successfully" in data["message"]

    # Verify content was deleted
    response = test_client.get("/api/content/test.md")
    assert response.status_code == 404


def test_delete_nonexistent_content(test_client):
    """Test deleting a nonexistent file returns 404."""
    response = test_client.delete("/api/content/nonexistent.md")
    assert response.status_code == 404
