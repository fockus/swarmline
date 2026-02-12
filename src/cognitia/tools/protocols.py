"""Протоколы для sandbox-изоляции агентов.

SandboxProvider — ISP-совместимый интерфейс (≤5 методов) для изоляции
файловой системы и выполнения команд.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cognitia.tools.types import ExecutionResult


@runtime_checkable
class SandboxProvider(Protocol):
    """Провайдер sandbox-изоляции для агентов.

    Обеспечивает безопасный доступ к файловой системе и выполнению команд.
    Изоляция по user_id + topic_id: каждый агент работает в своём namespace.

    ISP: ≤5 методов. Все операции — async.
    """

    async def read_file(self, path: str) -> str:
        """Прочитать файл из workspace.

        Args:
            path: Относительный путь от workspace root.

        Returns:
            Содержимое файла.

        Raises:
            FileNotFoundError: Файл не существует.
            SandboxViolation: Path traversal или выход за workspace.
        """
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл в workspace.

        Создаёт промежуточные директории. Атомарная запись (tmp + rename).

        Args:
            path: Относительный путь от workspace root.
            content: Содержимое файла.

        Raises:
            SandboxViolation: Path traversal, выход за workspace или превышение лимита.
        """
        ...

    async def execute(self, command: str) -> ExecutionResult:
        """Выполнить shell-команду в workspace.

        Args:
            command: Команда для выполнения.

        Returns:
            ExecutionResult с stdout, stderr, exit_code, timed_out.

        Raises:
            SandboxViolation: Запрещённая команда (из denied_commands).
        """
        ...

    async def list_dir(self, path: str = ".") -> list[str]:
        """Список файлов и директорий в workspace.

        Args:
            path: Относительный путь от workspace root.

        Returns:
            Список имён файлов/директорий.

        Raises:
            SandboxViolation: Path traversal.
        """
        ...

    async def glob_files(self, pattern: str) -> list[str]:
        """Поиск файлов по glob-паттерну внутри workspace.

        Args:
            pattern: Glob-паттерн (e.g. "**/*.py").

        Returns:
            Список относительных путей от workspace root.
        """
        ...
