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


def test_cross_mount_move_file_rolls_back_on_delete_failure(
    two_stores, monkeypatch
):
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

    # Source preserved (delete failed), destination cleaned up.
    assert docs_fs.read_file("engineering/intro.md") == "engineering content"
    assert not ops_fs.file_exists("runbooks/intro.md")


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
