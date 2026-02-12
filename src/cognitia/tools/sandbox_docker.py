"""DockerSandboxProvider — sandbox через Docker container.

Каждая сессия = Docker container. Optional dependency: docker SDK.
Container API может быть sync (docker SDK) или async (мок) —
используем _exec_run для абстракции.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shlex
from inspect import iscoroutinefunction
from typing import Any

from cognitia.tools.types import ExecutionResult, SandboxConfig, SandboxViolation


class DockerSandboxProvider:
    """SandboxProvider через Docker container.

    LSP: полностью заменяет LocalSandboxProvider и E2BSandboxProvider.
    """

    def __init__(
        self,
        config: SandboxConfig,
        *,
        _container: Any = None,
        container_factory: Any | None = None,
        image: str = "python:3.12-slim",
    ) -> None:
        self._config = config
        self._container = _container
        self._container_factory = container_factory
        self._image = image
        self._docker_client: Any | None = None
        self._workspace = "/workspace"

    def _resolve_path(self, path: str) -> str:
        """Безопасно нормализовать путь относительно workspace."""
        if os.path.isabs(path):
            raise SandboxViolation(f"Абсолютный путь запрещён: {path}", path=path)
        parts = [p for p in path.split("/") if p]
        if any(part == ".." for part in parts):
            raise SandboxViolation(f"Path traversal запрещён: {path}", path=path)
        return "/".join(parts)

    def _check_denied_command(self, command: str) -> None:
        denied = self._config.denied_commands or frozenset()
        words = command.split()
        for word in words:
            cmd_name = os.path.basename(word)
            if cmd_name in denied:
                raise SandboxViolation(f"Команда '{cmd_name}' запрещена", path=command)

    async def _ensure_container(self) -> Any:
        """Ленивая инициализация docker container."""
        if self._container is not None:
            return self._container

        if self._container_factory is not None:
            created = self._container_factory()
            if hasattr(created, "__await__"):
                created = await created
            self._container = created
            return self._container

        try:
            import docker  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "docker SDK не установлен. Установите optional dependency docker.",
            ) from exc

        try:
            self._docker_client = docker.from_env()
            self._container = self._docker_client.containers.run(
                self._image,
                command="sleep infinity",
                detach=True,
                tty=True,
                working_dir=self._workspace,
            )
        except Exception as exc:
            raise RuntimeError("Docker daemon недоступен для sandbox container.") from exc
        return self._container

    async def _exec(self, cmd: Any, *, timeout_seconds: int | None = None, **kwargs: Any) -> tuple[int, bytes]:
        """Выполнить команду в container. Поддерживает sync и async container."""
        container = await self._ensure_container()
        timeout = timeout_seconds or self._config.timeout_seconds
        exec_run = container.exec_run
        if iscoroutinefunction(exec_run):
            awaited = await asyncio.wait_for(exec_run(cmd, **kwargs), timeout=timeout)
            return awaited
        awaited = await asyncio.wait_for(
            asyncio.to_thread(exec_run, cmd, **kwargs),
            timeout=timeout,
        )
        ret: tuple[int, bytes] = awaited
        return ret

    async def read_file(self, path: str) -> str:
        """Прочитать файл через docker exec cat."""
        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}"
        _exit_code, output = await self._exec(["cat", full_path])
        return output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)

    async def write_file(self, path: str, content: str) -> None:
        """Записать файл через docker exec с передачей content."""
        if len(content.encode("utf-8")) > self._config.max_file_size_bytes:
            raise SandboxViolation(
                f"Файл превышает лимит {self._config.max_file_size_bytes} байт",
                path=path,
            )

        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}"
        # Передаём content через base64 чтобы избежать проблем с escaping
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        quoted_path = shlex.quote(full_path)
        cmd = (
            f"mkdir -p $(dirname {quoted_path}) "
            f"&& echo '{encoded}' | base64 -d > {quoted_path}"
        )
        await self._exec(["sh", "-c", cmd], timeout_seconds=self._config.timeout_seconds)

    async def execute(self, command: str) -> ExecutionResult:
        """Выполнить команду через docker exec."""
        self._check_denied_command(command)
        try:
            exit_code, output = await self._exec(
                ["sh", "-c", command],
                workdir=self._workspace,
                timeout_seconds=self._config.timeout_seconds,
            )
            stdout = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
            return ExecutionResult(stdout=stdout, stderr="", exit_code=exit_code or 0, timed_out=False)
        except TimeoutError:
            return ExecutionResult(stdout="", stderr="timeout", exit_code=-1, timed_out=True)

    async def list_dir(self, path: str = ".") -> list[str]:
        """Список файлов через docker exec ls."""
        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}" if safe_path else self._workspace
        _exit_code, output = await self._exec(f"ls {full_path}")
        raw = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        return [f for f in raw.strip().split("\n") if f]

    async def glob_files(self, pattern: str) -> list[str]:
        """Glob через find в Docker."""
        cmd = (
            f"cd {shlex.quote(self._workspace)} "
            f"&& find . -name {shlex.quote(pattern)} -type f | sed 's|^\\./||'"
        )
        _exit_code, output = await self._exec(["sh", "-c", cmd])
        raw = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        return sorted(f for f in raw.strip().split("\n") if f)

    async def close(self) -> None:
        """Остановить и удалить контейнер."""
        container = self._container
        if container is not None:
            for method_name in ("stop", "remove"):
                method = getattr(container, method_name, None)
                if callable(method):
                    result = method()
                    if hasattr(result, "__await__"):
                        await result
        self._container = None

        if self._docker_client is not None:
            close = getattr(self._docker_client, "close", None)
            if callable(close):
                result = close()
                if hasattr(result, "__await__"):
                    await result
        self._docker_client = None
