"""Unit tests for PidFile."""

from __future__ import annotations

import os
import tempfile

import pytest

from cognitia.daemon.pid import DaemonAlreadyRunningError, PidFile


@pytest.fixture()
def pid_path(tmp_path):
    """Temporary PID file path."""
    return str(tmp_path / "test-daemon.pid")


class TestPidFile:

    def test_acquire_creates_file(self, pid_path: str) -> None:
        pf = PidFile(pid_path)
        pf.acquire()
        assert os.path.exists(pid_path)
        content = open(pid_path).read().strip()
        assert content == str(os.getpid())
        pf.release()

    def test_release_removes_file(self, pid_path: str) -> None:
        pf = PidFile(pid_path)
        pf.acquire()
        pf.release()
        assert not os.path.exists(pid_path)

    def test_double_acquire_raises(self, pid_path: str) -> None:
        pf = PidFile(pid_path)
        pf.acquire()
        try:
            with pytest.raises(DaemonAlreadyRunningError, match="already running"):
                pf.acquire()
        finally:
            pf.release()

    def test_stale_pid_is_cleaned(self, pid_path: str) -> None:
        # Write a PID that doesn't correspond to a running process
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write("999999999\n")  # Very unlikely to be a real PID

        pf = PidFile(pid_path)
        # Should not raise — stale PID is cleaned
        pf.acquire()
        assert pf.read_pid() == os.getpid()
        pf.release()

    def test_is_running_when_not_exists(self, pid_path: str) -> None:
        pf = PidFile(pid_path)
        assert pf.is_running() is False

    def test_is_running_with_current_process(self, pid_path: str) -> None:
        pf = PidFile(pid_path)
        pf.acquire()
        assert pf.is_running() is True
        pf.release()

    def test_is_running_with_stale_pid(self, pid_path: str) -> None:
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write("999999999\n")
        pf = PidFile(pid_path)
        assert pf.is_running() is False

    def test_read_pid_none_when_missing(self, pid_path: str) -> None:
        pf = PidFile(pid_path)
        assert pf.read_pid() is None

    def test_read_pid_returns_int(self, pid_path: str) -> None:
        pf = PidFile(pid_path)
        pf.acquire()
        assert pf.read_pid() == os.getpid()
        pf.release()

    def test_release_only_own_pid(self, pid_path: str) -> None:
        """Release should not remove file if PID doesn't match."""
        os.makedirs(os.path.dirname(pid_path), exist_ok=True)
        with open(pid_path, "w") as f:
            f.write("1\n")  # PID 1 = init, definitely not us
        pf = PidFile(pid_path)
        pf.release()
        # File should still exist — PID 1 is not ours
        assert os.path.exists(pid_path)

    def test_creates_parent_dirs(self, tmp_path) -> None:
        deep_path = str(tmp_path / "a" / "b" / "c" / "daemon.pid")
        pf = PidFile(deep_path)
        pf.acquire()
        assert os.path.exists(deep_path)
        pf.release()

    def test_tilde_expansion(self) -> None:
        pf = PidFile("~/test.pid")
        assert "~" not in pf.path

    def test_protocol_compliance(self, pid_path: str) -> None:
        from cognitia.daemon.protocols import ProcessLock
        pf = PidFile(pid_path)
        assert isinstance(pf, ProcessLock)


class TestDaemonAlreadyRunningError:

    def test_contains_pid(self) -> None:
        err = DaemonAlreadyRunningError(42)
        assert err.pid == 42
        assert "42" in str(err)
