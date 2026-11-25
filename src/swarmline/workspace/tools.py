"""Workspace tool factory — agent-callable tools for git/verification.

Creates 6 tools: git_diff, git_status, git_commit, git_branch_create,
git_revert, run_verification. All return JSON-serialized results.
Errors (MutationPolicyViolation, ConflictError) are caught and returned
as structured error dicts — never raised.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from swarmline.runtime.types import ToolSpec
from swarmline.workspace.protocols import (
    ConflictDetectorPort,
    GitOperationsPort,
    MutationPolicyPort,
    OwnChangesTrackerPort,
    VerificationRunnerPort,
)
from swarmline.workspace.types import (
    GitOperationResult,
    MutationPolicyViolation,
    WorkspaceSession,
)

# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

_GIT_DIFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}

_GIT_STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}

_GIT_COMMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "Commit message"},
    },
    "required": ["message"],
}

_GIT_BRANCH_CREATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Branch name"},
    },
    "required": ["name"],
}

_GIT_REVERT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "commit_hash": {"type": "string", "description": "Commit hash to revert"},
    },
    "required": ["commit_hash"],
}

_RUN_VERIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "check_type": {
            "type": "string",
            "enum": ["tests", "lint"],
            "description": "Type of verification to run",
        },
        "command": {
            "type": "string",
            "description": "Custom command (optional, uses default if omitted)",
        },
    },
    "required": ["check_type"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result_to_json(result: GitOperationResult) -> str:
    """Serialize GitOperationResult to JSON string."""
    return json.dumps(
        {
            "success": result.success,
            "output": result.output,
            "changed_files": list(result.changed_files),
            "error": result.error,
            "operation": result.operation,
        }
    )


def _error_json(error_type: str, message: str) -> str:
    """Create a structured error JSON response."""
    return json.dumps(
        {
            "status": "error",
            "error_type": error_type,
            "message": message,
        }
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_workspace_tools(
    git_ops: GitOperationsPort,
    mutation_policy: MutationPolicyPort,
    tracker: OwnChangesTrackerPort,
    conflict_detector: ConflictDetectorPort,
    verification_runner: VerificationRunnerPort,
    session: WorkspaceSession,
) -> tuple[dict[str, ToolSpec], dict[str, Callable[..., Any]]]:
    """Create 6 workspace tools for agent use.

    Returns (specs dict, executors dict) matching the builtin tools pattern.
    """
    specs: dict[str, ToolSpec] = {}
    executors: dict[str, Callable[..., Any]] = {}

    # 1. git_diff
    async def _git_diff(args: dict[str, Any]) -> str:
        result = await git_ops.diff(session)
        return _result_to_json(result)

    specs["git_diff"] = ToolSpec(
        name="git_diff",
        description="Show unified diff and list of changed files",
        parameters=_GIT_DIFF_SCHEMA,
    )
    executors["git_diff"] = _git_diff

    # 2. git_status
    async def _git_status(args: dict[str, Any]) -> str:
        result = await git_ops.status(session)
        return _result_to_json(result)

    specs["git_status"] = ToolSpec(
        name="git_status",
        description="Show staged, unstaged, and untracked files",
        parameters=_GIT_STATUS_SCHEMA,
    )
    executors["git_status"] = _git_status

    # 3. git_commit
    async def _git_commit(args: dict[str, Any]) -> str:
        message = args.get("message", "")
        if not message:
            return _error_json("validation", "Commit message is required")

        try:
            mutation_policy.check_write_allowed(session, "<commit>")
        except MutationPolicyViolation as exc:
            return _error_json("mutation_policy_violation", str(exc))

        result = await git_ops.commit(session, message)

        if result.success and result.output:
            tracker.record_commit(session.session_id, result.output)

        return _result_to_json(result)

    specs["git_commit"] = ToolSpec(
        name="git_commit",
        description="Create a git commit with the given message",
        parameters=_GIT_COMMIT_SCHEMA,
    )
    executors["git_commit"] = _git_commit

    # 4. git_branch_create
    async def _git_branch_create(args: dict[str, Any]) -> str:
        name = args.get("name", "")
        if not name:
            return _error_json("validation", "Branch name is required")
        result = await git_ops.branch_create(session, name)
        return _result_to_json(result)

    specs["git_branch_create"] = ToolSpec(
        name="git_branch_create",
        description="Create and switch to a new branch",
        parameters=_GIT_BRANCH_CREATE_SCHEMA,
    )
    executors["git_branch_create"] = _git_branch_create

    # 5. git_revert
    async def _git_revert(args: dict[str, Any]) -> str:
        commit_hash = args.get("commit_hash", "")
        if not commit_hash:
            return _error_json("validation", "Commit hash is required")

        if not tracker.is_own_commit(session.session_id, commit_hash):
            return _error_json(
                "not_own_commit",
                f"Cannot revert commit {commit_hash}: not an own commit",
            )

        result = await git_ops.revert(session, commit_hash)
        return _result_to_json(result)

    specs["git_revert"] = ToolSpec(
        name="git_revert",
        description="Revert an own commit by hash",
        parameters=_GIT_REVERT_SCHEMA,
    )
    executors["git_revert"] = _git_revert

    # 6. run_verification
    async def _run_verification(args: dict[str, Any]) -> str:
        check_type = args.get("check_type", "")
        command = args.get("command")

        if check_type == "tests":
            result = await verification_runner.run_tests(session, command)
        elif check_type == "lint":
            result = await verification_runner.run_lint(session, command)
        else:
            return _error_json(
                "validation",
                f"Invalid check_type: {check_type!r}. Must be 'tests' or 'lint'",
            )

        return json.dumps(
            {
                "status": result.status.value,
                "checks": [
                    {"name": c.name, "status": c.status.value, "message": c.message}
                    for c in result.checks
                ],
                "summary": result.summary,
                "passed": result.passed,
            }
        )

    specs["run_verification"] = ToolSpec(
        name="run_verification",
        description="Run tests or lint checks on the workspace",
        parameters=_RUN_VERIFICATION_SCHEMA,
    )
    executors["run_verification"] = _run_verification

    return specs, executors
