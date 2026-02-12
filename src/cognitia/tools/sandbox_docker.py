"""DockerSandboxProvider — sandbox через Docker container.

Каждая сессия = Docker container. Optional dependency: docker SDK.
Container API может быть sync (docker SDK) или async (мок) —
используем _exec_run для абстракции.
"""

from __future__ import annotations

from typing import Any

from cognitia.tools.types import ExecutionResult, SandboxConfig


class DockerSandboxProvider:
    """SandboxProvider через Docker container.

    LSP: полностью заменяет LocalSandboxProvider и E2BSandboxProvider.
    """

    def __init__(self, config: SandboxConfig, *, _container: Any = None) -> None:
        self._config = config
        self._container = _container
        self._workspace = "/workspace"

    async def _exec(self, cmd: Any, **kwargs: Any) -> tuple[int, bytes]:
        """Выполнить команду в container. Поддерживает sync и async container."""
        result = self._container.exec_run(cmd, **kwargs)
        # AsyncMock возвращает coroutine
        if hasattr(result, "__await__"):
            result = await result
        ret: tuple[int, bytes] = result
        return ret

    async def read_file(self, path: str) -> str:
        """Прочитать файл через docker exec cat."""
        full_path = f"{self._workspace}/{path}"
        _exit_code, output = await self._exec(f"cat {full_path}")
        return output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл через docker exec с передачей content."""
        import base64

        full_path = f"{self._workspace}/{path}"
        # Передаём content через base64 чтобы избежать проблем с escaping
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = f"mkdir -p $(dirname {full_path}) && echo '{encoded}' | base64 -d > {full_path}"
        await self._exec(["sh", "-c", cmd])

    async def execute(self, command: str) -> ExecutionResult:
        """Выполнить команду через docker exec."""
        exit_code, output = await self._exec(
            ["sh", "-c", command], workdir=self._workspace,
        )
        stdout = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        return ExecutionResult(stdout=stdout, stderr="", exit_code=exit_code or 0, timed_out=False)

    async def list_dir(self, path: str = ".") -> list[str]:
        """Список файлов через docker exec ls."""
        full_path = f"{self._workspace}/{path}"
        _exit_code, output = await self._exec(f"ls {full_path}")
        raw = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        return [f for f in raw.strip().split("\n") if f]

    async def glob_files(self, pattern: str) -> list[str]:
        """Glob через find в Docker."""
        cmd = f"cd {self._workspace} && find . -name '{pattern}' -type f | sed 's|^\\./||'"
        _exit_code, output = await self._exec(["sh", "-c", cmd])
        raw = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        return sorted(f for f in raw.strip().split("\n") if f)
