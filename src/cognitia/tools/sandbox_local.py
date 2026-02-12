"""LocalSandboxProvider — sandbox-изоляция через path restriction для dev-среды.

Агент работает только внутри {root}/{user_id}/{topic_id}/workspace/.
Path traversal запрещён. Команды выполняются с cwd=workspace.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from cognitia.tools.types import ExecutionResult, SandboxConfig, SandboxViolation


class LocalSandboxProvider:
    """Sandbox-изоляция через filesystem path restriction.

    Обеспечивает:
    - Изоляция по user_id + topic_id (каждый workspace отдельный)
    - Блокировка path traversal (../)
    - Timeout для команд
    - Лимит на размер файлов
    - Блокировка запрещённых команд
    """

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self._workspace = Path(config.workspace_path)

    def _resolve_safe_path(self, path: str) -> Path:
        """Разрешить путь внутри workspace, блокируя traversal.

        Args:
            path: Относительный путь от workspace.

        Returns:
            Абсолютный Path внутри workspace.

        Raises:
            SandboxViolation: Path traversal или абсолютный путь.
        """
        if os.path.isabs(path):
            raise SandboxViolation(f"Абсолютный путь запрещён: {path}", path=path)

        # Нормализуем и проверяем что не выходим за workspace
        resolved = (self._workspace / path).resolve()
        workspace_resolved = self._workspace.resolve()

        # is_relative_to безопасен от prefix-bypass (/tmp/ws2 vs /tmp/ws)
        if not resolved.is_relative_to(workspace_resolved):
            raise SandboxViolation(f"Path traversal запрещён: {path}", path=path)

        return resolved

    def _check_denied_command(self, command: str) -> None:
        """Проверить что команда не в denied_commands.

        Raises:
            SandboxViolation: Команда запрещена.
        """
        if not self._config.denied_commands:
            return

        # Извлекаем первое слово (имя команды) и все слова
        words = command.split()
        for word in words:
            # Убираем path prefix (e.g. /usr/bin/rm → rm)
            cmd_name = os.path.basename(word)
            if cmd_name in self._config.denied_commands:
                raise SandboxViolation(
                    f"Команда '{cmd_name}' запрещена", path=command
                )

    async def read_file(self, path: str) -> str:
        """Прочитать файл из workspace."""
        safe_path = self._resolve_safe_path(path)
        if not safe_path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")
        return safe_path.read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл в workspace. Атомарная запись через tmp + rename."""
        # Проверяем лимит размера
        if len(content.encode("utf-8")) > self._config.max_file_size_bytes:
            raise SandboxViolation(
                f"Файл превышает лимит {self._config.max_file_size_bytes} байт",
                path=path,
            )

        safe_path = self._resolve_safe_path(path)

        # Создаём промежуточные директории
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        # Атомарная запись: tmp → rename
        tmp_path = safe_path.with_suffix(safe_path.suffix + ".tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(str(tmp_path), str(safe_path))
        except Exception:
            # Удаляем tmp если rename упал
            tmp_path.unlink(missing_ok=True)
            raise

    async def execute(self, command: str) -> ExecutionResult:
        """Выполнить shell-команду в workspace."""
        self._check_denied_command(command)

        # Создаём workspace если не существует
        self._workspace.mkdir(parents=True, exist_ok=True)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.timeout_seconds,
            )
            return ExecutionResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                timed_out=False,
            )
        except asyncio.TimeoutError:
            # Убиваем процесс при timeout
            proc.kill()
            await proc.wait()
            return ExecutionResult(
                stdout="",
                stderr="timeout",
                exit_code=-1,
                timed_out=True,
            )

    async def list_dir(self, path: str = ".") -> list[str]:
        """Список файлов и директорий в workspace."""
        safe_path = self._resolve_safe_path(path)

        if not safe_path.exists():
            return []

        return sorted(entry.name for entry in safe_path.iterdir())

    async def glob_files(self, pattern: str) -> list[str]:
        """Поиск файлов по glob-паттерну внутри workspace."""
        self._workspace.mkdir(parents=True, exist_ok=True)

        results: list[str] = []
        workspace_resolved = self._workspace.resolve()

        for match in workspace_resolved.glob(pattern):
            if match.is_file():
                # Возвращаем относительный путь от workspace
                rel = match.relative_to(workspace_resolved)
                results.append(str(rel))

        return sorted(results)
