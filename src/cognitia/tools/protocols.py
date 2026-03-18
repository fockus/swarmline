"""Protocols for agent sandbox isolation.

SandboxProvider is an ISP-compliant interface (≤5 methods) for isolating
the filesystem and executing commands.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cognitia.tools.types import ExecutionResult


@runtime_checkable
class SandboxProvider(Protocol):
    """Sandbox isolation provider for agents.

    Provides safe filesystem access and command execution.
    Isolation is based on user_id + topic_id: each agent runs in its own namespace.

    ISP: <=5 methods. All operations are async.
    """

    async def read_file(self, path: str) -> str:
        """Read a file from the workspace.

        Args:
            path: Relative path from the workspace root.

        Returns:
            File contents.

        Raises:
            FileNotFoundError: File does not exist.
            SandboxViolation: Path traversal or leaving the workspace.
        """
        ...

    async def write_file(self, path: str, content: str) -> None:
        """Write a file to the workspace.

        Creates intermediate directories. Atomic write (tmp + rename).

        Args:
            path: Relative path from the workspace root.
            content: File contents.

        Raises:
            SandboxViolation: Path traversal, leaving the workspace, or limit exceeded.
        """
        ...

    async def execute(self, command: str) -> ExecutionResult:
        """Execute a shell command in the workspace.

        Args:
            command: Command to execute.

        Returns:
            ExecutionResult with stdout, stderr, exit_code, timed_out.

        Raises:
            SandboxViolation: Denied command (from denied_commands).
        """
        ...

    async def list_dir(self, path: str = ".") -> list[str]:
        """List files and directories in the workspace.

        Args:
            path: Relative path from the workspace root.

        Returns:
            List of file/directory names.

        Raises:
            SandboxViolation: Path traversal.
        """
        ...

    async def glob_files(self, pattern: str) -> list[str]:
        """Search for files by glob pattern within the workspace.

        Args:
            pattern: Glob pattern (e.g. "**/*.py").

        Returns:
            List of relative paths from the workspace root.
        """
        ...
