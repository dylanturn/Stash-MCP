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


@pytest.fixture
def populated_dir(tmp_path):
    """Create a temp directory with a known file structure for pattern tests."""
    files = {
        "docs/guide.md": "# Guide",
        "docs/api.md": "# API",
        "docs/deep/nested.md": "# Nested",
        "notes/todo.txt": "todo",
        "notes/ideas.md": "ideas",
        "readme.md": "# Root readme",
        "data.json": '{"key": "value"}',
    }
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


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


def test_write_file_creates_deeply_nested_directories(temp_fs):
    """Test writing a file creates all missing parent directories."""
    temp_fs.write_file("a/b/c/d/deep.txt", "Deep content")
    assert temp_fs.file_exists("a/b/c/d/deep.txt")
    assert temp_fs.read_file("a/b/c/d/deep.txt") == "Deep content"


def test_write_file_existing_directory_no_error(temp_fs):
    """Test writing to an existing directory does not raise an error."""
    temp_fs.write_file("existing/file1.txt", "First")
    temp_fs.write_file("existing/file2.txt", "Second")
    assert temp_fs.read_file("existing/file1.txt") == "First"
    assert temp_fs.read_file("existing/file2.txt") == "Second"


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


def test_move_file(temp_fs):
    """Test moving a file."""
    temp_fs.write_file("original.txt", "Content")
    temp_fs.move_file("original.txt", "renamed.txt")

    assert not temp_fs.file_exists("original.txt")
    assert temp_fs.file_exists("renamed.txt")
    assert temp_fs.read_file("renamed.txt") == "Content"


def test_move_file_to_subdirectory(temp_fs):
    """Test moving a file into a new subdirectory."""
    temp_fs.write_file("original.txt", "Content")
    temp_fs.move_file("original.txt", "subdir/moved.txt")

    assert not temp_fs.file_exists("original.txt")
    assert temp_fs.file_exists("subdir/moved.txt")
    assert temp_fs.read_file("subdir/moved.txt") == "Content"


def test_move_nonexistent_file(temp_fs):
    """Test moving a nonexistent file raises error."""
    with pytest.raises(FileNotFoundError):
        temp_fs.move_file("nonexistent.txt", "dest.txt")


def test_move_file_to_existing_dest(temp_fs):
    """Test moving to existing destination raises error."""
    temp_fs.write_file("source.txt", "Source")
    temp_fs.write_file("dest.txt", "Dest")

    from stash_mcp.filesystem import FileSystemError
    with pytest.raises(FileSystemError, match="already exists"):
        temp_fs.move_file("source.txt", "dest.txt")


# --- move_directory tests ---


def test_move_directory_basic(temp_fs):
    """Test moving a directory to a new location."""
    temp_fs.write_file("src/file1.txt", "File 1")
    temp_fs.write_file("src/file2.txt", "File 2")
    moved = temp_fs.move_directory("src", "dst")

    assert not (temp_fs.content_dir / "src").exists()
    assert temp_fs.file_exists("dst/file1.txt")
    assert temp_fs.file_exists("dst/file2.txt")
    assert temp_fs.read_file("dst/file1.txt") == "File 1"
    assert len(moved) == 2
    assert ("src/file1.txt", "dst/file1.txt") in moved
    assert ("src/file2.txt", "dst/file2.txt") in moved


def test_move_directory_nested(temp_fs):
    """Test moving a directory with nested subdirectories."""
    temp_fs.write_file("src/a.txt", "A")
    temp_fs.write_file("src/sub/b.txt", "B")
    temp_fs.write_file("src/sub/deep/c.txt", "C")
    moved = temp_fs.move_directory("src", "dst")

    assert temp_fs.file_exists("dst/a.txt")
    assert temp_fs.file_exists("dst/sub/b.txt")
    assert temp_fs.file_exists("dst/sub/deep/c.txt")
    assert len(moved) == 3


def test_move_directory_nonexistent_source(temp_fs):
    """Test moving a nonexistent directory raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        temp_fs.move_directory("nonexistent", "dst")


def test_move_directory_source_is_file(temp_fs):
    """Test that moving a file path as directory raises InvalidPathError."""
    temp_fs.write_file("file.txt", "content")
    with pytest.raises(InvalidPathError):
        temp_fs.move_directory("file.txt", "dst")


def test_move_directory_dest_already_exists(temp_fs):
    """Test that moving to an existing destination raises FileSystemError."""
    from stash_mcp.filesystem import FileSystemError
    temp_fs.write_file("src/file.txt", "content")
    temp_fs.write_file("dst/other.txt", "other")
    with pytest.raises(FileSystemError, match="already exists"):
        temp_fs.move_directory("src", "dst")


def test_move_directory_into_itself(temp_fs):
    """Test that moving a directory into a subdirectory of itself raises InvalidPathError."""
    temp_fs.write_file("src/file.txt", "content")
    with pytest.raises(InvalidPathError, match="subdirectory of itself"):
        temp_fs.move_directory("src", "src/archive/src")


def test_move_directory_returns_moved_pairs(temp_fs):
    """Test that move_directory returns correct (old_path, new_path) pairs."""
    temp_fs.write_file("docs/README.md", "# Docs")
    temp_fs.write_file("docs/guide.md", "# Guide")
    moved = temp_fs.move_directory("docs", "archive/docs")

    assert ("docs/README.md", "archive/docs/README.md") in moved
    assert ("docs/guide.md", "archive/docs/guide.md") in moved


# --- Include patterns tests ---


def test_list_all_files_with_include_patterns(populated_dir):
    """Test that only files matching patterns are returned."""
    fs = FileSystem(populated_dir, include_patterns=["docs/**/*.md"])
    files = fs.list_all_files()
    assert "docs/guide.md" in files
    assert "docs/api.md" in files
    assert "docs/deep/nested.md" in files
    assert "notes/todo.txt" not in files
    assert "readme.md" not in files
    assert "data.json" not in files


def test_list_all_files_with_multiple_patterns(populated_dir):
    """Test that multiple patterns are unioned."""
    fs = FileSystem(populated_dir, include_patterns=["docs/**/*.md", "*.json"])
    files = fs.list_all_files()
    assert "docs/guide.md" in files
    assert "docs/api.md" in files
    assert "data.json" in files
    assert "notes/todo.txt" not in files
    assert "readme.md" not in files


def test_list_all_files_with_glob_star_star(populated_dir):
    """Test ** patterns work across directories."""
    fs = FileSystem(populated_dir, include_patterns=["**/*.md"])
    files = fs.list_all_files()
    assert "docs/guide.md" in files
    assert "docs/api.md" in files
    assert "docs/deep/nested.md" in files
    assert "notes/ideas.md" in files
    assert "readme.md" in files
    assert "notes/todo.txt" not in files
    assert "data.json" not in files


def test_list_files_with_include_patterns(populated_dir):
    """Test directories shown only when they contain matches."""
    fs = FileSystem(populated_dir, include_patterns=["docs/**/*.md"])
    items = fs.list_files("")
    names = [name for name, _ in items]
    assert "docs" in names
    assert "notes" not in names
    assert "readme.md" not in names
    assert "data.json" not in names


def test_list_files_with_patterns_hides_non_matching(populated_dir):
    """Test non-matching files and empty dirs hidden."""
    fs = FileSystem(populated_dir, include_patterns=["notes/*.txt"])
    items = fs.list_files("")
    names = [name for name, _ in items]
    assert "notes" in names
    assert "docs" not in names
    assert "readme.md" not in names

    # Inside notes, only .txt files are visible
    items = fs.list_files("notes")
    names = [name for name, _ in items]
    assert "todo.txt" in names
    assert "ideas.md" not in names


def test_include_patterns_trailing_slash_normalization():
    """Test that trailing '/' is treated as '/**'."""
    from stash_mcp.config import _parse_content_paths

    result = _parse_content_paths("docs/")
    assert result == ["docs/**"]

    result = _parse_content_paths("docs/, notes/")
    assert result == ["docs/**", "notes/**"]


def test_parse_content_paths_none_and_empty():
    """Test _parse_content_paths returns None for None/empty input."""
    from stash_mcp.config import _parse_content_paths

    assert _parse_content_paths(None) is None
    assert _parse_content_paths("") is None
    assert _parse_content_paths("  , , ") is None


def test_no_patterns_returns_all(populated_dir):
    """Test that None patterns preserves existing behavior."""
    fs = FileSystem(populated_dir, include_patterns=None)
    files = fs.list_all_files()
    assert len(files) == 7
    assert "docs/guide.md" in files
    assert "notes/todo.txt" in files
    assert "readme.md" in files
    assert "data.json" in files


def test_matches_patterns_helper(populated_dir):
    """Test the _matches_patterns method directly."""
    fs = FileSystem(populated_dir, include_patterns=["docs/**/*.md", "*.json"])
    assert fs._matches_patterns("docs/guide.md") is True
    assert fs._matches_patterns("docs/deep/nested.md") is True
    assert fs._matches_patterns("data.json") is True
    assert fs._matches_patterns("notes/todo.txt") is False
    assert fs._matches_patterns("readme.md") is False

    # No patterns = everything matches
    fs_all = FileSystem(populated_dir)
    assert fs_all._matches_patterns("anything.xyz") is True


def test_list_all_files_with_patterns_and_subpath(populated_dir):
    """Test list_all_files with patterns filtered to a subdirectory."""
    fs = FileSystem(populated_dir, include_patterns=["docs/**/*.md", "notes/*.txt"])
    files = fs.list_all_files("docs")
    assert "docs/guide.md" in files
    assert "docs/api.md" in files
    assert "docs/deep/nested.md" in files
    assert all(f.startswith("docs/") for f in files)
