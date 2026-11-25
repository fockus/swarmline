"""Tests for workspace tools (create_workspace_tools factory).

Tests each tool handler with mock implementations.
Verifies JSON-serializable output, error handling, policy enforcement.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from swarmline.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)
from swarmline.workspace.conflict import ConflictDetector
from swarmline.workspace.mutation import MutationPolicy, OwnChangesTracker
from swarmline.workspace.tools import create_workspace_tools
from swarmline.workspace.types import (
    GitOperationResult,
    MutationMode,
    WorkspaceSession,
)

# ---------------------------------------------------------------------------
# Fake implementations
# ---------------------------------------------------------------------------


class FakeGitOperations:
    """Deterministic GitOperationsPort for testing."""

    def __init__(
        self,
        diff_result: GitOperationResult | None = None,
        status_result: GitOperationResult | None = None,
        commit_result: GitOperationResult | None = None,
        branch_result: GitOperationResult | None = None,
        revert_result: GitOperationResult | None = None,
    ) -> None:
        self._diff = diff_result or GitOperationResult(
            success=True,
            output="diff output",
            changed_files=("a.py",),
            operation="diff",
        )
        self._status = status_result or GitOperationResult(
            success=True,
            output='{"staged":[],"unstaged":[],"untracked":[]}',
            operation="status",
        )
        self._commit = commit_result or GitOperationResult(
            success=True, output="abc1234", operation="commit"
        )
        self._branch = branch_result or GitOperationResult(
            success=True, output="Switched to new branch", operation="branch_create"
        )
        self._revert = revert_result or GitOperationResult(
            success=True, output="Reverted", operation="revert"
        )

    async def diff(self, session: Any) -> GitOperationResult:
        return self._diff

    async def status(self, session: Any) -> GitOperationResult:
        return self._status

    async def commit(self, session: Any, message: str) -> GitOperationResult:
        return self._commit

    async def branch_create(self, session: Any, name: str) -> GitOperationResult:
        return self._branch

    async def revert(self, session: Any, commit_hash: str) -> GitOperationResult:
        return self._revert


class FakeVerificationRunner:
    """Deterministic VerificationRunnerPort for testing."""

    def __init__(self, pass_result: bool = True) -> None:
        self._status = (
            VerificationStatus.PASS if pass_result else VerificationStatus.FAIL
        )

    async def run_tests(
        self, session: Any, command: str | None = None
    ) -> VerificationResult:
        return VerificationResult(
            status=self._status,
            checks=(CheckDetail(name="tests", status=self._status, message="output"),),
            summary=f"Tests {'passed' if self._status == VerificationStatus.PASS else 'failed'}",
        )

    async def run_lint(
        self, session: Any, command: str | None = None
    ) -> VerificationResult:
        return VerificationResult(
            status=self._status,
            checks=(
                CheckDetail(name="lint", status=self._status, message="lint output"),
            ),
            summary=f"Lint {'passed' if self._status == VerificationStatus.PASS else 'failed'}",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auto_session() -> WorkspaceSession:
    return WorkspaceSession.create(
        session_id="sess-tools",
        repo_root="/tmp/repo",
        branch="main",
        mutation_mode=MutationMode.AUTO_APPLY,
    )


@pytest.fixture
def read_only_session() -> WorkspaceSession:
    return WorkspaceSession.create(
        session_id="sess-ro",
        repo_root="/tmp/repo",
        branch="main",
        mutation_mode=MutationMode.READ_ONLY,
    )


def _make_tools(
    session: WorkspaceSession,
    git_ops: FakeGitOperations | None = None,
    verification_runner: FakeVerificationRunner | None = None,
) -> dict[str, Any]:
    """Create workspace tools with given deps, return executors dict."""
    specs, executors = create_workspace_tools(
        git_ops=git_ops or FakeGitOperations(),
        mutation_policy=MutationPolicy(),
        tracker=OwnChangesTracker(),
        conflict_detector=ConflictDetector(),
        verification_runner=verification_runner or FakeVerificationRunner(),
        session=session,
    )
    return executors


# ---------------------------------------------------------------------------
# Tests: tool invocation
# ---------------------------------------------------------------------------


class TestWorkspaceToolsBasic:
    """Test each tool returns valid JSON output."""

    async def test_git_diff_returns_json(self, auto_session: WorkspaceSession) -> None:
        executors = _make_tools(auto_session)
        result = await executors["git_diff"]({})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["operation"] == "diff"
        assert "a.py" in parsed["changed_files"]

    async def test_git_status_returns_json(
        self, auto_session: WorkspaceSession
    ) -> None:
        executors = _make_tools(auto_session)
        result = await executors["git_status"]({})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["operation"] == "status"

    async def test_git_commit_auto_apply_returns_json(
        self, auto_session: WorkspaceSession
    ) -> None:
        executors = _make_tools(auto_session)
        result = await executors["git_commit"]({"message": "test commit"})
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["output"] == "abc1234"

    async def test_git_branch_create_returns_json(
        self, auto_session: WorkspaceSession
    ) -> None:
        executors = _make_tools(auto_session)
        result = await executors["git_branch_create"]({"name": "feat/new"})
        parsed = json.loads(result)
        assert parsed["success"] is True

    async def test_git_commit_read_only_returns_error_not_raises(
        self, read_only_session: WorkspaceSession
    ) -> None:
        """read_only session: git_commit returns error JSON, does not raise."""
        executors = _make_tools(read_only_session)
        result = await executors["git_commit"]({"message": "should fail"})
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error_type"] == "mutation_policy_violation"

    async def test_git_revert_non_own_commit_returns_error(
        self, auto_session: WorkspaceSession
    ) -> None:
        """Revert of unknown commit returns error JSON."""
        executors = _make_tools(auto_session)
        result = await executors["git_revert"]({"commit_hash": "deadbeef"})
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert parsed["error_type"] == "not_own_commit"

    async def test_run_verification_routes_to_tests(
        self, auto_session: WorkspaceSession
    ) -> None:
        executors = _make_tools(auto_session)
        result = await executors["run_verification"]({"check_type": "tests"})
        parsed = json.loads(result)
        assert parsed["status"] == "pass"
        assert parsed["checks"][0]["name"] == "tests"

    async def test_run_verification_routes_to_lint(
        self, auto_session: WorkspaceSession
    ) -> None:
        executors = _make_tools(auto_session)
        result = await executors["run_verification"]({"check_type": "lint"})
        parsed = json.loads(result)
        assert parsed["status"] == "pass"
        assert parsed["checks"][0]["name"] == "lint"

    async def test_run_verification_invalid_type_returns_error(
        self, auto_session: WorkspaceSession
    ) -> None:
        executors = _make_tools(auto_session)
        result = await executors["run_verification"]({"check_type": "bogus"})
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    async def test_all_tools_return_json_serializable_output(
        self, auto_session: WorkspaceSession
    ) -> None:
        """Every tool returns valid JSON string."""
        executors = _make_tools(auto_session)
        tool_args = {
            "git_diff": {},
            "git_status": {},
            "git_commit": {"message": "test"},
            "git_branch_create": {"name": "feat/x"},
            "git_revert": {"commit_hash": "deadbeef"},
            "run_verification": {"check_type": "tests"},
        }
        for tool_name, args in tool_args.items():
            result = await executors[tool_name](args)
            parsed = json.loads(result)
            assert isinstance(parsed, dict), f"{tool_name} did not return a JSON object"
