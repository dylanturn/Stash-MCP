"""Filesystem layer for content management."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FileSystemError(Exception):
    """Base exception for filesystem operations."""
    pass


class FileNotFoundError(FileSystemError):
    """File not found error."""
    pass


class InvalidPathError(FileSystemError):
    """Invalid path error."""
    pass


class FileSystem:
    """Manages filesystem operations for content storage."""

    def __init__(self, content_dir: Path):
        """Initialize filesystem layer.

        Args:
            content_dir: Root directory for content storage
        """
        self.content_dir = content_dir.resolve()
        self.content_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Filesystem initialized with content_dir: {self.content_dir}")

    def _resolve_path(self, relative_path: str) -> Path:
        """Resolve and validate a relative path.

        Args:
            relative_path: Path relative to content_dir

        Returns:
            Resolved absolute path

        Raises:
            InvalidPathError: If path is invalid or outside content_dir
        """
        # Remove leading slash if present
        if relative_path.startswith("/"):
            relative_path = relative_path[1:]

        # Resolve the full path
        full_path = (self.content_dir / relative_path).resolve()

        # Security check: ensure path is within content_dir
        try:
            full_path.relative_to(self.content_dir)
        except ValueError:
            raise InvalidPathError(f"Path '{relative_path}' is outside content directory")

        return full_path

    def list_files(self, relative_path: str = "") -> list[tuple[str, bool]]:
        """List files and directories at the given path.

        Args:
            relative_path: Path relative to content_dir

        Returns:
            List of (name, is_directory) tuples

        Raises:
            FileNotFoundError: If path doesn't exist
            InvalidPathError: If path is invalid
        """
        full_path = self._resolve_path(relative_path)

        if not full_path.exists():
            raise FileNotFoundError(f"Path '{relative_path}' not found")

        if not full_path.is_dir():
            raise InvalidPathError(f"Path '{relative_path}' is not a directory")

        items = []
        for item in sorted(full_path.iterdir()):
            # Skip hidden files
            if item.name.startswith("."):
                continue
            items.append((item.name, item.is_dir()))

        return items

    def list_all_files(self, relative_path: str = "") -> list[str]:
        """Recursively list all files under the given path.

        Args:
            relative_path: Path relative to content_dir

        Returns:
            List of relative file paths

        Raises:
            InvalidPathError: If path is invalid
        """
        full_path = self._resolve_path(relative_path)

        if not full_path.exists():
            return []

        files = []
        if full_path.is_file():
            return [relative_path]

        for item in full_path.rglob("*"):
            if item.is_file() and not any(part.startswith(".") for part in item.parts):
                rel_path = item.relative_to(self.content_dir)
                files.append(str(rel_path))

        return sorted(files)

    def read_file(self, relative_path: str) -> str:
        """Read file content.

        Args:
            relative_path: Path relative to content_dir

        Returns:
            File content as string

        Raises:
            FileNotFoundError: If file doesn't exist
            InvalidPathError: If path is invalid or not a file
        """
        full_path = self._resolve_path(relative_path)

        if not full_path.exists():
            raise FileNotFoundError(f"File '{relative_path}' not found")

        if not full_path.is_file():
            raise InvalidPathError(f"Path '{relative_path}' is not a file")

        try:
            return full_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Error reading file '{relative_path}': {e}")
            raise FileSystemError(f"Failed to read file: {e}")

    def write_file(self, relative_path: str, content: str) -> None:
        """Write content to file.

        Args:
            relative_path: Path relative to content_dir
            content: Content to write

        Raises:
            InvalidPathError: If path is invalid
        """
        full_path = self._resolve_path(relative_path)

        # Create parent directories if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            full_path.write_text(content, encoding="utf-8")
            logger.info(f"Wrote file: {relative_path}")
        except Exception as e:
            logger.error(f"Error writing file '{relative_path}': {e}")
            raise FileSystemError(f"Failed to write file: {e}")

    def delete_file(self, relative_path: str) -> None:
        """Delete a file.

        Args:
            relative_path: Path relative to content_dir

        Raises:
            FileNotFoundError: If file doesn't exist
            InvalidPathError: If path is invalid or not a file
        """
        full_path = self._resolve_path(relative_path)

        if not full_path.exists():
            raise FileNotFoundError(f"File '{relative_path}' not found")

        if not full_path.is_file():
            raise InvalidPathError(f"Path '{relative_path}' is not a file")

        try:
            full_path.unlink()
            logger.info(f"Deleted file: {relative_path}")
        except Exception as e:
            logger.error(f"Error deleting file '{relative_path}': {e}")
            raise FileSystemError(f"Failed to delete file: {e}")

    def file_exists(self, relative_path: str) -> bool:
        """Check if a file exists.

        Args:
            relative_path: Path relative to content_dir

        Returns:
            True if file exists, False otherwise
        """
        try:
            full_path = self._resolve_path(relative_path)
            return full_path.is_file()
        except InvalidPathError:
            return False

    def create_directory(self, relative_path: str) -> None:
        """Create a directory.

        Args:
            relative_path: Path relative to content_dir

        Raises:
            InvalidPathError: If path is invalid
        """
        full_path = self._resolve_path(relative_path)

        try:
            full_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {relative_path}")
        except Exception as e:
            logger.error(f"Error creating directory '{relative_path}': {e}")
            raise FileSystemError(f"Failed to create directory: {e}")
