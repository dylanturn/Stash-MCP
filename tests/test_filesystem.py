"""Tests for filesystem module."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from stash_mcp.filesystem import (
    FileNotFoundError,
    FileSystem,
    InvalidPathError,
)


@pytest.fixture
def temp_fs():
    """Create a temporary filesystem for testing."""
    with TemporaryDirectory() as tmpdir:
        fs = FileSystem(Path(tmpdir))
        yield fs


def test_write_and_read_file(temp_fs):
    """Test writing and reading a file."""
    temp_fs.write_file("test.txt", "Hello, World!")
    content = temp_fs.read_file("test.txt")
    assert content == "Hello, World!"


def test_write_file_in_subdirectory(temp_fs):
    """Test writing a file in a subdirectory."""
    temp_fs.write_file("subdir/test.txt", "Content")
    content = temp_fs.read_file("subdir/test.txt")
    assert content == "Content"


def test_list_files(temp_fs):
    """Test listing files in a directory."""
    temp_fs.write_file("file1.txt", "Content 1")
    temp_fs.write_file("file2.txt", "Content 2")
    temp_fs.create_directory("subdir")

    items = temp_fs.list_files("")
    assert len(items) == 3
    names = [name for name, _ in items]
    assert "file1.txt" in names
    assert "file2.txt" in names
    assert "subdir" in names


def test_list_all_files(temp_fs):
    """Test listing all files recursively."""
    temp_fs.write_file("file1.txt", "Content 1")
    temp_fs.write_file("subdir/file2.txt", "Content 2")
    temp_fs.write_file("subdir/nested/file3.txt", "Content 3")

    files = temp_fs.list_all_files()
    assert len(files) == 3
    assert "file1.txt" in files
    assert "subdir/file2.txt" in files
    assert "subdir/nested/file3.txt" in files


def test_delete_file(temp_fs):
    """Test deleting a file."""
    temp_fs.write_file("test.txt", "Content")
    assert temp_fs.file_exists("test.txt")

    temp_fs.delete_file("test.txt")
    assert not temp_fs.file_exists("test.txt")


def test_file_exists(temp_fs):
    """Test checking if a file exists."""
    assert not temp_fs.file_exists("nonexistent.txt")

    temp_fs.write_file("test.txt", "Content")
    assert temp_fs.file_exists("test.txt")


def test_read_nonexistent_file(temp_fs):
    """Test reading a nonexistent file raises error."""
    with pytest.raises(FileNotFoundError):
        temp_fs.read_file("nonexistent.txt")


def test_delete_nonexistent_file(temp_fs):
    """Test deleting a nonexistent file raises error."""
    with pytest.raises(FileNotFoundError):
        temp_fs.delete_file("nonexistent.txt")


def test_invalid_path_outside_content_dir(temp_fs):
    """Test that paths outside content_dir are rejected."""
    with pytest.raises(InvalidPathError):
        temp_fs.write_file("../../../etc/passwd", "Malicious content")

    with pytest.raises(InvalidPathError):
        temp_fs.read_file("../../../etc/passwd")


def test_create_directory(temp_fs):
    """Test creating a directory."""
    temp_fs.create_directory("subdir/nested")

    # Verify we can write to the directory
    temp_fs.write_file("subdir/nested/test.txt", "Content")
    assert temp_fs.file_exists("subdir/nested/test.txt")
