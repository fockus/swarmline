"""LocalGitOperations — subprocess-based git implementation.

Uses asyncio.create_subprocess_exec (never shell=True) with 10s timeout.
Validates branch names and commit hashes to prevent argument injection.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from swarmline.workspace.types import GitOperationResult, WorkspaceSession

_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9/_.\-]+$")
_COMMIT_HASH_RE = re.compile(r"^[0-9a-f]{4,40}$")
_GIT_TIMEOUT_SECONDS = 10


def _validate_branch_name(name: str) -> str | None:
    """Return error message if branch name is invalid, else None."""
    if not name:
        return "Branch name must not be empty"
    if name.startswith("-"):
        return f"Invalid branch name: {name!r} (must not start with '-')"
    if name.startswith("."):
        return f"Invalid branch name: {name!r} (must not start with '.')"
    if ".." in name:
        return f"Invalid branch name: {name!r} (must not contain '..')"
    if name.endswith(".lock"):
        return f"Invalid branch name: {name!r} (must not end with '.lock')"
    if not _BRANCH_NAME_RE.match(name):
        return f"Invalid branch name: {name!r} (allowed: alphanumeric, /, _, ., -)"
    return None


def _validate_commit_hash(commit_hash: str) -> str | None:
    """Return error message if commit hash is invalid, else None."""
    if not commit_hash:
        return "Commit hash must not be empty"
    if commit_hash.startswith("-"):
        return f"Invalid commit hash: {commit_hash!r} (must not start with '-')"
    if not _COMMIT_HASH_RE.match(commit_hash):
        return f"Invalid commit hash: {commit_hash!r} (expected 4-40 hex chars)"
    return None


def _get_cwd(session: WorkspaceSession) -> str:
    """Determine working directory: worktree_path or repo_root."""
    return session.worktree_path if session.worktree_path else session.repo_root


class LocalGitOperations:
    """Git operations via local subprocess.

    Implements GitOperationsPort. All commands use create_subprocess_exec
    with a 10-second timeout. No shell=True.
    """

    async def _run_git(self, cwd: str, *args: str) -> tuple[int, str, str]:
        """Run a git command safely via create_subprocess_exec.

        Returns (exit_code, stdout, stderr).
        Raises TimeoutError if command takes longer than 10 seconds.

        Security: uses create_subprocess_exec (list args, no shell) to prevent
        command injection. All user-supplied arguments (branch names, commit hashes)
        are validated with strict regexes before reaching this method.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=_GIT_TIMEOUT_SECONDS
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        exit_code = proc.returncode if proc.returncode is not None else 1
        return (
            exit_code,
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
        )

    async def diff(self, session: WorkspaceSession) -> GitOperationResult:
        """Get unified diff and list of changed files."""
        cwd = _get_cwd(session)
        try:
            exit_code_diff, diff_output, diff_err = await self._run_git(cwd, "diff")
            exit_code_names, names_output, names_err = await self._run_git(
                cwd, "diff", "--name-only"
            )
        except TimeoutError:
            return GitOperationResult(
                success=False, output="", error="git diff timed out", operation="diff"
            )

        changed_files = tuple(
            line.strip() for line in names_output.splitlines() if line.strip()
        )
        combined_output = diff_output
        error = diff_err.strip() if exit_code_diff != 0 else None

        return GitOperationResult(
            success=(exit_code_diff == 0),
            output=combined_output,
            changed_files=changed_files,
            error=error,
            operation="diff",
        )

    async def status(self, session: WorkspaceSession) -> GitOperationResult:
        """Parse git status --porcelain=v1 into staged/unstaged/untracked."""
        cwd = _get_cwd(session)
        try:
            exit_code, stdout, stderr = await self._run_git(
                cwd, "status", "--porcelain=v1"
            )
        except TimeoutError:
            return GitOperationResult(
                success=False,
                output="",
                error="git status timed out",
                operation="status",
            )

        if exit_code != 0:
            return GitOperationResult(
                success=False,
                output=stdout,
                error=stderr.strip(),
                operation="status",
            )

        staged: list[str] = []
        unstaged: list[str] = []
        untracked: list[str] = []

        for line in stdout.splitlines():
            if len(line) < 3:
                continue
            index_status = line[0]
            worktree_status = line[1]
            file_path = line[3:]

            if index_status == "?" and worktree_status == "?":
                untracked.append(file_path)
            else:
                if index_status not in (" ", "?"):
                    staged.append(file_path)
                if worktree_status not in (" ", "?"):
                    unstaged.append(file_path)

        status_info: dict[str, Any] = {
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
        }
        output = json.dumps(status_info)
        all_files = list({*staged, *unstaged, *untracked})

        return GitOperationResult(
            success=True,
            output=output,
            changed_files=tuple(all_files),
            operation="status",
        )

    async def commit(
        self, session: WorkspaceSession, message: str
    ) -> GitOperationResult:
        """Create a commit with the given message. Returns commit hash on success."""
        cwd = _get_cwd(session)
        if not message or not message.strip():
            return GitOperationResult(
                success=False,
                output="",
                error="Commit message must not be empty",
                operation="commit",
            )

        try:
            exit_code, stdout, stderr = await self._run_git(
                cwd, "commit", "-m", message
            )
        except TimeoutError:
            return GitOperationResult(
                success=False,
                output="",
                error="git commit timed out",
                operation="commit",
            )

        if exit_code != 0:
            return GitOperationResult(
                success=False,
                output=stdout,
                error=stderr.strip() or stdout.strip(),
                operation="commit",
            )

        # Extract commit hash from output like "[branch abc1234] message"
        commit_hash = ""
        for line in stdout.splitlines():
            match = re.search(r"\[[\w/.\-]+ ([0-9a-f]+)\]", line)
            if match:
                commit_hash = match.group(1)
                break

        return GitOperationResult(
            success=True,
            output=commit_hash or stdout,
            changed_files=(),
            operation="commit",
        )

    async def branch_create(
        self, session: WorkspaceSession, name: str
    ) -> GitOperationResult:
        """Create and switch to a new branch. Validates branch name."""
        error = _validate_branch_name(name)
        if error:
            return GitOperationResult(
                success=False, output="", error=error, operation="branch_create"
            )

        cwd = _get_cwd(session)
        try:
            exit_code, stdout, stderr = await self._run_git(cwd, "checkout", "-b", name)
        except TimeoutError:
            return GitOperationResult(
                success=False,
                output="",
                error="git checkout -b timed out",
                operation="branch_create",
            )

        if exit_code != 0:
            return GitOperationResult(
                success=False,
                output=stdout,
                error=stderr.strip() or stdout.strip(),
                operation="branch_create",
            )

        return GitOperationResult(
            success=True,
            output=stdout.strip() or stderr.strip(),
            operation="branch_create",
        )

    async def revert(
        self, session: WorkspaceSession, commit_hash: str
    ) -> GitOperationResult:
        """Revert a commit by hash. Validates hash format."""
        error = _validate_commit_hash(commit_hash)
        if error:
            return GitOperationResult(
                success=False, output="", error=error, operation="revert"
            )

        cwd = _get_cwd(session)
        try:
            exit_code, stdout, stderr = await self._run_git(
                cwd, "revert", "--no-edit", commit_hash
            )
        except TimeoutError:
            return GitOperationResult(
                success=False,
                output="",
                error="git revert timed out",
                operation="revert",
            )

        if exit_code != 0:
            return GitOperationResult(
                success=False,
                output=stdout,
                error=stderr.strip() or stdout.strip(),
                operation="revert",
            )

        return GitOperationResult(
            success=True,
            output=stdout.strip() or stderr.strip(),
            operation="revert",
        )
