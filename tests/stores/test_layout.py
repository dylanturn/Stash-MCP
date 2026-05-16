"""Tests for the CONTENT_DIR shape invariant in ``stash_mcp.stores.layout``."""

from __future__ import annotations

from pathlib import Path

import pytest

from stash_mcp.config import Config
from stash_mcp.stores.layout import (
    ContentLayoutError,
    store_root,
    validate_content_layout,
)


@pytest.fixture
def content_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "content"
    root.mkdir()
    monkeypatch.setattr(Config, "CONTENT_DIR", root, raising=False)
    return root


def _set_auth(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setattr(Config, "AUTH_ENABLED", enabled, raising=False)


def test_auth_off_empty_dir_ok(content_dir: Path, monkeypatch: pytest.MonkeyPatch):
    _set_auth(monkeypatch, False)
    validate_content_layout()  # no raise


def test_auth_off_flat_content_ok(content_dir: Path, monkeypatch: pytest.MonkeyPatch):
    _set_auth(monkeypatch, False)
    (content_dir / "README.md").write_text("hi")
    (content_dir / "notes").mkdir()
    (content_dir / "notes" / "a.md").write_text("a")
    validate_content_layout()  # no raise


def test_auth_off_tenant_shaped_raises(
    content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _set_auth(monkeypatch, False)
    (content_dir / "tenant-uuid" / "docs").mkdir(parents=True)
    with pytest.raises(ContentLayoutError):
        validate_content_layout()


def test_auth_on_empty_dir_ok(content_dir: Path, monkeypatch: pytest.MonkeyPatch):
    _set_auth(monkeypatch, True)
    validate_content_layout()


def test_auth_on_flat_content_raises(
    content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _set_auth(monkeypatch, True)
    (content_dir / "README.md").write_text("hi")
    with pytest.raises(ContentLayoutError):
        validate_content_layout()


def test_auth_on_top_level_file_raises(
    content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _set_auth(monkeypatch, True)
    (content_dir / "stray.txt").write_text("oops")
    with pytest.raises(ContentLayoutError):
        validate_content_layout()


def test_auth_on_tenant_shaped_ok(content_dir: Path, monkeypatch: pytest.MonkeyPatch):
    _set_auth(monkeypatch, True)
    (content_dir / "tenant-a" / "docs").mkdir(parents=True)
    (content_dir / "tenant-a" / "docs" / "x.md").write_text("x")
    validate_content_layout()


def test_auth_on_empty_tenant_dir_ok(
    content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """B1 regression: ``tenant create`` writes a row but no on-disk dir; a
    deployment that later restarts may also have empty tenant dirs after
    stores are removed. Either way, the layout check must accept this."""
    _set_auth(monkeypatch, True)
    (content_dir / "tenant-a").mkdir()
    validate_content_layout()


def test_auth_on_mixed_empty_and_populated_tenants_ok(
    content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _set_auth(monkeypatch, True)
    (content_dir / "tenant-empty").mkdir()
    (content_dir / "tenant-full" / "docs").mkdir(parents=True)
    (content_dir / "tenant-full" / "notes").mkdir()
    validate_content_layout()


def test_dotfiles_ignored(content_dir: Path, monkeypatch: pytest.MonkeyPatch):
    _set_auth(monkeypatch, True)
    (content_dir / ".git").mkdir()
    (content_dir / ".DS_Store").write_text("")
    (content_dir / "tenant-a" / "docs").mkdir(parents=True)
    (content_dir / "tenant-a" / ".git").mkdir()
    (content_dir / "tenant-a" / "docs" / ".cache").mkdir()
    validate_content_layout()


def test_auth_off_dotfiles_only_ok(
    content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    _set_auth(monkeypatch, False)
    (content_dir / ".hidden").write_text("")
    validate_content_layout()


def test_store_root_uses_uuid_then_slug(
    content_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    p = store_root("11111111-1111-1111-1111-111111111111", "docs")
    assert p == content_dir / "11111111-1111-1111-1111-111111111111" / "docs"


def test_validate_creates_missing_content_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "not-yet"
    monkeypatch.setattr(Config, "CONTENT_DIR", root, raising=False)
    _set_auth(monkeypatch, False)
    assert not root.exists()
    validate_content_layout()
    assert root.is_dir()
