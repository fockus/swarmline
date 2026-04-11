"""Tests for OpenShellSandboxProvider (NVIDIA OpenShell integration).

All tests use mock session — no real OpenShell cluster required.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from swarmline.tools.sandbox_openshell import OpenShellSandboxProvider
from swarmline.tools.types import SandboxConfig, SandboxViolation


def _config(tmp_path, **kwargs) -> SandboxConfig:
    defaults = {
        "root_path": str(tmp_path),
        "user_id": "u1",
        "topic_id": "t1",
        "denied_commands": frozenset({"rm", "sudo"}),
        "timeout_seconds": 5,
    }
    defaults.update(kwargs)
    return SandboxConfig(**defaults)


@dataclass
class FakeExecResult:
    """Mimics openshell.ExecResult."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""


def _mock_session(exec_result: FakeExecResult | None = None):
    """Create a mock SandboxSession."""
    session = MagicMock()
    session.exec.return_value = exec_result or FakeExecResult()
    session.delete.return_value = True
    return session


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_isinstance_sandbox_provider(self, tmp_path) -> None:
        """OpenShellSandboxProvider satisfies SandboxProvider protocol."""
        from swarmline.tools.protocols import SandboxProvider

        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        assert isinstance(provider, SandboxProvider)


# ---------------------------------------------------------------------------
# Path safety (parity with Local/Docker/E2B)
# ---------------------------------------------------------------------------


class TestPathSafety:
    async def test_read_file_traversal_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation):
            await provider.read_file("../secret.txt")

    async def test_write_file_traversal_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation):
            await provider.write_file("../../etc/passwd", "hacked")

    async def test_absolute_path_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation):
            await provider.read_file("/etc/passwd")

    async def test_glob_traversal_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation):
            await provider.glob_files("../../**/*.py")

    async def test_glob_absolute_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation):
            await provider.glob_files("/etc/**")


# ---------------------------------------------------------------------------
# Command safety
# ---------------------------------------------------------------------------


class TestCommandSafety:
    async def test_denied_command_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation, match="'rm' is denied"):
            await provider.execute("rm -rf /workspace")

    async def test_shell_wrapper_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation, match="'bash' is denied"):
            await provider.execute("bash -c 'echo hacked'")

    async def test_sudo_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation, match="'sudo' is denied"):
            await provider.execute("sudo cat /etc/shadow")

    async def test_empty_command_blocked(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=_mock_session())
        with pytest.raises(SandboxViolation, match="Empty command"):
            await provider.execute("")


# ---------------------------------------------------------------------------
# Read file
# ---------------------------------------------------------------------------


class TestReadFile:
    async def test_read_file_success(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(stdout="hello world", exit_code=0))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        content = await provider.read_file("test.txt")
        assert content == "hello world"
        session.exec.assert_called_once()
        call_args = session.exec.call_args
        assert call_args[0][0] == ["cat", "/workspace/test.txt"]

    async def test_read_file_not_found(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(stderr="No such file", exit_code=1))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        with pytest.raises(FileNotFoundError):
            await provider.read_file("missing.txt")


# ---------------------------------------------------------------------------
# Write file
# ---------------------------------------------------------------------------


class TestWriteFile:
    async def test_write_file_success(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(exit_code=0))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        await provider.write_file("output.txt", "data")
        session.exec.assert_called_once()

    async def test_write_file_size_limit(self, tmp_path) -> None:
        config = _config(tmp_path, max_file_size_bytes=10)
        provider = OpenShellSandboxProvider(config, _session=_mock_session())

        with pytest.raises(SandboxViolation, match="exceeds the limit"):
            await provider.write_file("big.txt", "x" * 100)

    async def test_write_file_creates_parent_dirs(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(exit_code=0))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        await provider.write_file("deep/nested/file.txt", "content")
        # Should call mkdir first, then tee (two separate exec calls)
        assert session.exec.call_count == 2
        mkdir_call = session.exec.call_args_list[0]
        tee_call = session.exec.call_args_list[1]
        assert mkdir_call[0][0] == ["mkdir", "-p", "/workspace/deep/nested"]
        assert tee_call[0][0] == ["tee", "/workspace/deep/nested/file.txt"]


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


class TestExecute:
    async def test_execute_success(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(stdout="output", stderr="", exit_code=0))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        result = await provider.execute("ls -la")
        assert result.stdout == "output"
        assert result.exit_code == 0
        assert result.timed_out is False

    async def test_execute_nonzero_exit(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(stdout="", stderr="error", exit_code=1))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        result = await provider.execute("python3 bad.py")
        assert result.exit_code == 1
        assert result.stderr == "error"

    async def test_execute_timeout_detection(self, tmp_path) -> None:
        session = MagicMock()
        session.exec.side_effect = Exception("deadline exceeded")
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        result = await provider.execute("sleep 999")
        assert result.timed_out is True
        assert result.exit_code == -1


# ---------------------------------------------------------------------------
# List dir / Glob
# ---------------------------------------------------------------------------


class TestListAndGlob:
    async def test_list_dir_success(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(stdout="a.txt\nb.py\ndir1", exit_code=0))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        entries = await provider.list_dir(".")
        assert entries == ["a.txt", "b.py", "dir1"]

    async def test_list_dir_empty(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(stdout="", exit_code=1))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        entries = await provider.list_dir("nonexistent")
        assert entries == []

    async def test_glob_files_success(self, tmp_path) -> None:
        session = _mock_session(FakeExecResult(
            stdout="/workspace/src/main.py\n/workspace/src/util.py",
            exit_code=0,
        ))
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        files = await provider.glob_files("src/*.py")
        assert files == ["src/main.py", "src/util.py"]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_close_deletes_session(self, tmp_path) -> None:
        session = _mock_session()
        provider = OpenShellSandboxProvider(_config(tmp_path), _session=session)

        await provider.close()
        session.delete.assert_called_once()
        assert provider._session is None

    async def test_close_without_session_is_noop(self, tmp_path) -> None:
        provider = OpenShellSandboxProvider(_config(tmp_path))
        await provider.close()  # no exception

    async def test_lazy_init_via_factory(self, tmp_path) -> None:
        """session_factory is called on first use, not on init."""
        session = _mock_session(FakeExecResult(stdout="ok", exit_code=0))
        factory = MagicMock(return_value=session)

        provider = OpenShellSandboxProvider(
            _config(tmp_path), session_factory=factory
        )
        factory.assert_not_called()

        await provider.read_file("test.txt")
        factory.assert_called_once()
