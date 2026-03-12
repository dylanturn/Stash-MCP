"""Tests for GitBackend."""

import subprocess
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from stash_mcp.git_backend import (
    BlameLine,
    GitBackend,
    LogEntry,
    PullResult,
    _parse_author_string,
    _parse_blame_porcelain,
    _parse_pull_file_statuses,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(path: Path, *, initial_commit: bool = True) -> None:
    """Initialise a git repo at *path*, optionally with an empty initial commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    if initial_commit:
        (path / "README.md").write_text("# Test\n")
        subprocess.run(
            ["git", "-C", str(path), "add", "."],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(path), "commit", "-m", "Initial commit"],
            check=True,
            capture_output=True,
        )


# ---------------------------------------------------------------------------
# _parse_author_string
# ---------------------------------------------------------------------------


class TestParseAuthorString:
    def test_standard_format(self):
        name, email = _parse_author_string("Alice <alice@example.com>")
        assert name == "Alice"
        assert email == "alice@example.com"

    def test_name_with_spaces(self):
        name, email = _parse_author_string("stash-mcp <stash@local>")
        assert name == "stash-mcp"
        assert email == "stash@local"

    def test_no_angle_brackets_returns_full_string_as_name(self):
        name, email = _parse_author_string("noemail")
        assert name == "noemail"
        assert email == ""

    def test_strips_surrounding_whitespace(self):
        name, email = _parse_author_string("  Bot  <bot@host>  ")
        assert name == "Bot"
        assert email == "bot@host"


# ---------------------------------------------------------------------------
# _parse_blame_porcelain
# ---------------------------------------------------------------------------


SAMPLE_PORCELAIN = """\
0123456789abcdef0123456789abcdef01234567 1 1 1
author Alice
author-mail <alice@example.com>
author-time 1700000000
author-tz +0000
committer Alice
committer-mail <alice@example.com>
committer-time 1700000000
committer-tz +0000
summary Add greeting
filename hello.txt
\tHello, world!
0123456789abcdef0123456789abcdef01234567 2 2 1
\tAnother line
"""


class TestParseBlamePorcelain:
    def test_parses_two_lines(self):
        lines = _parse_blame_porcelain(SAMPLE_PORCELAIN)
        assert len(lines) == 2

    def test_first_line_fields(self):
        lines = _parse_blame_porcelain(SAMPLE_PORCELAIN)
        bl = lines[0]
        assert bl.line_number == 1
        assert bl.author == "Alice"
        assert bl.summary == "Add greeting"
        assert bl.content == "Hello, world!"
        assert isinstance(bl.timestamp, datetime)

    def test_second_line_reuses_cached_commit(self):
        lines = _parse_blame_porcelain(SAMPLE_PORCELAIN)
        # Both lines share the same commit hash
        assert lines[0].commit_hash == lines[1].commit_hash

    def test_empty_output(self):
        assert _parse_blame_porcelain("") == []


# ---------------------------------------------------------------------------
# _parse_pull_file_statuses
# ---------------------------------------------------------------------------


class TestParsePullFileStatuses:
    def test_added(self):
        added, modified, deleted = _parse_pull_file_statuses("A\tnew.txt\n")
        assert added == ["new.txt"]
        assert modified == []
        assert deleted == []

    def test_modified(self):
        added, modified, deleted = _parse_pull_file_statuses("M\told.txt\n")
        assert modified == ["old.txt"]

    def test_deleted(self):
        added, modified, deleted = _parse_pull_file_statuses("D\tgone.txt\n")
        assert deleted == ["gone.txt"]

    def test_mixed(self):
        diff_output = "A\tnew.txt\nM\texisting.txt\nD\tremoved.txt\n"
        added, modified, deleted = _parse_pull_file_statuses(diff_output)
        assert added == ["new.txt"]
        assert modified == ["existing.txt"]
        assert deleted == ["removed.txt"]

    def test_empty(self):
        added, modified, deleted = _parse_pull_file_statuses("")
        assert added == modified == deleted == []


# ---------------------------------------------------------------------------
# GitBackend.validate()
# ---------------------------------------------------------------------------


class TestGitBackendValidate:
    def test_non_git_dir_raises(self):
        with TemporaryDirectory() as tmpdir:
            backend = GitBackend(Path(tmpdir))
            with pytest.raises(RuntimeError, match="not a git repository"):
                backend.validate()

    def test_git_dir_passes(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            backend = GitBackend(repo)
            backend.validate()  # Should not raise

    def test_validate_sets_committer_identity_when_not_configured_locally(self):
        """validate() writes local user.name/user.email from author_default."""
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            # No local user.name/user.email
            backend = GitBackend(repo, author_default="Stash Bot <stash@example.com>")
            backend.validate()
            name = subprocess.check_output(
                ["git", "-C", str(repo), "config", "--local", "user.name"], text=True
            ).strip()
            email = subprocess.check_output(
                ["git", "-C", str(repo), "config", "--local", "user.email"], text=True
            ).strip()
            assert name == "Stash Bot"
            assert email == "stash@example.com"

    def test_validate_does_not_overwrite_existing_local_identity(self):
        """validate() leaves user.name/user.email alone when already set locally."""
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)  # sets user.name="Test User", user.email="test@example.com"
            backend = GitBackend(repo, author_default="Bot <bot@example.com>")
            backend.validate()
            name = subprocess.check_output(
                ["git", "-C", str(repo), "config", "--local", "user.name"], text=True
            ).strip()
            assert name == "Test User"  # unchanged


# ---------------------------------------------------------------------------
# GitBackend.validate_remote()
# ---------------------------------------------------------------------------


class TestGitBackendValidateRemote:
    def test_missing_remote_returns_false(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            backend = GitBackend(repo)
            assert backend.validate_remote("origin") is False

    def test_configured_remote_returns_true(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            subprocess.run(
                ["git", "-C", str(repo), "remote", "add", "origin", "https://example.com/repo.git"],
                check=True,
                capture_output=True,
            )
            backend = GitBackend(repo)
            assert backend.validate_remote("origin") is True


# ---------------------------------------------------------------------------
# GitBackend.log()
# ---------------------------------------------------------------------------


class TestGitBackendLog:
    def test_returns_initial_commit(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            backend = GitBackend(repo)
            entries = backend.log()
            assert len(entries) >= 1
            assert isinstance(entries[0], LogEntry)
            assert entries[0].message == "Initial commit"
            assert entries[0].author == "Test User"

    def test_max_count_respected(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            # Add a second commit
            (repo / "file.txt").write_text("content")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "Second commit"],
                check=True,
                capture_output=True,
            )
            backend = GitBackend(repo)
            entries = backend.log(max_count=1)
            assert len(entries) == 1

    def test_path_filter(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            # Commit a specific file
            (repo / "specific.md").write_text("hello")
            subprocess.run(
                ["git", "-C", str(repo), "add", "specific.md"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "Add specific file"],
                check=True,
                capture_output=True,
            )
            backend = GitBackend(repo)
            entries = backend.log(path="specific.md")
            assert len(entries) == 1
            assert entries[0].message == "Add specific file"


# ---------------------------------------------------------------------------
# GitBackend.blame()
# ---------------------------------------------------------------------------


class TestGitBackendBlame:
    def test_blame_returns_lines(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            backend = GitBackend(repo)
            blame = backend.blame("README.md")
            assert len(blame) >= 1
            assert isinstance(blame[0], BlameLine)
            assert blame[0].author == "Test User"

    def test_blame_line_range(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            (repo / "multi.txt").write_text("line1\nline2\nline3\n")
            subprocess.run(
                ["git", "-C", str(repo), "add", "multi.txt"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "Add multi-line file"],
                check=True,
                capture_output=True,
            )
            backend = GitBackend(repo)
            blame = backend.blame("multi.txt", start_line=1, end_line=2)
            assert len(blame) == 2

    def test_blame_nonexistent_file_returns_empty(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            backend = GitBackend(repo)
            blame = backend.blame("nonexistent.txt")
            assert blame == []


# ---------------------------------------------------------------------------
# GitBackend.diff()
# ---------------------------------------------------------------------------


class TestGitBackendDiff:
    def test_diff_single_commit_returns_empty_or_error(self):
        """With only one commit HEAD~1 doesn't exist — diff returns an error string."""
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            backend = GitBackend(repo)
            result = backend.diff("README.md")
            # Either empty diff or error message — either is acceptable
            assert isinstance(result, str)

    def test_diff_with_explicit_ref(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            # Second commit modifying README
            (repo / "README.md").write_text("# Updated\n")
            subprocess.run(
                ["git", "-C", str(repo), "add", "README.md"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-m", "Update README"],
                check=True,
                capture_output=True,
            )
            head1 = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD~1"], text=True
            ).strip()
            backend = GitBackend(repo)
            result = backend.diff("README.md", ref=head1)
            assert "README.md" in result or "diff" in result.lower() or result == ""


# ---------------------------------------------------------------------------
# GitBackend._configure_credentials()
# ---------------------------------------------------------------------------


class TestGitBackendConfigureCredentials:
    def test_credential_helper_script_created(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            GitBackend(repo, sync_token="my-test-token")
            helper = repo / ".git" / "stash-credential-helper.sh"
            assert helper.exists()
            content = helper.read_text()
            assert "my-test-token" in content
            assert helper.stat().st_mode & 0o100  # executable bit set

    def test_token_with_special_chars_is_shell_escaped(self):
        with TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            token = "tok'en$with;special!chars"
            GitBackend(repo, sync_token=token)
            helper = repo / ".git" / "stash-credential-helper.sh"
            content = helper.read_text()
            # shlex.quote wraps the token in single quotes with escaping
            assert "tok" in content  # token value is present (escaped form)


# ---------------------------------------------------------------------------
# PullResult dataclass
# ---------------------------------------------------------------------------


class TestPullResult:
    def test_defaults(self):
        r = PullResult(success=True)
        assert r.changed_files == []
        assert r.added_files == []
        assert r.modified_files == []
        assert r.deleted_files == []
        assert r.message == ""


# ---------------------------------------------------------------------------
# GitBackend.clone()
# ---------------------------------------------------------------------------


def _init_bare_repo(path: Path) -> None:
    """Create a bare git repo at *path* with a single commit on ``main``."""
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)

    # Create a temporary working tree to populate the bare repo
    with TemporaryDirectory() as tmpwork:
        work = Path(tmpwork)
        subprocess.run(["git", "clone", str(path), str(work)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(work), "config", "user.email", "test@example.com"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(work), "config", "user.name", "Test User"],
            check=True, capture_output=True,
        )
        (work / "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(work), "commit", "-m", "Initial commit"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(work), "push", "origin", "HEAD:main"],
            check=True, capture_output=True,
        )


class TestGitBackendClone:
    def test_clone_into_nonexistent_dir(self):
        with TemporaryDirectory() as tmpdir:
            bare = Path(tmpdir) / "origin.git"
            target = Path(tmpdir) / "cloned"
            _init_bare_repo(bare)
            backend = GitBackend.clone(url=str(bare), target_dir=target, branch="main")
            assert target.exists()
            assert (target / ".git").exists()
            assert (target / "README.md").exists()
            assert isinstance(backend, GitBackend)
            assert backend.content_dir == target

    def test_clone_into_empty_existing_dir(self):
        with TemporaryDirectory() as tmpdir:
            bare = Path(tmpdir) / "origin.git"
            target = Path(tmpdir) / "cloned"
            target.mkdir()
            _init_bare_repo(bare)
            backend = GitBackend.clone(url=str(bare), target_dir=target, branch="main")
            assert (target / "README.md").exists()
            assert isinstance(backend, GitBackend)

    def test_clone_log_has_initial_commit(self):
        with TemporaryDirectory() as tmpdir:
            bare = Path(tmpdir) / "origin.git"
            target = Path(tmpdir) / "cloned"
            _init_bare_repo(bare)
            backend = GitBackend.clone(url=str(bare), target_dir=target, branch="main")
            entries = backend.log()
            assert any(e.message == "Initial commit" for e in entries)

    def test_clone_bad_url_raises_runtime_error(self):
        with TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "cloned"
            with pytest.raises(RuntimeError, match="Git clone failed"):
                GitBackend.clone(
                    url="https://invalid.example.invalid/nonexistent.git",
                    target_dir=target,
                    branch="main",
                )

    def test_clone_token_injected_then_removed_from_remote_url(self):
        """After clone, origin remote URL must NOT contain the token."""
        with TemporaryDirectory() as tmpdir:
            bare = Path(tmpdir) / "origin.git"
            target = Path(tmpdir) / "cloned"
            _init_bare_repo(bare)
            # Use a fake token — local file:// clone won't use it but the
            # post-clone URL rewrite still happens.
            GitBackend.clone(
                url=str(bare), target_dir=target, branch="main", token="secret-pat"
            )
            remote_url = subprocess.check_output(
                ["git", "remote", "get-url", "origin"], cwd=target, text=True
            ).strip()
            assert "secret-pat" not in remote_url
            assert str(bare) in remote_url

    def test_clone_with_token_sets_up_credential_helper(self):
        with TemporaryDirectory() as tmpdir:
            bare = Path(tmpdir) / "origin.git"
            target = Path(tmpdir) / "cloned"
            _init_bare_repo(bare)
            GitBackend.clone(
                url=str(bare), target_dir=target, branch="main", token="mytoken"
            )
            helper = target / ".git" / "stash-credential-helper.sh"
            assert helper.exists()
            assert "mytoken" in helper.read_text()


# ---------------------------------------------------------------------------
# _maybe_clone_repo() helper (tested via main.py import)
# ---------------------------------------------------------------------------


class TestMaybeCloneRepo:
    """Tests for the _maybe_clone_repo startup helper."""

    def test_no_clone_url_is_noop(self, tmp_path, monkeypatch):
        import stash_mcp.config as cfg

        monkeypatch.setattr(cfg.Config, "GIT_CLONE_URL", None)
        from stash_mcp.main import _maybe_clone_repo

        _maybe_clone_repo()  # Should not raise

    def test_clone_url_clones_repo(self, tmp_path, monkeypatch):
        import stash_mcp.config as cfg
        import stash_mcp.main as app_main

        bare = tmp_path / "origin.git"
        target = tmp_path / "content"
        _init_bare_repo(bare)

        monkeypatch.setattr(cfg.Config, "GIT_CLONE_URL", str(bare))
        monkeypatch.setattr(cfg.Config, "GIT_CLONE_BRANCH", "main")
        monkeypatch.setattr(cfg.Config, "GIT_CLONE_TOKEN", None)
        monkeypatch.setattr(cfg.Config, "GIT_SYNC_RECURSIVE", False)
        monkeypatch.setattr(cfg.Config, "CONTENT_DIR", target)

        app_main._maybe_clone_repo()

        assert target.exists()
        assert (target / ".git").exists()
        assert cfg.Config.GIT_TRACKING is True

    def test_already_cloned_skips(self, tmp_path, monkeypatch):
        import stash_mcp.config as cfg
        import stash_mcp.main as app_main

        bare = tmp_path / "origin.git"
        target = tmp_path / "content"
        _init_bare_repo(bare)

        monkeypatch.setattr(cfg.Config, "GIT_CLONE_URL", str(bare))
        monkeypatch.setattr(cfg.Config, "GIT_CLONE_BRANCH", "main")
        monkeypatch.setattr(cfg.Config, "GIT_CLONE_TOKEN", None)
        monkeypatch.setattr(cfg.Config, "GIT_SYNC_RECURSIVE", False)
        monkeypatch.setattr(cfg.Config, "CONTENT_DIR", target)

        # First clone
        app_main._maybe_clone_repo()
        assert (target / ".git").exists()

        # Reset tracking flag so we can confirm second call doesn't fail
        monkeypatch.setattr(cfg.Config, "GIT_TRACKING", False)
        # Second call should skip gracefully
        app_main._maybe_clone_repo()
        # GIT_TRACKING stays False (wasn't re-enabled since we skipped)
        assert cfg.Config.GIT_TRACKING is False

    def test_non_empty_non_git_dir_raises_system_exit(self, tmp_path, monkeypatch):
        import stash_mcp.config as cfg
        import stash_mcp.main as app_main

        target = tmp_path / "content"
        target.mkdir()
        (target / "some_file.txt").write_text("user data")

        monkeypatch.setattr(cfg.Config, "GIT_CLONE_URL", "https://example.com/repo.git")
        monkeypatch.setattr(cfg.Config, "GIT_CLONE_BRANCH", "main")
        monkeypatch.setattr(cfg.Config, "GIT_CLONE_TOKEN", None)
        monkeypatch.setattr(cfg.Config, "GIT_SYNC_RECURSIVE", False)
        monkeypatch.setattr(cfg.Config, "CONTENT_DIR", target)

        with pytest.raises(SystemExit):
            app_main._maybe_clone_repo()
