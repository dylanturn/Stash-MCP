"""``CompositeFileSystem`` — routes file ops to multiple underlying FileSystems.

Implements the same interface as :class:`stash_mcp.filesystem.FileSystem`
so MCP tool handlers and REST callers don't need to know the request is
running against a multi-store composite (spec 04). Each underlying mount
binds a ``(FileSystem, subpath, virtual_prefix)`` triple; an agent-
facing path is matched against the longest-prefix mount and forwarded
to that mount's filesystem with the prefix stripped and the mount's
subpath prepended.

Containment is delegated to the underlying ``FileSystem._resolve_path``
— the composite is a router, not a sandbox replacement.
"""

from __future__ import annotations

import logging
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..filesystem import (
    FileNotFoundError as ContentNotFoundError,
)
from ..filesystem import (
    InvalidPathError,
)

logger = logging.getLogger(__name__)


@dataclass
class CompositeMount:
    """One mount entry for the composite.

    Attributes:
        fs: The underlying :class:`FileSystem` (or
            :class:`TransactionManager`) the mount delegates to.
        subpath: A normalized relative path under the underlying FS
            (empty for the FS root). The composite prepends this to
            every agent-facing path that resolves to this mount.
        virtual_prefix: The agent-facing path prefix (normalized,
            without leading/trailing slashes; empty for a root mount).
    """

    fs: Any  # FileSystem | TransactionManager — duck-typed FS interface
    subpath: str
    virtual_prefix: str


class CompositeFileSystem:
    """Routes file ops by virtual_prefix to the right underlying FS."""

    def __init__(self, mounts: list[CompositeMount]):
        if not mounts:
            raise ValueError("CompositeFileSystem requires at least one mount")
        # Sort longest-prefix first so a mount at "docs/team-a" matches
        # before a mount at "docs" for paths under "docs/team-a/".
        self._mounts = sorted(mounts, key=lambda m: -len(m.virtual_prefix))

    # --- routing -----------------------------------------------------

    def _norm(self, agent_path: str) -> str:
        return (agent_path or "").lstrip("/")

    def _resolve(self, agent_path: str) -> tuple[Any, str, CompositeMount]:
        """Map an agent-facing path to (fs, fs_relative_path, mount).

        Raises :class:`InvalidPathError` if the agent_path doesn't fall
        inside any mount.
        """
        normalized = self._norm(agent_path)
        for mount in self._mounts:
            prefix = mount.virtual_prefix
            if prefix == "":
                fs_rel = (
                    posixpath.join(mount.subpath, normalized)
                    if normalized
                    else mount.subpath
                )
                return mount.fs, fs_rel, mount
            if normalized == prefix:
                return mount.fs, mount.subpath, mount
            if normalized.startswith(prefix + "/"):
                tail = normalized[len(prefix) + 1 :]
                fs_rel = posixpath.join(mount.subpath, tail) if mount.subpath else tail
                return mount.fs, fs_rel, mount
        raise InvalidPathError(
            f"path {agent_path!r} is not inside any mount"
        )

    # --- read APIs ---------------------------------------------------

    def read_file(self, relative_path: str) -> str:
        fs, fs_rel, _m = self._resolve(relative_path)
        return fs.read_file(fs_rel)

    def file_exists(self, relative_path: str) -> bool:
        try:
            fs, fs_rel, _m = self._resolve(relative_path)
        except InvalidPathError:
            return False
        return fs.file_exists(fs_rel)

    def content_hash(self, relative_path: str) -> str:
        fs, fs_rel, _m = self._resolve(relative_path)
        return fs.content_hash(fs_rel)

    def list_files(
        self, relative_path: str = ""
    ) -> list[tuple[str, bool]]:
        """Listing semantics:

        - ``list_files("")`` on the composite root returns the union of
          the underlying root mount's entries (if any) with synthetic
          directory entries for each top-level virtual_prefix.
        - ``list_files("<prefix>")`` walks into that prefix's mount.
        - ``list_files("<prefix>/sub")`` likewise; resolution uses the
          longest-prefix match.
        """
        normalized = self._norm(relative_path)
        if normalized == "":
            # Composite-root listing: collect entries from a root mount
            # (virtual_prefix == "") if present, plus synthesise top-
            # level virtual_prefix directories.
            entries: dict[str, bool] = {}
            for mount in self._mounts:
                if mount.virtual_prefix == "":
                    try:
                        for name, is_dir in mount.fs.list_files(mount.subpath):
                            entries[name] = is_dir
                    except (ContentNotFoundError, InvalidPathError):
                        pass
                else:
                    top = mount.virtual_prefix.split("/", 1)[0]
                    entries[top] = True
            return sorted(entries.items())

        # Direct prefix match for a virtual-prefix dir handle the
        # walk-into case where the agent path equals a prefix.
        for mount in self._mounts:
            if mount.virtual_prefix and mount.virtual_prefix == normalized:
                return mount.fs.list_files(mount.subpath)
        fs, fs_rel, _m = self._resolve(relative_path)
        return fs.list_files(fs_rel)

    def list_all_files(self, relative_path: str = "") -> list[str]:
        normalized = self._norm(relative_path)
        if normalized == "":
            # Union of every mount's files, re-prefixed with the
            # virtual_prefix as seen by the agent.
            out: list[str] = []
            for mount in self._mounts:
                try:
                    sub_files = mount.fs.list_all_files(mount.subpath)
                except (ContentNotFoundError, InvalidPathError):
                    continue
                strip_prefix = (
                    mount.subpath + "/" if mount.subpath else ""
                )
                for f in sub_files:
                    rel = (
                        f[len(strip_prefix) :]
                        if strip_prefix and f.startswith(strip_prefix)
                        else f
                    )
                    if mount.virtual_prefix:
                        out.append(
                            posixpath.join(mount.virtual_prefix, rel)
                            if rel
                            else mount.virtual_prefix
                        )
                    else:
                        out.append(rel)
            return sorted(set(out))
        fs, fs_rel, mount = self._resolve(relative_path)
        sub_files = fs.list_all_files(fs_rel)
        # Re-prefix with the virtual prefix the agent asked for.
        strip_prefix = mount.subpath + "/" if mount.subpath else ""
        out = []
        for f in sub_files:
            rel = (
                f[len(strip_prefix) :]
                if strip_prefix and f.startswith(strip_prefix)
                else f
            )
            if mount.virtual_prefix:
                out.append(
                    posixpath.join(mount.virtual_prefix, rel) if rel else mount.virtual_prefix
                )
            else:
                out.append(rel)
        return out

    # --- write APIs --------------------------------------------------

    def write_file(self, relative_path: str, content: str) -> None:
        fs, fs_rel, _m = self._resolve(relative_path)
        fs.write_file(fs_rel, content)

    def delete_file(self, relative_path: str) -> None:
        fs, fs_rel, _m = self._resolve(relative_path)
        fs.delete_file(fs_rel)

    def move_file(self, source_path: str, dest_path: str) -> None:
        src_fs, src_rel, src_mount = self._resolve(source_path)
        dst_fs, dst_rel, dst_mount = self._resolve(dest_path)
        # Compare mounts, not filesystems: two virtual prefixes can
        # legitimately mount the same underlying FS at different
        # subpaths, and a move between those would silently bypass the
        # cross-mount boundary if we only checked FS identity.
        if src_mount is dst_mount:
            src_fs.move_file(src_rel, dst_rel)
            return
        # Cross-mount move: read, write to the destination, then delete
        # the source. Not atomic — if the write succeeds and the delete
        # fails, both copies exist; if the write fails, the source is
        # preserved. Multi-store composites already forbid git/tx tools
        # (single-mount rename detection isn't available here either),
        # so the caller knows they're trading atomicity for the move.
        content = src_fs.read_file(src_rel)
        dst_fs.write_file(dst_rel, content)
        try:
            src_fs.delete_file(src_rel)
        except Exception:
            # Best-effort cleanup of the new copy so we don't leave the
            # file duplicated. Re-raise the original delete error so
            # callers see why the move didn't complete.
            try:
                dst_fs.delete_file(dst_rel)
            except Exception:
                pass
            raise

    def move_directory(
        self, source_path: str, dest_path: str
    ) -> list[tuple[str, str]]:
        src_fs, src_rel, src_mount = self._resolve(source_path)
        dst_fs, dst_rel, dst_mount = self._resolve(dest_path)
        if src_mount is dst_mount:
            return src_fs.move_directory(src_rel, dst_rel)
        # Cross-mount directory move: enumerate, copy each file across,
        # then delete the originals. Same atomicity caveat as
        # ``move_file`` — and on partial failure we roll back the
        # already-written destination files to avoid duplicates.
        try:
            src_files = src_fs.list_all_files(src_rel)
        except (ContentNotFoundError, InvalidPathError) as exc:
            raise InvalidPathError(
                f"source directory not found: {source_path!r}"
            ) from exc
        if not src_files:
            return []

        src_strip = src_rel + "/" if src_rel else ""
        moves: list[tuple[str, str]] = []
        written: list[str] = []
        try:
            for src_file in src_files:
                tail = (
                    src_file[len(src_strip):]
                    if src_strip and src_file.startswith(src_strip)
                    else src_file
                )
                dst_file = posixpath.join(dst_rel, tail) if dst_rel else tail
                content = src_fs.read_file(src_file)
                dst_fs.write_file(dst_file, content)
                written.append(dst_file)
                moves.append((src_file, dst_file))
            for src_file, _ in moves:
                src_fs.delete_file(src_file)
        except Exception:
            for dst_file in written:
                try:
                    dst_fs.delete_file(dst_file)
                except Exception:
                    pass
            raise
        return moves

    def create_directory(self, relative_path: str) -> None:
        fs, fs_rel, _m = self._resolve(relative_path)
        fs.create_directory(fs_rel)

    # --- containment-check exposure ---------------------------------

    def _resolve_path(self, relative_path: str) -> Path:
        """Mirror of ``FileSystem._resolve_path`` for callers like
        :func:`move_content_batch` that pre-check a destination's
        existence on disk. Forwards to the underlying mount's resolver.
        """
        fs, fs_rel, _m = self._resolve(relative_path)
        return fs._resolve_path(fs_rel)
