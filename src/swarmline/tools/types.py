"""Types for agent sandbox isolation.

SandboxConfig is the sandbox configuration (root_path, user/topic isolation, limits).
ExecutionResult is the result of command execution.
SandboxViolation is raised on isolation violations.
"""

from __future__ import annotations

from dataclasses import dataclass

from swarmline.path_safety import build_isolated_path, validate_namespace_segment


@dataclass(frozen=True)
class SandboxConfig:
    """Sandbox isolation configuration.

    The sandbox isolates filesystem access and command execution
    by user_id / topic_id. Each agent works in its own workspace:
    {root_path}/{user_id}/{topic_id}/workspace/
    """

    root_path: str
    user_id: str
    topic_id: str
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    timeout_seconds: int = 30
    allowed_extensions: frozenset[str] | None = None
    denied_commands: frozenset[str] | None = None
    allow_host_execution: bool = False

    def __post_init__(self) -> None:
        validate_namespace_segment(self.user_id, "user_id")
        validate_namespace_segment(self.topic_id, "topic_id")

    @property
    def workspace_path(self) -> str:
        """Absolute path to the agent workspace."""
        return str(
            build_isolated_path(
                self.root_path, self.user_id, self.topic_id, "workspace"
            )
        )


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing a command in the sandbox.

    Contains stdout, stderr, exit_code, and a timeout flag.
    """

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


class SandboxViolation(Exception):
    """Sandbox isolation violation.

    Raised when path traversal is attempted, limits are exceeded,
    or denied commands are executed.
    """

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path
