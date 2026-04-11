"""Tests tipov and protocolov sandbox - TDD: RED phase. Contractnye tests for SandboxProvider Protocol, SandboxConfig, ExecutionResult,
SandboxViolation. Napisany DO realizatsii.
"""

from __future__ import annotations

import pytest


class TestSandboxConfig:
    """Validation SandboxConfig dataclass."""

    def test_default_values(self) -> None:
        """SandboxConfig imeet razumnye defolty."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(root_path="/tmp/sandbox", user_id="u1", topic_id="t1")

        assert config.root_path == "/tmp/sandbox"
        assert config.user_id == "u1"
        assert config.topic_id == "t1"
        assert config.max_file_size_bytes == 10 * 1024 * 1024  # 10MB
        assert config.timeout_seconds == 30
        assert config.allowed_extensions is None
        assert config.denied_commands is None
        assert config.allow_host_execution is False

    def test_custom_values(self) -> None:
        """SandboxConfig prinimaet kastomnye values."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(
            root_path="/data",
            user_id="user-42",
            topic_id="topic-7",
            max_file_size_bytes=1024,
            timeout_seconds=5,
            allowed_extensions={".py", ".txt"},
            denied_commands={"rm", "sudo"},
            allow_host_execution=True,
        )

        assert config.max_file_size_bytes == 1024
        assert config.timeout_seconds == 5
        assert config.allowed_extensions == {".py", ".txt"}
        assert config.denied_commands == {"rm", "sudo"}
        assert config.allow_host_execution is True

    def test_frozen(self) -> None:
        """SandboxConfig not izmenyaem posle creatediya."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(root_path="/tmp", user_id="u", topic_id="t")
        with pytest.raises(AttributeError):
            config.root_path = "/other"  # type: ignore[misc]

    def test_workspace_path(self) -> None:
        """workspace_path collects from root/user_id/topic_id/workspace."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(root_path="/data", user_id="u1", topic_id="t1")
        assert config.workspace_path == "/data/u1/t1/workspace"


class TestExecutionResult:
    """Validation ExecutionResult dataclass."""

    def test_successful_execution(self) -> None:
        """ExecutionResult for uspeshnoy commands."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="hello\n", stderr="", exit_code=0, timed_out=False)

        assert result.stdout == "hello\n"
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.timed_out is False

    def test_failed_execution(self) -> None:
        """ExecutionResult for upavshey commands."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="", stderr="not found", exit_code=1, timed_out=False)

        assert result.exit_code == 1
        assert result.stderr == "not found"

    def test_timed_out_execution(self) -> None:
        """ExecutionResult for commands with timeout."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="partial", stderr="", exit_code=-1, timed_out=True)

        assert result.timed_out is True

    def test_frozen(self) -> None:
        """ExecutionResult not izmenyaem."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="", stderr="", exit_code=0, timed_out=False)
        with pytest.raises(AttributeError):
            result.exit_code = 42  # type: ignore[misc]


class TestSandboxViolation:
    """SandboxViolation - kastomnoe isklyuchenie for narusheniy izolyatsii."""

    def test_is_exception(self) -> None:
        """SandboxViolation nashould Exception."""
        from cognitia.tools.types import SandboxViolation

        exc = SandboxViolation("path traversal detected")
        assert isinstance(exc, Exception)
        assert str(exc) == "path traversal detected"

    def test_with_path(self) -> None:
        """SandboxViolation hranit path narusheniya."""
        from cognitia.tools.types import SandboxViolation

        exc = SandboxViolation("traversal", path="../../etc/passwd")
        assert exc.path == "../../etc/passwd"


class TestSandboxProviderProtocol:
    """Contractnye tests for SandboxProvider Protocol."""

    def test_runtime_checkable(self) -> None:
        """SandboxProvider pomechen @runtime_checkable - isinstance works."""
        from cognitia.tools.protocols import SandboxProvider

        class FakeSandbox:
            async def read_file(self, path: str) -> str:
                return ""

            async def write_file(self, path: str, content: str) -> None:
                pass

            async def execute(self, command: str) -> object:
                return None

            async def list_dir(self, path: str = ".") -> list[str]:
                return []

            async def glob_files(self, pattern: str) -> list[str]:
                return []

        assert isinstance(FakeSandbox(), SandboxProvider)

    def test_incomplete_implementation_not_instance(self) -> None:
        """Obekt without vseh metodov NE prohodit isinstance check."""
        from cognitia.tools.protocols import SandboxProvider

        class IncompleteSandbox:
            async def read_file(self, path: str) -> str:
                return ""

        assert not isinstance(IncompleteSandbox(), SandboxProvider)

    def test_protocol_has_five_methods(self) -> None:
        """ISP: SandboxProvider imeet ≤5 metodov."""
        from cognitia.tools.protocols import SandboxProvider

        # Schitaem publichnye async-metody (not dunder, not private)
        methods = [
            name
            for name in dir(SandboxProvider)
            if not name.startswith("_") and callable(getattr(SandboxProvider, name, None))
        ]
        assert len(methods) <= 5, f"ISP violation: {len(methods)} methods > 5: {methods}"

    def test_no_freedom_agent_imports(self) -> None:
        """CHistyy domain: nott importov from freedom_agent."""
        import cognitia.tools.protocols as mod
        import cognitia.tools.types as types_mod

        source_protocols = _get_source(mod)
        source_types = _get_source(types_mod)

        assert "freedom_agent" not in source_protocols
        assert "freedom_agent" not in source_types


def _get_source(module: object) -> str:
    """Get ishodnyy kod modulya."""
    import inspect

    return inspect.getsource(module)
