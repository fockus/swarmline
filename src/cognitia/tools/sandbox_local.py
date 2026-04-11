"""LocalSandboxProvider - sandbox isolation via path restriction for a dev environment.

The agent operates only inside {root}/{user_id}/{topic_id}/workspace/.
Path traversal is forbidden. Commands run with cwd=workspace.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path

import structlog

from cognitia.observability.security import log_security_decision
from cognitia.tools.types import ExecutionResult, SandboxConfig, SandboxViolation

_DENYLIST_WRAPPERS = frozenset({"sh", "bash", "zsh", "ksh", "dash", "fish", "env"})
_log = structlog.get_logger(component="sandbox_local")


class LocalSandboxProvider:
    """Sandbox isolation via filesystem path restriction.

    Provides:
    - Isolation by user_id + topic_id (each workspace is separate)
    - Path traversal blocking (../)
    - Command timeouts
    - File size limits
    - Denied command blocking
    """

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self._workspace = Path(config.workspace_path)

    def _resolve_safe_path(self, path: str) -> Path:
        """Resolve a path inside the workspace while blocking traversal.

        Args:
            path: Relative path from the workspace.

        Returns:
            Absolute Path inside the workspace.

        Raises:
            SandboxViolation: Path traversal or absolute path.
        """
        if os.path.isabs(path):
            raise SandboxViolation(f"Абсолютный путь запрещён: {path}", path=path)

        # Normalize and verify that we do not leave the workspace
        resolved = (self._workspace / path).resolve()
        workspace_resolved = self._workspace.resolve()

        # is_relative_to is safe against prefix bypass (/tmp/ws2 vs /tmp/ws)
        if not resolved.is_relative_to(workspace_resolved):
            raise SandboxViolation(f"Path traversal запрещён: {path}", path=path)

        return resolved

    def _parse_command(self, command: str) -> list[str]:
        """Parse a command string into argv without shell semantics.

        Raises:
            SandboxViolation: Empty or invalid command.
        """
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            raise SandboxViolation(f"Невалидная команда: {command}", path=command) from exc

        if not argv:
            raise SandboxViolation("Пустая команда запрещена", path=command)

        return argv

    def _check_denied_command(self, argv: list[str], raw_command: str) -> None:
        """Check that the command is not in denied_commands.

        Raises:
            SandboxViolation: Command is denied.
        """
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
        """Read a file from the workspace."""
        safe_path = self._resolve_safe_path(path)
        if not safe_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return safe_path.read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        """Write a file to the workspace. Atomic write via tmp + rename."""
        # Check file size limit
        if len(content.encode("utf-8")) > self._config.max_file_size_bytes:
            raise SandboxViolation(
                f"File exceeds the limit of {self._config.max_file_size_bytes} bytes",
                path=path,
            )

        safe_path = self._resolve_safe_path(path)

        # Create intermediate directories
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: tmp -> rename
        tmp_path = safe_path.with_suffix(safe_path.suffix + ".tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(str(tmp_path), str(safe_path))
        except Exception:
            # Remove tmp if rename failed
            tmp_path.unlink(missing_ok=True)
            raise

    async def execute(self, command: str) -> ExecutionResult:
        """Execute a host command in the workspace.

        Host execution is disabled by default and requires an explicit opt-in
        via ``SandboxConfig.allow_host_execution``.
        """
        if not self._config.allow_host_execution:
            log_security_decision(
                _log,
                component="sandbox_local",
                event_name="security.host_execution_denied",
                reason="host_execution_disabled",
                target="execute",
            )
            raise SandboxViolation(
                "Host execution is disabled by default. "
                "Set allow_host_execution=True to enable execute()."
            )

        argv = self._parse_command(command)
        self._check_denied_command(argv, command)

        # Create the workspace if it does not exist
        self._workspace.mkdir(parents=True, exist_ok=True)

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
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
        except TimeoutError:
            # Kill the process on timeout
            if proc is not None:
                proc.kill()
                await proc.wait()
            return ExecutionResult(
                stdout="",
                stderr="timeout",
                exit_code=-1,
                timed_out=True,
            )

    async def list_dir(self, path: str = ".") -> list[str]:
        """List files and directories in the workspace."""
        safe_path = self._resolve_safe_path(path)

        if not safe_path.exists():
            return []

        return sorted(entry.name for entry in safe_path.iterdir())

    async def glob_files(self, pattern: str) -> list[str]:
        """Search for files by glob pattern within the workspace."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._validate_glob_pattern(pattern)

        results: list[str] = []
        workspace_resolved = self._workspace.resolve()

        for match in workspace_resolved.glob(pattern):
            if match.is_file():
                if not match.resolve().is_relative_to(workspace_resolved):
                    raise SandboxViolation(
                        f"Path traversal forbidden: {pattern}",
                        path=pattern,
                    )
                # Return the path relative to the workspace
                rel = match.relative_to(workspace_resolved)
                results.append(str(rel))

        return sorted(results)
