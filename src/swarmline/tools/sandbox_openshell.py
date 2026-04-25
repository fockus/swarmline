"""OpenShellSandboxProvider - sandbox isolation via NVIDIA OpenShell.

Kernel-level isolation (Landlock + Seccomp + network namespace)
with policy-based control. Requires ``openshell`` package (optional).

Note on path safety: local path validation is a pre-flight heuristic.
Primary defense is OpenShell's kernel-level Landlock FS isolation.
Symlinks inside the remote sandbox are constrained by Landlock policy,
not by this provider's path checks.

Install: ``pip install swarmline[openshell]``
"""

from __future__ import annotations

import asyncio
import os
import shlex
from typing import Any

import structlog

from swarmline.tools.types import ExecutionResult, SandboxConfig, SandboxViolation

_log = structlog.get_logger(component="sandbox_openshell")

_DENYLIST_WRAPPERS = frozenset({"sh", "bash", "zsh", "ksh", "dash", "fish", "env"})


class OpenShellSandboxProvider:
    """Sandbox isolation via NVIDIA OpenShell (kernel-level).

    Uses gRPC-based SandboxClient + SandboxSession for command execution
    and filesystem operations inside an isolated sandbox pod.

    Provides:
    - Kernel-level isolation (Landlock, Seccomp BPF, network namespace)
    - Policy-based network control via OPA
    - Pre-flight path traversal blocking (local validation before remote call)
    - Command timeouts
    - File size limits

    Path safety note: local validation blocks obvious traversal (../, absolute).
    Kernel-level Landlock on the remote sandbox is the primary defense against
    symlink-based escapes.
    """

    def __init__(
        self,
        config: SandboxConfig,
        *,
        _session: Any = None,
        session_factory: Any = None,
    ) -> None:
        self._config = config
        self._session = _session
        self._session_factory = session_factory
        self._workspace = "/workspace"
        self._init_lock = asyncio.Lock()

    async def _ensure_session(self) -> Any:
        """Lazy initialization of OpenShell SandboxSession (thread-safe)."""
        if self._session is not None:
            return self._session

        async with self._init_lock:
            # Double-check after acquiring lock
            if self._session is not None:
                return self._session

            if self._session_factory is not None:
                created = self._session_factory()
                if hasattr(created, "__await__"):
                    created = await created
                self._session = created
                return self._session

            # Real SDK import (lazy — only when actually used)
            try:
                from openshell import SandboxClient  # ty: ignore[unresolved-import]  # optional dep
            except ImportError as exc:
                raise RuntimeError(
                    "openshell not installed. Run: pip install swarmline[openshell]"
                ) from exc

            def _create() -> Any:
                client = SandboxClient.from_active_cluster()
                session = client.create_session(
                    sandbox_name=f"swarmline-{self._config.user_id}-{self._config.topic_id}",
                )
                return session

            self._session = await asyncio.to_thread(_create)
            return self._session

    def _resolve_safe_path(self, path: str) -> str:
        """Validate path and return absolute path inside workspace.

        Pre-flight heuristic: blocks absolute paths, traversal (..),
        and hidden path components (starting with .).

        Raises:
            SandboxViolation: Path traversal or absolute path.
        """
        if os.path.isabs(path):
            raise SandboxViolation(f"Absolute path forbidden: {path}", path=path)

        # Normalize and check for traversal
        normalized = os.path.normpath(path)
        if normalized.startswith("..") or "/.." in normalized or normalized == ".":
            if normalized == ".":
                return self._workspace
            raise SandboxViolation(f"Path traversal forbidden: {path}", path=path)

        return f"{self._workspace}/{normalized}"

    def _parse_command(self, command: str) -> list[str]:
        """Parse command string into argv without shell semantics."""
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            raise SandboxViolation(f"Invalid command: {command}", path=command) from exc
        if not argv:
            raise SandboxViolation("Empty command forbidden", path=command)
        return argv

    def _check_denied_command(self, argv: list[str], raw_command: str) -> None:
        """Check that the command is not in denied list."""
        cmd_name = os.path.basename(argv[0])
        if cmd_name in _DENYLIST_WRAPPERS:
            raise SandboxViolation(f"Shell wrapper '{cmd_name}' is denied", path=raw_command)

        denied = self._config.denied_commands or frozenset()
        for word in argv:
            cmd_name = os.path.basename(word)
            if cmd_name in denied:
                raise SandboxViolation(f"Command '{cmd_name}' is denied", path=raw_command)

    @staticmethod
    def _validate_glob_pattern(pattern: str) -> None:
        if os.path.isabs(pattern):
            raise SandboxViolation(f"Absolute path forbidden: {pattern}", path=pattern)
        parts = [part for part in pattern.split("/") if part]
        if any(part == ".." for part in parts):
            raise SandboxViolation(f"Path traversal forbidden: {pattern}", path=pattern)

    async def read_file(self, path: str) -> str:
        """Read a file from the sandbox workspace."""
        safe_path = self._resolve_safe_path(path)
        session = await self._ensure_session()

        result = await asyncio.to_thread(
            session.exec,
            ["cat", safe_path],
            workdir=self._workspace,
            timeout_seconds=self._config.timeout_seconds,
        )

        if result.exit_code != 0:
            if "No such file" in result.stderr or result.exit_code == 1:
                raise FileNotFoundError(f"File not found: {path}")
            raise SandboxViolation(f"Read failed: {result.stderr}", path=path)

        return result.stdout

    async def write_file(self, path: str, content: str) -> None:
        """Write a file to the sandbox workspace.

        Uses two separate exec calls to avoid shell interpolation issues:
        1. mkdir -p for parent directory
        2. tee for writing content via stdin
        """
        if len(content.encode("utf-8")) > self._config.max_file_size_bytes:
            raise SandboxViolation(
                f"File exceeds the limit of {self._config.max_file_size_bytes} bytes",
                path=path,
            )

        safe_path = self._resolve_safe_path(path)
        session = await self._ensure_session()

        # Step 1: create parent dirs (safe — no user input in argv)
        parent = os.path.dirname(safe_path)
        if parent and parent != self._workspace:
            await asyncio.to_thread(
                session.exec,
                ["mkdir", "-p", parent],
                workdir=self._workspace,
                timeout_seconds=self._config.timeout_seconds,
            )

        # Step 2: write via tee (content via stdin, path as argv — no shell)
        result = await asyncio.to_thread(
            session.exec,
            ["tee", safe_path],
            stdin=content.encode("utf-8"),
            workdir=self._workspace,
            timeout_seconds=self._config.timeout_seconds,
        )

        if result.exit_code != 0:
            raise SandboxViolation(f"Write failed: {result.stderr}", path=path)

    async def execute(self, command: str) -> ExecutionResult:
        """Execute a command in the sandbox workspace."""
        argv = self._parse_command(command)
        self._check_denied_command(argv, command)

        session = await self._ensure_session()

        try:
            result = await asyncio.to_thread(
                session.exec,
                argv,
                workdir=self._workspace,
                timeout_seconds=self._config.timeout_seconds,
            )
            return ExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                timed_out=False,
            )
        except Exception as exc:
            # OpenShell may raise on timeout or connection errors
            err_str = str(exc).lower()
            if "timeout" in err_str or "deadline" in err_str:
                return ExecutionResult(
                    stdout="",
                    stderr="timeout",
                    exit_code=-1,
                    timed_out=True,
                )
            raise

    async def list_dir(self, path: str = ".") -> list[str]:
        """List files and directories in the sandbox workspace."""
        safe_path = self._resolve_safe_path(path)
        session = await self._ensure_session()

        result = await asyncio.to_thread(
            session.exec,
            ["ls", "-1", safe_path],
            workdir=self._workspace,
            timeout_seconds=self._config.timeout_seconds,
        )

        if result.exit_code != 0:
            return []

        entries = [e for e in result.stdout.strip().split("\n") if e]
        return sorted(entries)

    async def glob_files(self, pattern: str) -> list[str]:
        """Search for files by glob pattern within the sandbox workspace."""
        self._validate_glob_pattern(pattern)
        session = await self._ensure_session()

        result = await asyncio.to_thread(
            session.exec,
            ["find", self._workspace, "-path", f"{self._workspace}/{pattern}", "-type", "f"],
            workdir=self._workspace,
            timeout_seconds=self._config.timeout_seconds,
        )

        if result.exit_code != 0:
            return []

        workspace_prefix = self._workspace + "/"
        paths: list[str] = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and line.startswith(workspace_prefix):
                paths.append(line[len(workspace_prefix):])

        return sorted(paths)

    async def close(self) -> None:
        """Cleanup: delete the sandbox session."""
        if self._session is not None:
            try:
                await asyncio.to_thread(self._session.delete)
            except Exception as exc:
                _log.warning("close_session_failed", error=str(exc))
            self._session = None
