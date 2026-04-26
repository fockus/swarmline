"""PID file management — prevents double-start of daemon."""

from __future__ import annotations

import fcntl
import os
import tempfile

from swarmline.errors import SwarmlineError


class DaemonAlreadyRunningError(SwarmlineError, RuntimeError):
    """Raised when PID file indicates daemon is already running."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        super().__init__(f"Daemon already running with PID {pid}")


class PidFile:
    """PID file management with file locking and stale detection.

    Implements ``ProcessLock`` protocol.

    Uses ``fcntl.flock(LOCK_EX | LOCK_NB)`` to eliminate TOCTOU races:
    the lock file is held for the lifetime of the daemon, and any
    concurrent acquire attempt fails atomically.

    Usage::

        pid = PidFile("/tmp/my-daemon.pid")
        pid.acquire()   # raises DaemonAlreadyRunningError if running
        try:
            ...         # daemon work
        finally:
            pid.release()
    """

    def __init__(self, path: str) -> None:
        self._path = os.path.expanduser(path)
        self._lock_fd: int | None = None  # held while daemon runs

    @property
    def path(self) -> str:
        """Resolved PID file path."""
        return self._path

    def acquire(self) -> None:
        """Acquire PID lock atomically via ``fcntl.flock``.

        Raises ``DaemonAlreadyRunningError`` if another process holds
        the lock. Cleans up stale PID files (process dead, no lock held).
        """
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        lock_path = self._path + ".lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            # Lock held by another process — read their PID
            existing = self.read_pid()
            raise DaemonAlreadyRunningError(existing or 0)

        # Lock acquired — we're the only daemon now
        self._lock_fd = fd

        # Check for stale PID (dead process, no lock — cleaned up above)
        existing = self.read_pid()
        if existing is not None and not _is_process_alive(existing):
            self._remove_pid()

        # Write our PID
        self._write_pid_atomic(os.getpid())

    def release(self) -> None:
        """Release PID lock and remove PID file."""
        stored = self.read_pid()
        if stored is not None and stored == os.getpid():
            self._remove_pid()

        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

            lock_path = self._path + ".lock"
            try:
                os.unlink(lock_path)
            except OSError:
                pass

    def is_running(self) -> bool:
        """Check if daemon is already running (lock held or process alive)."""
        # Try non-blocking lock probe
        lock_path = self._path + ".lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError:
            return False

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # We got the lock — no daemon running
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except OSError:
            # Lock held — daemon running
            return True
        finally:
            os.close(fd)

    def read_pid(self) -> int | None:
        """Read PID from file. Returns None if file doesn't exist."""
        try:
            with open(self._path) as f:
                content = f.read().strip()
            return int(content)
        except (FileNotFoundError, ValueError):
            return None

    def _write_pid_atomic(self, pid: int) -> None:
        """Write PID atomically via tempfile + os.replace."""
        parent = os.path.dirname(self._path)
        fd = -1
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".pid_")
            os.write(fd, f"{pid}\n".encode())
            os.close(fd)
            fd = -1  # mark as closed
            os.replace(tmp_path, self._path)
        except BaseException:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def _remove_pid(self) -> None:
        """Remove PID file, ignoring errors."""
        try:
            os.unlink(self._path)
        except OSError:
            pass


def _is_process_alive(pid: int) -> bool:
    """Check if process with given PID is alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it
        return True
    return True
