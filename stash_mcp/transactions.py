"""Transaction management for Stash-MCP.

Provides :class:`TransactionManager`, which wraps a :class:`~.filesystem.FileSystem`
instance and gates all mutating operations behind an active write transaction.
Only one transaction may be active at a time (globally) and it is owned by a
single MCP session identified by its session object identity.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable

logger = logging.getLogger(__name__)


class TransactionError(Exception):
    """Raised when a transaction operation is invalid."""


def _get_current_session_id() -> str | None:
    """Return the calling MCP session's identity string, or *None*.

    Reads the current FastMCP :class:`Context` from its context-variable so
    the caller does not need to pass a session reference explicitly.
    """
    try:
        from fastmcp.server.context import _current_context

        ctx = _current_context.get()
        return str(id(ctx.session))
    except Exception:
        return None


class TransactionManager:
    """Wraps a :class:`~.filesystem.FileSystem` with transaction-gated writes.

    Read methods delegate directly to the inner filesystem without any
    additional checks.  All mutating methods require an active transaction
    owned by the calling session; if none exists they raise
    :class:`TransactionError`.

    Only one transaction may be held at a time.  Callers that attempt to
    start a transaction while another is active will wait up to
    ``lock_wait`` seconds before receiving a "try again" error.

    Transactions automatically abort (hard-reset) after ``timeout`` seconds
    to prevent orphaned locks.
    """

    def __init__(self, fs, git) -> None:
        self.fs = fs
        self.git = git
        self._lock: asyncio.Lock = asyncio.Lock()
        self._active_session: str | None = None
        self._active_id: str | None = None
        self._timeout_task: asyncio.Task | None = None
        self._pause_sync: Callable[[], None] | None = None
        self._resume_sync: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Sync-pause wiring
    # ------------------------------------------------------------------

    def set_sync_callbacks(
        self,
        pause: Callable[[], None],
        resume: Callable[[], None],
    ) -> None:
        """Register callbacks that pause/resume the periodic git-sync loop."""
        self._pause_sync = pause
        self._resume_sync = resume

    # ------------------------------------------------------------------
    # Transaction lifecycle
    # ------------------------------------------------------------------

    async def start_transaction(
        self,
        session_id: str,
        timeout: int,
        lock_wait: int,
    ) -> str:
        """Acquire the global transaction lock and return a new UUID.

        Args:
            session_id: Opaque identifier for the calling session.
            timeout: Seconds before the transaction is auto-aborted.
            lock_wait: Seconds to wait for the lock before giving up.

        Returns:
            UUID string identifying the new transaction.

        Raises:
            TransactionError: If this session already holds a transaction or
                if the lock is unavailable within *lock_wait* seconds.
        """
        if self._active_session == session_id:
            raise TransactionError(
                "A transaction is already active for this session."
            )

        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=lock_wait)
        except TimeoutError:
            raise TransactionError(
                "Transaction lock unavailable, try again later."
            )

        txn_id = str(uuid.uuid4())
        self._active_session = session_id
        self._active_id = txn_id

        if self._pause_sync is not None:
            self._pause_sync()

        self._timeout_task = asyncio.create_task(
            self._auto_abort(timeout),
            name=f"txn-timeout-{txn_id[:8]}",
        )

        logger.info("Transaction started: %s (session=%s)", txn_id, session_id)
        return txn_id

    async def end_transaction(
        self,
        session_id: str,
        message: str,
        author: str | None = None,
        sync_remote: str | None = None,
        sync_branch: str | None = None,
    ) -> None:
        """Stage + commit all changes and release the lock.

        Args:
            session_id: Must match the session that started the transaction.
            message: Commit message.
            author: Optional author string in ``"Name <email>"`` format.
            sync_remote: If set, push to this remote after committing.
            sync_branch: Branch to push to (required when *sync_remote* is set).

        Raises:
            TransactionError: If *session_id* does not own the active transaction.
            RuntimeError: If the git commit or push fails.
        """
        self._validate_session(session_id)
        self._cancel_timeout()

        try:
            await asyncio.to_thread(self.git.commit, message, author)
            if sync_remote and sync_branch:
                await asyncio.to_thread(self.git.push, sync_remote, sync_branch)
        finally:
            self._clear_and_release()

    async def abort_transaction(self, session_id: str) -> None:
        """Discard all uncommitted changes and release the lock.

        Args:
            session_id: Must match the session that started the transaction.

        Raises:
            TransactionError: If *session_id* does not own the active transaction.
        """
        self._validate_session(session_id)
        self._cancel_timeout()

        try:
            await asyncio.to_thread(self.git.reset_hard)
        finally:
            self._clear_and_release()

    async def _auto_abort(self, timeout: int) -> None:
        """Abort the transaction automatically after *timeout* seconds."""
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return

        if self._active_id is None:
            return  # Transaction ended normally before we were scheduled

        logger.warning(
            "Transaction %s timed out; performing hard reset.", self._active_id
        )
        try:
            await asyncio.to_thread(self.git.reset_hard)
        except Exception as exc:
            logger.error("Hard reset on timeout failed: %s", exc)

        self._clear_and_release()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_session(self, session_id: str) -> None:
        if self._active_session != session_id:
            raise TransactionError("No active transaction for this session.")

    def _cancel_timeout(self) -> None:
        if self._timeout_task is not None and not self._timeout_task.done():
            self._timeout_task.cancel()
        self._timeout_task = None

    def _clear_and_release(self) -> None:
        self._active_session = None
        self._active_id = None
        if self._resume_sync is not None:
            self._resume_sync()
        if self._lock.locked():
            self._lock.release()

    def _require_active_transaction(self) -> None:
        """Raise :class:`TransactionError` when no transaction is active for the calling session."""
        if self._active_id is None:
            raise TransactionError(
                "No active transaction. Call start_content_transaction first."
            )
        session_id = _get_current_session_id()
        if session_id is not None and session_id != self._active_session:
            raise TransactionError(
                "No active transaction. Call start_content_transaction first."
            )

    # ------------------------------------------------------------------
    # FileSystem delegation — reads pass through, writes are gated
    # ------------------------------------------------------------------

    @property
    def content_dir(self):
        return self.fs.content_dir

    @property
    def include_patterns(self):
        return self.fs.include_patterns

    # --- Read methods (unconditional) ---

    def read_file(self, path: str) -> str:
        return self.fs.read_file(path)

    def list_files(self, relative_path: str = "") -> list:
        return self.fs.list_files(relative_path)

    def list_all_files(self, relative_path: str = "") -> list:
        return self.fs.list_all_files(relative_path)

    def file_exists(self, path: str) -> bool:
        return self.fs.file_exists(path)

    # --- Write methods (require active transaction) ---

    def write_file(self, path: str, content: str) -> None:
        self._require_active_transaction()
        return self.fs.write_file(path, content)

    def delete_file(self, path: str) -> None:
        self._require_active_transaction()
        return self.fs.delete_file(path)

    def move_file(self, source_path: str, dest_path: str) -> None:
        self._require_active_transaction()
        return self.fs.move_file(source_path, dest_path)

    def create_directory(self, path: str) -> None:
        self._require_active_transaction()
        return self.fs.create_directory(path)
