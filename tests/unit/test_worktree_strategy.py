"""Unit tests for FactoryWorktreeStrategy, WorktreePolicy, MergeResult."""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.multi_agent.worktree_strategy import (
    FactoryWorktreeStrategy,
    MergeResult,
    WorktreePolicy,
)
from swarmline.multi_agent.workspace_types import WorkspaceSpec, WorkspaceStrategy


# --- FactoryWorktreeStrategy enum ---


class TestFactoryWorktreeStrategyEnum:
    def test_none_value(self) -> None:
        assert FactoryWorktreeStrategy.NONE.value == "none"

    def test_per_graph_value(self) -> None:
        assert FactoryWorktreeStrategy.PER_GRAPH.value == "per_graph"

    def test_per_sprint_value(self) -> None:
        assert FactoryWorktreeStrategy.PER_SPRINT.value == "per_sprint"

    def test_per_agent_value(self) -> None:
        assert FactoryWorktreeStrategy.PER_AGENT.value == "per_agent"

    def test_is_str_enum(self) -> None:
        assert issubclass(FactoryWorktreeStrategy, str)

    def test_member_count_is_four(self) -> None:
        assert len(FactoryWorktreeStrategy) == 4

    def test_from_string_value(self) -> None:
        assert FactoryWorktreeStrategy("per_agent") is FactoryWorktreeStrategy.PER_AGENT


# --- WorktreePolicy frozen dataclass ---


class TestWorktreePolicy:
    def test_create_minimal(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        assert policy.strategy is FactoryWorktreeStrategy.PER_AGENT
        assert policy.base_path == "/repo"

    def test_default_branch_template(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        assert policy.branch_template == "factory/{context}/{agent}"

    def test_default_auto_merge_is_false(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        assert policy.auto_merge is False

    def test_default_cleanup_on_success_is_true(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        assert policy.cleanup_on_success is True

    def test_default_merge_target_is_main(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        assert policy.merge_target == "main"

    def test_frozen_cannot_assign(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.base_path = "/other"  # type: ignore[misc]

    def test_to_workspace_spec_per_agent_uses_git_worktree(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        spec = policy.to_workspace_spec(agent_id="dev1", task_id="t1")
        assert isinstance(spec, WorkspaceSpec)
        assert spec.strategy is WorkspaceStrategy.GIT_WORKTREE

    def test_to_workspace_spec_none_uses_temp_dir(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.NONE,
            base_path="/repo",
        )
        spec = policy.to_workspace_spec(agent_id="dev1", task_id="t1")
        assert spec.strategy is WorkspaceStrategy.TEMP_DIR

    def test_to_workspace_spec_per_graph_uses_git_worktree(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_GRAPH,
            base_path="/repo",
        )
        spec = policy.to_workspace_spec(agent_id="dev1", task_id="t1")
        assert spec.strategy is WorkspaceStrategy.GIT_WORKTREE

    def test_to_workspace_spec_per_sprint_uses_git_worktree(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_SPRINT,
            base_path="/repo",
        )
        spec = policy.to_workspace_spec(agent_id="dev1", task_id="t1")
        assert spec.strategy is WorkspaceStrategy.GIT_WORKTREE

    def test_to_workspace_spec_formats_branch_template(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
            branch_template="factory/{context}/{agent}",
        )
        spec = policy.to_workspace_spec(agent_id="dev1", task_id="t1", context="goal-a")
        assert spec.branch_template == "factory/goal-a/dev1"

    def test_to_workspace_spec_base_path_preserved(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/my/repo",
        )
        spec = policy.to_workspace_spec(agent_id="dev1", task_id="t1")
        assert spec.base_path == "/my/repo"

    def test_to_workspace_spec_empty_context_formats_correctly(self) -> None:
        policy = WorktreePolicy(
            strategy=FactoryWorktreeStrategy.PER_AGENT,
            base_path="/repo",
        )
        spec = policy.to_workspace_spec(agent_id="dev1", task_id="t1", context="")
        assert spec.branch_template == "factory//dev1"


# --- MergeResult frozen dataclass ---


class TestMergeResult:
    def test_success_result(self) -> None:
        result = MergeResult(
            success=True,
            source_branch="factory/goal-a/dev1",
            target_branch="main",
        )
        assert result.success is True
        assert result.source_branch == "factory/goal-a/dev1"
        assert result.target_branch == "main"
        assert result.error is None
        assert result.conflicts == ()

    def test_failure_result_with_error(self) -> None:
        result = MergeResult(
            success=False,
            source_branch="factory/goal-a/dev1",
            target_branch="main",
            error="Conflict in file.py",
        )
        assert result.success is False
        assert result.error == "Conflict in file.py"

    def test_failure_with_conflicts(self) -> None:
        result = MergeResult(
            success=False,
            source_branch="dev",
            target_branch="main",
            error="merge conflict",
            conflicts=("file_a.py", "file_b.py"),
        )
        assert result.conflicts == ("file_a.py", "file_b.py")

    def test_frozen_cannot_assign(self) -> None:
        result = MergeResult(
            success=True,
            source_branch="dev",
            target_branch="main",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.success = False  # type: ignore[misc]
