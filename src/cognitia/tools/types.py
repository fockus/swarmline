"""Типы для sandbox-изоляции агентов.

SandboxConfig — конфигурация sandbox (root_path, user/topic изоляция, лимиты).
ExecutionResult — результат выполнения команды.
SandboxViolation — исключение при нарушении изоляции.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxConfig:
    """Конфигурация sandbox-изоляции.

    Sandbox обеспечивает изоляцию файловой системы и выполнения команд
    по user_id / topic_id. Каждый агент работает в своём workspace:
    {root_path}/{user_id}/{topic_id}/workspace/
    """

    root_path: str
    user_id: str
    topic_id: str
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    timeout_seconds: int = 30
    allowed_extensions: frozenset[str] | None = None
    denied_commands: frozenset[str] | None = None

    @property
    def workspace_path(self) -> str:
        """Полный путь к workspace агента."""
        return str(Path(self.root_path) / self.user_id / self.topic_id / "workspace")


@dataclass(frozen=True)
class ExecutionResult:
    """Результат выполнения команды в sandbox.

    Содержит stdout, stderr, exit_code и флаг timeout.
    """

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


class SandboxViolation(Exception):
    """Нарушение изоляции sandbox.

    Бросается при попытке path traversal, превышении лимитов
    или выполнении запрещённых команд.
    """

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path
