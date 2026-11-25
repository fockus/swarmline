"""Integration tests -- self-verification exposure (code-agent-facade plan,
Stage 4).

`run_verification` is already wired (Stage 3, workspace tools); Stage 4
exposes `CodeAgent(verify_command=...)` as a facade-level override of the
DEFAULT test command used when the caller (the LLM) omits an explicit
`command` argument. `WorkspaceVerificationRunner`'s own command-injection
guard (shell-metacharacter blocklist) is reused unchanged -- only the
DEFAULT changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swarmline.code_agent import CodeAgent
from swarmline.orchestration.verification_types import (
    CheckDetail,
    VerificationResult,
    VerificationStatus,
)
from swarmline.workspace.conflict import ConflictDetector
from swarmline.workspace.git_local import LocalGitOperations
from swarmline.workspace.mutation import MutationPolicy, OwnChangesTracker
from swarmline.workspace.tools import create_workspace_tools
from swarmline.workspace.types import MutationMode, WorkspaceSession

pytestmark = pytest.mark.asyncio


class _FakeVerificationRunner:
    """Minimal `VerificationRunnerPort` double -- returns a scripted result
    regardless of the command it is asked to run."""

    def __init__(self, result: VerificationResult) -> None:
        self._result = result

    async def run_tests(
        self, session: WorkspaceSession, command: str | None = None
    ) -> VerificationResult:
        return self._result

    async def run_lint(
        self, session: WorkspaceSession, command: str | None = None
    ) -> VerificationResult:
        return self._result


def _build_workspace_executors(tmp_path: Path, runner: Any) -> dict[str, Any]:
    session = WorkspaceSession.create(
        session_id="s1",
        repo_root=str(tmp_path),
        branch="unknown",
        mutation_mode=MutationMode.AUTO_APPLY,
    )
    _specs, executors = create_workspace_tools(
        LocalGitOperations(),
        MutationPolicy(),
        OwnChangesTracker(),
        ConflictDetector(),
        runner,
        session,
    )
    return executors


class TestRunVerificationToolShape:
    async def test_run_verification_tool_executes_tests_via_fake_runner(
        self, tmp_path: Path
    ) -> None:
        fake_result = VerificationResult(
            status=VerificationStatus.PASS,
            checks=(
                CheckDetail(
                    name="tests", status=VerificationStatus.PASS, message="3 passed"
                ),
            ),
            summary="tests passed",
        )
        executors = _build_workspace_executors(
            tmp_path, _FakeVerificationRunner(fake_result)
        )

        result = json.loads(
            await executors["run_verification"]({"check_type": "tests"})
        )

        assert result == {
            "status": "pass",
            "checks": [{"name": "tests", "status": "pass", "message": "3 passed"}],
            "summary": "tests passed",
            "passed": True,
        }

    async def test_run_verification_reports_fail_status(self, tmp_path: Path) -> None:
        fake_result = VerificationResult(
            status=VerificationStatus.FAIL,
            checks=(
                CheckDetail(
                    name="tests", status=VerificationStatus.FAIL, message="1 failed"
                ),
            ),
            summary="tests failed",
        )
        executors = _build_workspace_executors(
            tmp_path, _FakeVerificationRunner(fake_result)
        )

        result = json.loads(
            await executors["run_verification"]({"check_type": "tests"})
        )

        assert result["status"] == "fail"
        assert result["passed"] is False


class TestVerifyCommandOverride:
    async def test_verify_command_override_forwarded(self, tmp_path: Path) -> None:
        """The override reaches the REAL runner end-to-end via a trivial,
        deterministic shell command -- no fakes needed to prove forwarding."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), verify_command="echo forwarded-ok"
        )

        result = json.loads(
            await agent._capability_executors["run_verification"](
                {"check_type": "tests"}
            )
        )

        assert result["passed"] is True
        assert "forwarded-ok" in result["checks"][0]["message"]

    async def test_explicit_command_wins_over_verify_command_override(
        self, tmp_path: Path
    ) -> None:
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), verify_command="echo should-not-run"
        )

        result = json.loads(
            await agent._capability_executors["run_verification"](
                {"check_type": "tests", "command": "echo explicit-wins"}
            )
        )

        assert "explicit-wins" in result["checks"][0]["message"]
        assert "should-not-run" not in result["checks"][0]["message"]

    async def test_verify_command_override_does_not_apply_to_lint(
        self, tmp_path: Path
    ) -> None:
        """`verify_command` overrides the DEFAULT TEST command only -- lint
        keeps its own default (`ruff check .`), never silently redirected to
        the test override."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), verify_command="echo forwarded-ok"
        )

        result = json.loads(
            await agent._capability_executors["run_verification"](
                {"check_type": "lint"}
            )
        )

        assert "forwarded-ok" not in result["checks"][0]["message"]


class TestVerificationCommandValidation:
    async def test_run_verification_blocks_shell_metacharacters(
        self, tmp_path: Path
    ) -> None:
        """Existing `WorkspaceVerificationRunner` command-injection guard is
        untouched by the `verify_command` wiring."""
        agent = CodeAgent(model="sonnet", cwd=str(tmp_path))

        result = json.loads(
            await agent._capability_executors["run_verification"](
                {"check_type": "tests", "command": "pytest; rm -rf /"}
            )
        )

        assert result["passed"] is False
        assert "forbidden shell metacharacters" in result["checks"][0]["message"]

    async def test_verify_command_override_with_shell_metacharacters_is_blocked(
        self, tmp_path: Path
    ) -> None:
        """The SAME guard applies to the Stage 4 `verify_command=...`
        override path (omitted `command`, `check_type="tests"`) -- the
        override substitutes into the same validated `command` argument, it
        does not bypass `_validate_command`."""
        agent = CodeAgent(
            model="sonnet", cwd=str(tmp_path), verify_command="pytest; rm -rf /"
        )

        result = json.loads(
            await agent._capability_executors["run_verification"](
                {"check_type": "tests"}
            )
        )

        assert result["passed"] is False
        assert "forbidden shell metacharacters" in result["checks"][0]["message"]
