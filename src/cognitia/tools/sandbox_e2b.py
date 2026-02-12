"""E2BSandboxProvider — cloud sandbox через E2B API.

Каждая сессия = Firecracker VM. Optional dependency: e2b.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from cognitia.tools.types import ExecutionResult, SandboxConfig, SandboxViolation


class E2BSandboxProvider:
    """SandboxProvider через E2B cloud sandbox.

    LSP: полностью заменяет LocalSandboxProvider.
    """

    def __init__(
        self,
        config: SandboxConfig,
        *,
        _sandbox: Any = None,
        sandbox_factory: Any | None = None,
    ) -> None:
        self._config = config
        self._sandbox = _sandbox
        self._sandbox_factory = sandbox_factory
        self._workspace = "/home/user/workspace"

    def _resolve_path(self, path: str) -> str:
        """Безопасно нормализовать путь относительно workspace."""
        if os.path.isabs(path):
            raise SandboxViolation(f"Абсолютный путь запрещён: {path}", path=path)
        parts = [p for p in path.split("/") if p]
        if any(part == ".." for part in parts):
            raise SandboxViolation(f"Path traversal запрещён: {path}", path=path)
        return "/".join(parts)

    async def _ensure_sandbox(self) -> Any:
        """Ленивая инициализация E2B sandbox."""
        if self._sandbox is not None:
            return self._sandbox

        if self._sandbox_factory is not None:
            created = self._sandbox_factory()
            if hasattr(created, "__await__"):
                created = await created
            self._sandbox = created
            return self._sandbox

        try:
            from e2b_code_interpreter import Sandbox  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "E2B SDK не установлен. Установите optional dependency e2b_code_interpreter.",
            ) from exc

        self._sandbox = Sandbox()
        return self._sandbox

    async def _with_timeout(self, awaitable: Any) -> Any:
        """Ограничить операцию timeout из SandboxConfig."""
        return await asyncio.wait_for(awaitable, timeout=self._config.timeout_seconds)

    def _check_denied_command(self, command: str) -> None:
        denied = self._config.denied_commands or frozenset()
        words = command.split()
        for word in words:
            if os.path.basename(word) in denied:
                raise SandboxViolation(f"Команда '{word}' запрещена", path=command)

    async def read_file(self, path: str) -> str:
        """Прочитать файл через E2B filesystem API."""
        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}"
        sandbox = await self._ensure_sandbox()
        result: str = await self._with_timeout(sandbox.filesystem.read(full_path))
        return result

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл через E2B filesystem API."""
        if len(content.encode("utf-8")) > self._config.max_file_size_bytes:
            raise SandboxViolation(
                f"Файл превышает лимит {self._config.max_file_size_bytes} байт",
                path=path,
            )

        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}"
        sandbox = await self._ensure_sandbox()
        await self._with_timeout(sandbox.filesystem.write(full_path, content))

    async def execute(self, command: str) -> ExecutionResult:
        """Выполнить команду через E2B process API."""
        self._check_denied_command(command)
        sandbox = await self._ensure_sandbox()
        try:
            proc = await self._with_timeout(
                sandbox.process.start(command, cwd=self._workspace),
            )
            return ExecutionResult(
                stdout=getattr(proc, "stdout", "") or "",
                stderr=getattr(proc, "stderr", "") or "",
                exit_code=getattr(proc, "exit_code", 0) or 0,
                timed_out=False,
            )
        except TimeoutError:
            return ExecutionResult(
                stdout="",
                stderr="timeout",
                exit_code=-1,
                timed_out=True,
            )

    async def list_dir(self, path: str = ".") -> list[str]:
        """Список файлов через E2B filesystem API."""
        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}" if safe_path else self._workspace
        sandbox = await self._ensure_sandbox()
        entries = await self._with_timeout(sandbox.filesystem.list(full_path))
        return [e.name for e in entries]

    async def glob_files(self, pattern: str) -> list[str]:
        """Glob через find команду в E2B."""
        sandbox = await self._ensure_sandbox()
        proc = await self._with_timeout(
            sandbox.process.start(
                f"find {self._workspace} -name '{pattern}' -type f",
                cwd=self._workspace,
            )
        )
        stdout = getattr(proc, "stdout", "") or ""
        results = []
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if line and line.startswith(self._workspace):
                rel = line[len(self._workspace) + 1:]
                if rel:
                    results.append(rel)
        return sorted(results)

    async def close(self) -> None:
        """Корректно закрыть sandbox-сессию."""
        if self._sandbox is None:
            return
        for method_name in ("kill", "close"):
            method = getattr(self._sandbox, method_name, None)
            if callable(method):
                result = method()
                if hasattr(result, "__await__"):
                    await result
                break
        self._sandbox = None
