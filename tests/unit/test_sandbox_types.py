"""Тесты типов и протоколов sandbox — TDD: RED phase.

Контрактные тесты для SandboxProvider Protocol, SandboxConfig, ExecutionResult,
SandboxViolation. Написаны ДО реализации.
"""

from __future__ import annotations

import pytest


class TestSandboxConfig:
    """Валидация SandboxConfig dataclass."""

    def test_default_values(self) -> None:
        """SandboxConfig имеет разумные дефолты."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(root_path="/tmp/sandbox", user_id="u1", topic_id="t1")

        assert config.root_path == "/tmp/sandbox"
        assert config.user_id == "u1"
        assert config.topic_id == "t1"
        assert config.max_file_size_bytes == 10 * 1024 * 1024  # 10MB
        assert config.timeout_seconds == 30
        assert config.allowed_extensions is None
        assert config.denied_commands is None

    def test_custom_values(self) -> None:
        """SandboxConfig принимает кастомные значения."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(
            root_path="/data",
            user_id="user-42",
            topic_id="topic-7",
            max_file_size_bytes=1024,
            timeout_seconds=5,
            allowed_extensions={".py", ".txt"},
            denied_commands={"rm", "sudo"},
        )

        assert config.max_file_size_bytes == 1024
        assert config.timeout_seconds == 5
        assert config.allowed_extensions == {".py", ".txt"}
        assert config.denied_commands == {"rm", "sudo"}

    def test_frozen(self) -> None:
        """SandboxConfig не изменяем после создания."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(root_path="/tmp", user_id="u", topic_id="t")
        with pytest.raises(AttributeError):
            config.root_path = "/other"  # type: ignore[misc]

    def test_workspace_path(self) -> None:
        """workspace_path собирается из root/user_id/topic_id/workspace."""
        from cognitia.tools.types import SandboxConfig

        config = SandboxConfig(root_path="/data", user_id="u1", topic_id="t1")
        assert config.workspace_path == "/data/u1/t1/workspace"


class TestExecutionResult:
    """Валидация ExecutionResult dataclass."""

    def test_successful_execution(self) -> None:
        """ExecutionResult для успешной команды."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="hello\n", stderr="", exit_code=0, timed_out=False)

        assert result.stdout == "hello\n"
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.timed_out is False

    def test_failed_execution(self) -> None:
        """ExecutionResult для упавшей команды."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="", stderr="not found", exit_code=1, timed_out=False)

        assert result.exit_code == 1
        assert result.stderr == "not found"

    def test_timed_out_execution(self) -> None:
        """ExecutionResult для команды с timeout."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="partial", stderr="", exit_code=-1, timed_out=True)

        assert result.timed_out is True

    def test_frozen(self) -> None:
        """ExecutionResult не изменяем."""
        from cognitia.tools.types import ExecutionResult

        result = ExecutionResult(stdout="", stderr="", exit_code=0, timed_out=False)
        with pytest.raises(AttributeError):
            result.exit_code = 42  # type: ignore[misc]


class TestSandboxViolation:
    """SandboxViolation — кастомное исключение для нарушений изоляции."""

    def test_is_exception(self) -> None:
        """SandboxViolation наследует Exception."""
        from cognitia.tools.types import SandboxViolation

        exc = SandboxViolation("path traversal detected")
        assert isinstance(exc, Exception)
        assert str(exc) == "path traversal detected"

    def test_with_path(self) -> None:
        """SandboxViolation хранит path нарушения."""
        from cognitia.tools.types import SandboxViolation

        exc = SandboxViolation("traversal", path="../../etc/passwd")
        assert exc.path == "../../etc/passwd"


class TestSandboxProviderProtocol:
    """Контрактные тесты для SandboxProvider Protocol."""

    def test_runtime_checkable(self) -> None:
        """SandboxProvider помечен @runtime_checkable — isinstance работает."""
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
        """Объект без всех методов НЕ проходит isinstance check."""
        from cognitia.tools.protocols import SandboxProvider

        class IncompleteSandbox:
            async def read_file(self, path: str) -> str:
                return ""

        assert not isinstance(IncompleteSandbox(), SandboxProvider)

    def test_protocol_has_five_methods(self) -> None:
        """ISP: SandboxProvider имеет ≤5 методов."""
        from cognitia.tools.protocols import SandboxProvider

        # Считаем публичные async-методы (не dunder, не private)
        methods = [
            name
            for name in dir(SandboxProvider)
            if not name.startswith("_") and callable(getattr(SandboxProvider, name, None))
        ]
        assert len(methods) <= 5, f"ISP violation: {len(methods)} methods > 5: {methods}"

    def test_no_freedom_agent_imports(self) -> None:
        """Чистый domain: нет импортов из freedom_agent."""
        import cognitia.tools.protocols as mod
        import cognitia.tools.types as types_mod

        source_protocols = _get_source(mod)
        source_types = _get_source(types_mod)

        assert "freedom_agent" not in source_protocols
        assert "freedom_agent" not in source_types


def _get_source(module: object) -> str:
    """Получить исходный код модуля."""
    import inspect

    return inspect.getsource(module)
