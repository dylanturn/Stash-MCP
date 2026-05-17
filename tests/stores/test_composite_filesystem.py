"""Tests for :class:`CompositeFileSystem` (spec 04)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stash_mcp.filesystem import FileSystem, InvalidPathError
from stash_mcp.stores.composite_filesystem import (
    CompositeFileSystem,
    CompositeMount,
)


@pytest.fixture
def two_stores(tmp_path: Path):
    docs_root = tmp_path / "docs"
    ops_root = tmp_path / "ops"
    docs_root.mkdir()
    ops_root.mkdir()

    docs_fs = FileSystem(docs_root)
    ops_fs = FileSystem(ops_root)
    docs_fs.write_file("engineering/intro.md", "engineering content")
    docs_fs.write_file("engineering/team-a/spec.md", "team-a spec")
    docs_fs.write_file("public/readme.md", "public content")
    ops_fs.write_file("runbooks/oncall.md", "oncall runbook")
    return docs_fs, ops_fs


def test_simple_root_mount_reads_underlying_subpath(two_stores):
    docs_fs, _ = two_stores
    composite = CompositeFileSystem(
        [CompositeMount(fs=docs_fs, subpath="engineering", virtual_prefix="")]
    )
    assert composite.read_file("intro.md") == "engineering content"
    assert composite.read_file("team-a/spec.md") == "team-a spec"
    assert composite.file_exists("intro.md")
    assert not composite.file_exists("nope.md")


def test_virtual_prefix_routes_to_correct_mount(two_stores):
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )
    assert composite.read_file("engineering/intro.md") == "engineering content"
    assert composite.read_file("ops/oncall.md") == "oncall runbook"


def test_unmounted_path_raises(two_stores):
    docs_fs, _ = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
        ]
    )
    with pytest.raises(InvalidPathError):
        composite.read_file("ops/x.md")  # no ops mount


def test_longest_prefix_wins(two_stores):
    """A mount at "docs/team-a" should beat a root mount when both could
    match."""
    docs_fs, ops_fs = two_stores
    # Build two mounts: one is the root catch-all (whole docs FS), one
    # is a more specific prefix that maps to a different FS.
    composite = CompositeFileSystem(
        [
            CompositeMount(fs=docs_fs, subpath="", virtual_prefix=""),
            CompositeMount(
                fs=ops_fs,
                subpath="runbooks",
                virtual_prefix="engineering/team-a",
            ),
        ]
    )
    # /public/readme.md falls into the root mount (docs_fs).
    assert composite.read_file("public/readme.md") == "public content"
    # /engineering/team-a/oncall.md is captured by the more specific
    # mount — it routes to ops_fs's runbooks/oncall.md.
    assert (
        composite.read_file("engineering/team-a/oncall.md")
        == "oncall runbook"
    )


def test_list_dir_synthesises_virtual_prefix_dirs(two_stores):
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )
    entries = dict(composite.list_files(""))
    # Both top-level prefixes appear as directories.
    assert entries == {"engineering": True, "ops": True}


def test_list_dir_walks_into_mount(two_stores):
    docs_fs, _ = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
        ]
    )
    entries = dict(composite.list_files("engineering"))
    assert "intro.md" in entries
    assert "team-a" in entries
    assert entries["team-a"] is True


def test_list_all_files_reprefixes(two_stores):
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )
    all_files = composite.list_all_files("")
    assert "engineering/intro.md" in all_files
    assert "engineering/team-a/spec.md" in all_files
    assert "ops/oncall.md" in all_files
    # Files outside the mounts must not surface.
    assert not any("public" in f for f in all_files)


def test_containment_still_enforced(two_stores):
    docs_fs, _ = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
        ]
    )
    # The agent tries to escape the underlying content_dir with enough
    # ``..`` segments to actually leave the directory. The underlying
    # ``FileSystem._resolve_path`` containment check fires.
    with pytest.raises(InvalidPathError):
        composite.read_file("engineering/../../../../etc/passwd")


def test_write_and_delete_round_trip(two_stores):
    docs_fs, _ = two_stores
    composite = CompositeFileSystem(
        [CompositeMount(fs=docs_fs, subpath="engineering", virtual_prefix="")]
    )
    composite.write_file("new.md", "hello")
    assert docs_fs.read_file("engineering/new.md") == "hello"
    composite.delete_file("new.md")
    assert not docs_fs.file_exists("engineering/new.md")


def test_cross_mount_move_file_copies_and_deletes(two_stores):
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )
    composite.move_file("engineering/intro.md", "ops/intro.md")

    assert not docs_fs.file_exists("engineering/intro.md")
    assert ops_fs.read_file("runbooks/intro.md") == "engineering content"


def test_cross_mount_move_file_rolls_back_on_write_failure(
    two_stores, monkeypatch
):
    """Phase-1 (write) failure must leave the source intact and clean
    up the partial destination."""
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )

    def boom(_path: str, _content: str) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(ops_fs, "write_file", boom)
    with pytest.raises(OSError, match="simulated write failure"):
        composite.move_file("engineering/intro.md", "ops/intro.md")

    assert docs_fs.read_file("engineering/intro.md") == "engineering content"
    assert not ops_fs.file_exists("runbooks/intro.md")


def test_cross_mount_move_file_preserves_destination_on_delete_failure(
    two_stores, monkeypatch
):
    """Phase-2 (delete) failure must NOT roll back the destination —
    that would risk losing data if the delete had partially
    succeeded. The destination is the canonical copy going forward;
    the leftover source is the caller's problem to clean up."""
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )

    def boom(_path: str) -> None:
        raise OSError("simulated delete failure")

    monkeypatch.setattr(docs_fs, "delete_file", boom)
    with pytest.raises(OSError, match="simulated delete failure"):
        composite.move_file("engineering/intro.md", "ops/intro.md")

    # Both copies exist after the failed delete — no data loss.
    assert docs_fs.read_file("engineering/intro.md") == "engineering content"
    assert ops_fs.read_file("runbooks/intro.md") == "engineering content"


def test_cross_mount_move_file_refuses_existing_destination(two_stores):
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )
    ops_fs.write_file("runbooks/intro.md", "existing")

    from stash_mcp.filesystem import FileSystemError

    with pytest.raises(FileSystemError, match="already exists"):
        composite.move_file("engineering/intro.md", "ops/intro.md")

    # Source and (pre-existing) destination both untouched.
    assert docs_fs.read_file("engineering/intro.md") == "engineering content"
    assert ops_fs.read_file("runbooks/intro.md") == "existing"


def test_cross_mount_move_directory_copies_and_deletes(two_stores):
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )

    moves = composite.move_directory("engineering/team-a", "ops/team-a")

    assert len(moves) == 1
    assert not docs_fs.file_exists("engineering/team-a/spec.md")
    assert ops_fs.read_file("runbooks/team-a/spec.md") == "team-a spec"


def test_move_directory_returns_agent_facing_paths_same_mount(two_stores):
    """move_directory must surface paths in the namespace the agent
    used on the way in, not the underlying FS namespace. mcp_server's
    move_content_directory iterates these paths to emit events and
    fire resource notifications, so agent-facing is the right answer."""
    docs_fs, _ = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="docs"
            ),
        ]
    )
    moves = composite.move_directory("docs/team-a", "docs/team-b")
    assert moves == [("docs/team-a/spec.md", "docs/team-b/spec.md")]


def test_move_directory_returns_agent_facing_paths_cross_mount(two_stores):
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="docs"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )
    moves = composite.move_directory("docs/team-a", "ops/team-a")
    assert moves == [("docs/team-a/spec.md", "ops/team-a/spec.md")]


def test_cross_mount_move_directory_raises_on_missing_source(two_stores):
    """A typo'd source path used to silently no-op (list_all_files
    returns [] for missing paths). Now it raises so the agent learns."""
    docs_fs, ops_fs = two_stores
    composite = CompositeFileSystem(
        [
            CompositeMount(
                fs=docs_fs, subpath="engineering", virtual_prefix="engineering"
            ),
            CompositeMount(
                fs=ops_fs, subpath="runbooks", virtual_prefix="ops"
            ),
        ]
    )
    from stash_mcp.filesystem import FileNotFoundError as ContentNotFoundError

    with pytest.raises(ContentNotFoundError):
        composite.move_directory("engineering/does-not-exist", "ops/x")
