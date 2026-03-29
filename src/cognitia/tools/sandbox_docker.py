"""DockerSandboxProvider - sandbox via a Docker container.

Each session is a Docker container. Optional dependency: docker SDK.
The container API may be sync (docker SDK) or async (mock) -
use _exec_run for abstraction.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shlex
from inspect import iscoroutinefunction
from typing import Any

from cognitia.tools.types import ExecutionResult, SandboxConfig, SandboxViolation

_DENYLIST_WRAPPERS = frozenset({"sh", "bash", "zsh", "ksh", "dash", "fish", "env"})


class DockerSandboxProvider:
    """SandboxProvider via a Docker container.

    LSP: fully replaces LocalSandboxProvider and E2BSandboxProvider.
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
        """Safely normalize a path relative to the workspace."""
        if os.path.isabs(path):
            raise SandboxViolation(f"Абсолютный путь запрещён: {path}", path=path)
        parts = [p for p in path.split("/") if p]
        if any(part == ".." for part in parts):
            raise SandboxViolation(f"Path traversal запрещён: {path}", path=path)
        return "/".join(parts)

    def _parse_command(self, command: str) -> list[str]:
        """Parse a command string into argv without shell semantics."""
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            raise SandboxViolation(f"Невалидная команда: {command}", path=command) from exc
        if not argv:
            raise SandboxViolation("Пустая команда запрещена", path=command)
        return argv

    def _check_denied_command(self, argv: list[str], raw_command: str) -> None:
        denied = self._config.denied_commands or frozenset()
        cmd_name = os.path.basename(argv[0])
        if cmd_name in _DENYLIST_WRAPPERS:
            raise SandboxViolation(f"Shell wrapper '{cmd_name}' запрещён", path=raw_command)
        for word in argv:
            cmd_name = os.path.basename(word)
            if cmd_name in denied:
                raise SandboxViolation(f"Команда '{cmd_name}' запрещена", path=raw_command)

    @staticmethod
    def _validate_glob_pattern(pattern: str) -> None:
        if os.path.isabs(pattern):
            raise SandboxViolation(f"Абсолютный путь запрещён: {pattern}", path=pattern)
        parts = [p for p in pattern.split("/") if p]
        if any(part == ".." for part in parts):
            raise SandboxViolation(f"Path traversal запрещён: {pattern}", path=pattern)

    async def _ensure_container(self) -> Any:
        """Lazy initialization of the Docker container."""
        if self._container is not None:
            return self._container

        if self._container_factory is not None:
            created = self._container_factory()
            if hasattr(created, "__await__"):
                created = await created
            self._container = created
            return self._container

        try:
            import docker  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "docker SDK is not installed. Install the optional docker dependency.",
            ) from exc

        try:
            self._docker_client = docker.from_env()
            self._container = self._docker_client.containers.run(
                self._image,
                command="sleep infinity",
                detach=True,
                tty=True,
                working_dir=self._workspace,
                # Security hardening
                security_opt=["no-new-privileges=true"],
                cap_drop=["ALL"],
                mem_limit=getattr(self._config, "mem_limit", "512m"),
                network_mode=getattr(self._config, "network_mode", "none"),
                read_only=getattr(self._config, "read_only", False),
            )
        except Exception as exc:
            raise RuntimeError("Docker daemon is unavailable for the sandbox container.") from exc
        return self._container

    async def _exec(
        self, cmd: Any, *, timeout_seconds: int | None = None, **kwargs: Any
    ) -> tuple[int, bytes]:
        """Execute a command in the container. Supports sync and async containers."""
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
        """Read a file via docker exec cat."""
        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}"
        _exit_code, output = await self._exec(["cat", full_path])
        return (
            output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        )

    async def write_file(self, path: str, content: str) -> None:
        """Write a file via docker exec while passing content."""
        if len(content.encode("utf-8")) > self._config.max_file_size_bytes:
            raise SandboxViolation(
                f"Файл превышает лимит {self._config.max_file_size_bytes} байт",
                path=path,
            )

        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}"
        # Write via Python in container — no shell wrapper, content passed as argv
        # base64 encoding ensures no special characters in the argument
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        await self._exec(
            [
                "python3", "-c",
                "import base64,os,sys;"
                "p=sys.argv[1];d=sys.argv[2];"
                "os.makedirs(os.path.dirname(p),exist_ok=True);"
                "open(p,'wb').write(base64.b64decode(d))",
                full_path,
                encoded,
            ],
            timeout_seconds=self._config.timeout_seconds,
        )

    async def execute(self, command: str) -> ExecutionResult:
        """Execute a command via docker exec."""
        argv = self._parse_command(command)
        self._check_denied_command(argv, command)
        try:
            exit_code, output = await self._exec(
                argv,
                workdir=self._workspace,
                timeout_seconds=self._config.timeout_seconds,
            )
            stdout = (
                output.decode("utf-8", errors="replace")
                if isinstance(output, bytes)
                else str(output)
            )
            return ExecutionResult(
                stdout=stdout, stderr="", exit_code=exit_code or 0, timed_out=False
            )
        except TimeoutError:
            return ExecutionResult(stdout="", stderr="timeout", exit_code=-1, timed_out=True)

    async def list_dir(self, path: str = ".") -> list[str]:
        """List files via docker exec ls."""
        safe_path = self._resolve_path(path)
        full_path = f"{self._workspace}/{safe_path}" if safe_path else self._workspace
        _exit_code, output = await self._exec(["ls", full_path])
        raw = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        return [f for f in raw.strip().split("\n") if f]

    async def glob_files(self, pattern: str) -> list[str]:
        """Glob via find in Docker."""
        self._validate_glob_pattern(pattern)
        cmd = (
            f"cd {shlex.quote(self._workspace)} "
            f"&& find . -name {shlex.quote(pattern)} -type f | sed 's|^\\./||'"
        )
        _exit_code, output = await self._exec(["sh", "-c", cmd])
        raw = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
        return sorted(f for f in raw.strip().split("\n") if f)

    async def close(self) -> None:
        """Stop and remove the container."""
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
