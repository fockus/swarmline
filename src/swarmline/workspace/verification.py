"""WorkspaceVerificationRunner — tests and lint in workspace context.

Uses CommandRunner (from orchestration.code_verifier) for sandbox-agnostic
command execution. Maps results to VerificationResult.

Security: Commands are validated against a shell metacharacter blocklist
to prevent injection via agent-supplied command parameters.
"""

from __future__ import annotations

import re
import shlex

from swarmline.orchestration.code_verifier import CommandRunner
from swarmline.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)
from swarmline.workspace.types import WorkspaceSession

_MAX_OUTPUT_LENGTH = 1000
_DEFAULT_TEST_COMMAND = "pytest"
_DEFAULT_LINT_COMMAND = "ruff check ."

# Shell metacharacters that indicate injection attempts.
_SHELL_METACHAR_RE = re.compile(r"[;|&`$><\n]|\$\(")


def _validate_command(cmd: str) -> str | None:
    """Return error message if command contains shell metacharacters."""
    if _SHELL_METACHAR_RE.search(cmd):
        return f"Command contains forbidden shell metacharacters: {cmd!r}"
    return None


def _truncate(text: str, max_length: int = _MAX_OUTPUT_LENGTH) -> str:
    """Truncate text to max_length, adding indicator if truncated."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "... [truncated]"


def _get_cwd(session: WorkspaceSession) -> str:
    """Determine working directory: worktree_path or repo_root."""
    return session.worktree_path if session.worktree_path else session.repo_root


class WorkspaceVerificationRunner:
    """Runs tests and lints in workspace context.

    Implements VerificationRunnerPort. Delegates execution to a CommandRunner.
    """

    def __init__(self, command_runner: CommandRunner) -> None:
        self._runner = command_runner

    async def _run_command(
        self, session: WorkspaceSession, cmd: str, check_name: str
    ) -> VerificationResult:
        """Run a validated command in workspace context."""
        error = _validate_command(cmd)
        if error:
            return VerificationResult(
                status=VerificationStatus.FAIL,
                checks=(
                    CheckDetail(
                        name=check_name, status=VerificationStatus.FAIL, message=error
                    ),
                ),
                summary=f"{check_name} blocked: command validation failed",
            )

        cwd = _get_cwd(session)
        full_cmd = f"cd {shlex.quote(cwd)} && {cmd}"

        result = await self._runner.run(full_cmd)

        status = (
            VerificationStatus.PASS
            if result.exit_code == 0
            else VerificationStatus.FAIL
        )
        output = _truncate(result.stdout + result.stderr)

        return VerificationResult(
            status=status,
            checks=(CheckDetail(name=check_name, status=status, message=output),),
            summary=f"{check_name} {'passed' if status == VerificationStatus.PASS else 'failed'} (exit code {result.exit_code})",
        )

    async def run_tests(
        self, session: WorkspaceSession, command: str | None = None
    ) -> VerificationResult:
        """Run test command in workspace. Default: pytest."""
        cmd = command or _DEFAULT_TEST_COMMAND
        return await self._run_command(session, cmd, "tests")

    async def run_lint(
        self, session: WorkspaceSession, command: str | None = None
    ) -> VerificationResult:
        """Run lint command in workspace. Default: ruff check ."""
        cmd = command or _DEFAULT_LINT_COMMAND
        return await self._run_command(session, cmd, "lint")
