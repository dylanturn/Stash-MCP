"""Tests for TransactionManager and git backend transaction methods."""

import asyncio
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stash_mcp.filesystem import FileSystem
from stash_mcp.transactions import TransactionError, TransactionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(path: Path) -> None:
    """Initialise a bare git repo at *path* with a single commit."""
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
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "Initial commit"],
        check=True,
        capture_output=True,
    )


def _make_tm(tmpdir: Path) -> tuple[TransactionManager, FileSystem]:
    """Create a TransactionManager backed by a real git repo."""
    from stash_mcp.git_backend import GitBackend

    _init_repo(tmpdir)
    fs = FileSystem(tmpdir)
    git = GitBackend(tmpdir)
    return TransactionManager(fs, git), fs


# ---------------------------------------------------------------------------
# GitBackend — commit / reset_hard / push
# ---------------------------------------------------------------------------


class TestGitBackendNewMethods:
    def test_commit_stages_and_commits(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            _init_repo(path)
            from stash_mcp.git_backend import GitBackend

            git = GitBackend(path)
            (path / "new.txt").write_text("hello")
            git.commit("Add new.txt")
            result = subprocess.run(
                ["git", "-C", tmpdir, "log", "--oneline"],
                capture_output=True,
                text=True,
            )
            assert "Add new.txt" in result.stdout

    def test_commit_with_author(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            _init_repo(path)
            from stash_mcp.git_backend import GitBackend

            git = GitBackend(path)
            (path / "authored.txt").write_text("authored content")
            git.commit("Add authored file", author="Custom Author <custom@example.com>")
            result = subprocess.run(
                ["git", "-C", tmpdir, "log", "--format=%an <%ae>", "-1"],
                capture_output=True,
                text=True,
            )
            assert "Custom Author" in result.stdout
            assert "custom@example.com" in result.stdout

    def test_reset_hard_discards_changes(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            _init_repo(path)
            from stash_mcp.git_backend import GitBackend

            git = GitBackend(path)
            (path / "README.md").write_text("changed content")
            git.reset_hard()
            assert (path / "README.md").read_text() == "# Test\n"

    def test_commit_raises_on_nothing_to_commit(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            _init_repo(path)
            from stash_mcp.git_backend import GitBackend

            git = GitBackend(path)
            # Nothing changed — commit should fail
            with pytest.raises(RuntimeError, match="git commit failed"):
                git.commit("Empty commit")

    def test_push_raises_on_no_remote(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            _init_repo(path)
            from stash_mcp.git_backend import GitBackend

            git = GitBackend(path)
            with pytest.raises(RuntimeError, match="git push failed"):
                git.push("nonexistent-remote", "main")


# ---------------------------------------------------------------------------
# TransactionManager — write gating
# ---------------------------------------------------------------------------


class TestTransactionManagerWriteGating:
    @pytest.mark.asyncio
    async def test_write_blocked_without_transaction(self):
        with TemporaryDirectory() as tmpdir:
            tm, fs = _make_tm(Path(tmpdir))
            with pytest.raises(TransactionError, match="No active transaction"):
                tm.write_file("test.txt", "content")

    @pytest.mark.asyncio
    async def test_delete_blocked_without_transaction(self):
        with TemporaryDirectory() as tmpdir:
            tm, fs = _make_tm(Path(tmpdir))
            fs.write_file("README.md", "x")  # write directly to fs
            with pytest.raises(TransactionError, match="No active transaction"):
                tm.delete_file("README.md")

    @pytest.mark.asyncio
    async def test_move_blocked_without_transaction(self):
        with TemporaryDirectory() as tmpdir:
            tm, fs = _make_tm(Path(tmpdir))
            fs.write_file("README.md", "x")
            with pytest.raises(TransactionError, match="No active transaction"):
                tm.move_file("README.md", "moved.md")

    @pytest.mark.asyncio
    async def test_read_passes_without_transaction(self):
        with TemporaryDirectory() as tmpdir:
            tm, fs = _make_tm(Path(tmpdir))
            # README.md created by _init_repo
            content = tm.read_file("README.md")
            assert "Test" in content

    @pytest.mark.asyncio
    async def test_list_passes_without_transaction(self):
        with TemporaryDirectory() as tmpdir:
            tm, fs = _make_tm(Path(tmpdir))
            files = tm.list_all_files()
            assert "README.md" in files

    @pytest.mark.asyncio
    async def test_file_exists_passes_without_transaction(self):
        with TemporaryDirectory() as tmpdir:
            tm, fs = _make_tm(Path(tmpdir))
            assert tm.file_exists("README.md")


# ---------------------------------------------------------------------------
# TransactionManager — lifecycle
# ---------------------------------------------------------------------------


class TestTransactionManagerLifecycle:
    @pytest.mark.asyncio
    async def test_start_returns_uuid(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            txn_id = await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            assert isinstance(txn_id, str)
            import uuid as _uuid
            # Verify it's a valid UUID
            assert _uuid.UUID(txn_id)
            await tm.abort_transaction("session-1")

    @pytest.mark.asyncio
    async def test_write_allowed_during_transaction(self):
        with TemporaryDirectory() as tmpdir:
            tm, fs = _make_tm(Path(tmpdir))
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            # Should not raise
            tm.write_file("new.txt", "hello")
            assert fs.file_exists("new.txt")
            await tm.abort_transaction("session-1")

    @pytest.mark.asyncio
    async def test_end_transaction_commits(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            tm, fs = _make_tm(path)
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            tm.write_file("committed.txt", "content")
            await tm.end_transaction("session-1", "Add committed.txt")
            result = subprocess.run(
                ["git", "-C", tmpdir, "log", "--oneline"],
                capture_output=True,
                text=True,
            )
            assert "Add committed.txt" in result.stdout

    @pytest.mark.asyncio
    async def test_end_transaction_commits_with_author(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            tm, fs = _make_tm(path)
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            tm.write_file("authored.txt", "content")
            await tm.end_transaction(
                "session-1",
                "Add authored file",
                author="Agent Smith <agent@example.com>",
            )
            result = subprocess.run(
                ["git", "-C", tmpdir, "log", "--format=%an <%ae>", "-1"],
                capture_output=True,
                text=True,
            )
            assert "Agent Smith" in result.stdout
            assert "agent@example.com" in result.stdout

    @pytest.mark.asyncio
    async def test_abort_transaction_resets(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            tm, fs = _make_tm(path)
            original = (path / "README.md").read_text()
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            tm.write_file("README.md", "corrupted")
            await tm.abort_transaction("session-1")
            assert (path / "README.md").read_text() == original

    @pytest.mark.asyncio
    async def test_lock_released_after_end(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            await tm.abort_transaction("session-1")
            assert not tm._lock.locked()

    @pytest.mark.asyncio
    async def test_cannot_start_second_transaction_same_session(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            with pytest.raises(TransactionError, match="already active"):
                await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            await tm.abort_transaction("session-1")

    @pytest.mark.asyncio
    async def test_second_session_waits_for_lock(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)

            # Session 2 should time out because session 1 holds the lock
            with pytest.raises(TransactionError, match="unavailable"):
                await tm.start_transaction("session-2", timeout=30, lock_wait=0.1)

            await tm.abort_transaction("session-1")

    @pytest.mark.asyncio
    async def test_end_by_wrong_session_raises(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            with pytest.raises(TransactionError, match="No active transaction for this session"):
                await tm.end_transaction("session-2", "should fail")
            await tm.abort_transaction("session-1")

    @pytest.mark.asyncio
    async def test_abort_by_wrong_session_raises(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            with pytest.raises(TransactionError, match="No active transaction for this session"):
                await tm.abort_transaction("session-2")
            await tm.abort_transaction("session-1")


# ---------------------------------------------------------------------------
# TransactionManager — timeout
# ---------------------------------------------------------------------------


class TestTransactionManagerTimeout:
    @pytest.mark.asyncio
    async def test_transaction_auto_aborts_on_timeout(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            tm, fs = _make_tm(path)
            original = (path / "README.md").read_text()
            await tm.start_transaction("session-1", timeout=0.1, lock_wait=5)
            tm.write_file("README.md", "should be reverted")
            # Wait for auto-abort
            await asyncio.sleep(0.5)
            assert (path / "README.md").read_text() == original
            assert not tm._lock.locked()
            assert tm._active_id is None

    @pytest.mark.asyncio
    async def test_second_session_acquires_lock_after_timeout(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            await tm.start_transaction("session-1", timeout=0.1, lock_wait=5)
            # Wait for auto-abort
            await asyncio.sleep(0.5)
            # Session 2 should now be able to acquire
            txn_id = await tm.start_transaction("session-2", timeout=30, lock_wait=5)
            assert txn_id is not None
            await tm.abort_transaction("session-2")


# ---------------------------------------------------------------------------
# TransactionManager — sync callbacks
# ---------------------------------------------------------------------------


class TestTransactionManagerSyncCallbacks:
    @pytest.mark.asyncio
    async def test_pause_called_on_start(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            pause = MagicMock()
            resume = MagicMock()
            tm.set_sync_callbacks(pause, resume)
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            pause.assert_called_once()
            resume.assert_not_called()
            await tm.abort_transaction("session-1")

    @pytest.mark.asyncio
    async def test_resume_called_on_end(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            pause = MagicMock()
            resume = MagicMock()
            tm.set_sync_callbacks(pause, resume)
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            await tm.abort_transaction("session-1")
            resume.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_called_on_abort(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            pause = MagicMock()
            resume = MagicMock()
            tm.set_sync_callbacks(pause, resume)
            await tm.start_transaction("session-1", timeout=30, lock_wait=5)
            await tm.abort_transaction("session-1")
            resume.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_called_on_timeout(self):
        with TemporaryDirectory() as tmpdir:
            tm, _ = _make_tm(Path(tmpdir))
            pause = MagicMock()
            resume = MagicMock()
            tm.set_sync_callbacks(pause, resume)
            await tm.start_transaction("session-1", timeout=0.1, lock_wait=5)
            await asyncio.sleep(0.5)
            resume.assert_called_once()


# ---------------------------------------------------------------------------
# MCP transaction tools
# ---------------------------------------------------------------------------


class TestMCPTransactionTools:
    """Tests for MCP start/end/abort_content_transaction tools."""

    def _make_mcp(self, tmpdir: Path):
        from stash_mcp.git_backend import GitBackend
        from stash_mcp.mcp_server import create_mcp_server

        _init_repo(tmpdir)
        fs = FileSystem(tmpdir)
        git = GitBackend(tmpdir)
        tm = TransactionManager(fs, git)
        with (
            patch("stash_mcp.mcp_server.Config.READ_ONLY", False),
            patch("stash_mcp.mcp_server.Config.GIT_SYNC_ENABLED", False),
        ):
            mcp = create_mcp_server(tm, git_backend=git)
        return mcp, tm, fs

    def _mock_context(self, session_obj=None):
        from fastmcp.server.context import Context, _current_context

        ctx = MagicMock(spec=Context)
        ctx.session = session_obj or MagicMock()
        ctx.session.send_resource_updated = AsyncMock()
        ctx.send_resource_list_changed = AsyncMock()
        token = _current_context.set(ctx)
        return ctx, token

    @pytest.mark.asyncio
    async def test_transaction_tools_registered(self):
        with TemporaryDirectory() as tmpdir:
            mcp, tm, fs = self._make_mcp(Path(tmpdir))
            tool_names = {t.name for t in await mcp.list_tools()}
            assert "start_content_transaction" in tool_names
            assert "end_content_transaction" in tool_names
            assert "abort_content_transaction" in tool_names

    @pytest.mark.asyncio
    async def test_start_returns_uuid(self):
        with TemporaryDirectory() as tmpdir:
            mcp, tm, fs = self._make_mcp(Path(tmpdir))
            ctx, token = self._mock_context()
            try:
                tool = await mcp.get_tool("start_content_transaction")
                result = await tool.run({})
                import uuid as _uuid

                # The result text should contain a valid UUID string
                text = str(result.content).strip()
                # UUID may be wrapped in quotes/brackets by the serializer; extract it
                import re

                uuid_match = re.search(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    text,
                )
                assert uuid_match is not None, f"No UUID found in result: {text}"
                _uuid.UUID(uuid_match.group())
            finally:
                from fastmcp.server.context import _current_context

                _current_context.reset(token)
                if tm._active_session is not None:
                    await tm.abort_transaction(tm._active_session)

    @pytest.mark.asyncio
    async def test_write_blocked_without_transaction(self):
        with TemporaryDirectory() as tmpdir:
            mcp, tm, fs = self._make_mcp(Path(tmpdir))
            ctx, token = self._mock_context()
            try:
                tool = await mcp.get_tool("create_content")
                with pytest.raises((ValueError, TransactionError)):
                    await tool.run({"path": "new.md", "content": "hello"})
            finally:
                from fastmcp.server.context import _current_context

                _current_context.reset(token)

    @pytest.mark.asyncio
    async def test_write_allowed_after_start(self):
        with TemporaryDirectory() as tmpdir:
            mcp, tm, fs = self._make_mcp(Path(tmpdir))
            session_obj = MagicMock()
            ctx, token = self._mock_context(session_obj)
            try:
                start_tool = await mcp.get_tool("start_content_transaction")
                await start_tool.run({})

                create_tool = await mcp.get_tool("create_content")
                result = await create_tool.run({"path": "new.md", "content": "hello"})
                assert "Created" in str(result.content)
            finally:
                from fastmcp.server.context import _current_context

                _current_context.reset(token)
                if tm._active_session is not None:
                    await tm.abort_transaction(tm._active_session)

    @pytest.mark.asyncio
    async def test_abort_resets_changes(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            mcp, tm, fs = self._make_mcp(path)
            original = (path / "README.md").read_text()
            session_obj = MagicMock()
            ctx, token = self._mock_context(session_obj)
            try:
                start_tool = await mcp.get_tool("start_content_transaction")
                await start_tool.run({})

                replace_tool = await mcp.get_tool("replace_content")
                import hashlib

                sha = hashlib.sha256(original.encode()).hexdigest()
                await replace_tool.run(
                    {"path": "README.md", "content": "corrupted", "sha": sha}
                )

                abort_tool = await mcp.get_tool("abort_content_transaction")
                result = await abort_tool.run({})
                assert "aborted" in str(result.content).lower()
            finally:
                from fastmcp.server.context import _current_context

                _current_context.reset(token)

            assert (path / "README.md").read_text() == original


# ---------------------------------------------------------------------------
# Mode matrix
# ---------------------------------------------------------------------------


class TestModeMatrix:
    """Verify the mode matrix: transaction tools only appear in the right mode."""

    @pytest.mark.asyncio
    async def test_no_transaction_tools_when_read_only(self):
        with TemporaryDirectory() as tmpdir:
            from stash_mcp.git_backend import GitBackend
            from stash_mcp.mcp_server import create_mcp_server

            _init_repo(Path(tmpdir))
            fs = FileSystem(Path(tmpdir))
            git = GitBackend(Path(tmpdir))
            with patch("stash_mcp.mcp_server.Config.READ_ONLY", True):
                mcp = create_mcp_server(fs, git_backend=git)
            tool_names = {t.name for t in await mcp.list_tools()}
            assert "start_content_transaction" not in tool_names
            assert "end_content_transaction" not in tool_names
            assert "abort_content_transaction" not in tool_names

    @pytest.mark.asyncio
    async def test_no_transaction_tools_without_git_tracking(self):
        with TemporaryDirectory() as tmpdir:
            from stash_mcp.mcp_server import create_mcp_server

            fs = FileSystem(Path(tmpdir))
            with patch("stash_mcp.mcp_server.Config.READ_ONLY", False):
                # No git_backend passed → no transaction tools
                mcp = create_mcp_server(fs, git_backend=None)
            tool_names = {t.name for t in await mcp.list_tools()}
            assert "start_content_transaction" not in tool_names

    @pytest.mark.asyncio
    async def test_no_transaction_tools_when_plain_filesystem(self):
        """When git_backend is passed but filesystem is plain FileSystem, no txn tools."""
        with TemporaryDirectory() as tmpdir:
            from stash_mcp.git_backend import GitBackend
            from stash_mcp.mcp_server import create_mcp_server

            _init_repo(Path(tmpdir))
            fs = FileSystem(Path(tmpdir))
            git = GitBackend(Path(tmpdir))
            with patch("stash_mcp.mcp_server.Config.READ_ONLY", False):
                # filesystem is a plain FileSystem (not TransactionManager)
                mcp = create_mcp_server(fs, git_backend=git)
            tool_names = {t.name for t in await mcp.list_tools()}
            assert "start_content_transaction" not in tool_names
