"""Contract tests for GitOperationsPort.

Every correct GitOperationsPort implementation MUST pass all these tests.
Tests assert observable behavior (result types, success/failure, output content)
— never subprocess internals.

Categories:
- Diff operations (3 tests)
- Status operations (4 tests)
- Commit operations (2 tests)
- Branch operations (2 tests)
- Revert operations (2 tests)

Total: 13+ contract tests.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from swarmline.workspace.protocols import GitOperationsPort
from swarmline.workspace.types import (
    GitOperationResult,
    MutationMode,
    WorkspaceSession,
)

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not found")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _run_git(cwd: str, *args: str) -> str:
    """Run a git command, return stdout. Raise on failure."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.decode()}")
    return stdout.decode()


@pytest.fixture
async def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit for contract testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cwd = str(repo)

    await _run_git(cwd, "init")
    await _run_git(cwd, "config", "user.name", "Test User")
    await _run_git(cwd, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("initial content\n")
    await _run_git(cwd, "add", ".")
    await _run_git(cwd, "commit", "-m", "initial commit")
    return repo


@pytest.fixture
def workspace_session(git_repo: Path) -> WorkspaceSession:
    """WorkspaceSession pointing at the test git repo."""
    return WorkspaceSession.create(
        session_id="contract-test-session",
        repo_root=str(git_repo),
        branch="main",
        mutation_mode=MutationMode.AUTO_APPLY,
    )


@pytest.fixture(params=["local"])
def git_operations(request: pytest.FixtureRequest) -> GitOperationsPort:
    """Parameterized fixture: all GitOperationsPort implementations."""
    if request.param == "local":
        from swarmline.workspace.git_local import LocalGitOperations

        return LocalGitOperations()
    raise ValueError(f"Unknown git operations impl: {request.param}")


# =====================================================================
# 1. Diff Operations (3 tests)
# =====================================================================


class TestDiffContract:
    """Contract: diff returns GitOperationResult with diff content."""

    async def test_diff_no_changes_returns_empty_output(
        self, git_operations: GitOperationsPort, workspace_session: WorkspaceSession
    ) -> None:
        """Clean repo diff returns success with empty output."""
        result = await git_operations.diff(workspace_session)

        assert isinstance(result, GitOperationResult)
        assert result.success is True
        assert result.output == ""
        assert result.changed_files == ()

    async def test_diff_with_modified_file_returns_unified_diff(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """Modified file produces non-empty unified diff."""
        (git_repo / "README.md").write_text("modified content\n")

        result = await git_operations.diff(workspace_session)

        assert result.success is True
        assert len(result.output) > 0
        assert "modified content" in result.output

    async def test_diff_changed_files_lists_modified_paths(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """changed_files includes paths of modified files."""
        (git_repo / "README.md").write_text("changed\n")

        result = await git_operations.diff(workspace_session)

        assert result.success is True
        assert "README.md" in result.changed_files


# =====================================================================
# 2. Status Operations (4 tests)
# =====================================================================


class TestStatusContract:
    """Contract: status returns structured info about repo state."""

    async def test_status_clean_repo_returns_empty_lists(
        self, git_operations: GitOperationsPort, workspace_session: WorkspaceSession
    ) -> None:
        """Clean repo status has no staged, unstaged, or untracked files."""
        result = await git_operations.status(workspace_session)

        assert isinstance(result, GitOperationResult)
        assert result.success is True
        assert result.changed_files == ()

    async def test_status_modified_file_appears_in_unstaged(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """Modified but unstaged file appears in the result."""
        (git_repo / "README.md").write_text("changed\n")

        result = await git_operations.status(workspace_session)

        assert result.success is True
        status_data = json.loads(result.output)
        assert "README.md" in status_data["unstaged"]

    async def test_status_staged_file_appears_in_staged(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """Staged file appears in staged list."""
        (git_repo / "README.md").write_text("staged change\n")
        await _run_git(str(git_repo), "add", "README.md")

        result = await git_operations.status(workspace_session)

        assert result.success is True
        status_data = json.loads(result.output)
        assert "README.md" in status_data["staged"]

    async def test_status_untracked_file_appears_in_untracked(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """New untracked file appears in untracked list."""
        (git_repo / "newfile.py").write_text("print('hello')\n")

        result = await git_operations.status(workspace_session)

        assert result.success is True
        status_data = json.loads(result.output)
        assert "newfile.py" in status_data["untracked"]


# =====================================================================
# 3. Commit Operations (2 tests)
# =====================================================================


class TestCommitContract:
    """Contract: commit creates a commit with staged changes."""

    async def test_commit_with_staged_changes_returns_hash(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """Commit with staged changes succeeds and returns a commit hash."""
        (git_repo / "README.md").write_text("committed content\n")
        await _run_git(str(git_repo), "add", "README.md")

        result = await git_operations.commit(workspace_session, "test commit message")

        assert result.success is True
        assert len(result.output) > 0

    async def test_commit_empty_returns_failure(
        self, git_operations: GitOperationsPort, workspace_session: WorkspaceSession
    ) -> None:
        """Commit with no staged changes returns failure."""
        result = await git_operations.commit(workspace_session, "empty commit")

        assert result.success is False
        assert result.error is not None


# =====================================================================
# 4. Branch Operations (2 tests)
# =====================================================================


class TestBranchContract:
    """Contract: branch_create creates a new branch."""

    async def test_branch_create_new_branch_succeeds(
        self, git_operations: GitOperationsPort, workspace_session: WorkspaceSession
    ) -> None:
        """Creating a new branch succeeds."""
        result = await git_operations.branch_create(
            workspace_session, "feat/new-branch"
        )

        assert result.success is True

    async def test_branch_create_existing_returns_error(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """Creating a branch that already exists returns failure."""
        await _run_git(str(git_repo), "branch", "existing-branch")

        result = await git_operations.branch_create(
            workspace_session, "existing-branch"
        )

        assert result.success is False
        assert result.error is not None


# =====================================================================
# 5. Revert Operations (2 tests)
# =====================================================================


class TestRevertContract:
    """Contract: revert undoes a commit by hash."""

    async def test_revert_own_commit_succeeds(
        self,
        git_operations: GitOperationsPort,
        workspace_session: WorkspaceSession,
        git_repo: Path,
    ) -> None:
        """Reverting a valid commit succeeds."""
        import re

        (git_repo / "revertme.txt").write_text("will be reverted\n")
        await _run_git(str(git_repo), "add", "revertme.txt")
        commit_output = await _run_git(str(git_repo), "commit", "-m", "add revertme")
        match = re.search(r"\[[\w/.\-]+ ([0-9a-f]+)\]", commit_output)
        assert match, f"Could not extract commit hash from: {commit_output}"
        commit_hash = match.group(1)

        result = await git_operations.revert(workspace_session, commit_hash)

        assert result.success is True

    async def test_revert_nonexistent_commit_returns_error(
        self, git_operations: GitOperationsPort, workspace_session: WorkspaceSession
    ) -> None:
        """Reverting a non-existent commit hash returns failure."""
        result = await git_operations.revert(workspace_session, "0000deadbeef")

        assert result.success is False
        assert result.error is not None
