"""E2BSandboxProvider — cloud sandbox через E2B API.

Каждая сессия = Firecracker VM. Optional dependency: e2b.
"""

from __future__ import annotations

from typing import Any

from cognitia.tools.types import ExecutionResult, SandboxConfig


class E2BSandboxProvider:
    """SandboxProvider через E2B cloud sandbox.

    LSP: полностью заменяет LocalSandboxProvider.
    """

    def __init__(self, config: SandboxConfig, *, _sandbox: Any = None) -> None:
        self._config = config
        self._sandbox = _sandbox  # Инжектируется в тестах или создаётся через E2B SDK
        self._workspace = "/home/user/workspace"

    async def read_file(self, path: str) -> str:
        """Прочитать файл через E2B filesystem API."""
        full_path = f"{self._workspace}/{path}"
        result: str = await self._sandbox.filesystem.read(full_path)
        return result

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл через E2B filesystem API."""
        full_path = f"{self._workspace}/{path}"
        await self._sandbox.filesystem.write(full_path, content)

    async def execute(self, command: str) -> ExecutionResult:
        """Выполнить команду через E2B process API."""
        proc = await self._sandbox.process.start(command, cwd=self._workspace)
        return ExecutionResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.exit_code or 0,
            timed_out=False,
        )

    async def list_dir(self, path: str = ".") -> list[str]:
        """Список файлов через E2B filesystem API."""
        full_path = f"{self._workspace}/{path}"
        entries = await self._sandbox.filesystem.list(full_path)
        return [e.name for e in entries]

    async def glob_files(self, pattern: str) -> list[str]:
        """Glob через find команду в E2B."""
        proc = await self._sandbox.process.start(
            f"find {self._workspace} -name '{pattern}' -type f",
            cwd=self._workspace,
        )
        stdout = proc.stdout or ""
        results = []
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if line and line.startswith(self._workspace):
                rel = line[len(self._workspace) + 1:]
                if rel:
                    results.append(rel)
        return sorted(results)
