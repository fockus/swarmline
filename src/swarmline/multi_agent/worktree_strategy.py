"""Factory-level worktree strategy types — enum, policy, merge result."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from swarmline.multi_agent.workspace_types import WorkspaceSpec, WorkspaceStrategy


class FactoryWorktreeStrategy(str, Enum):
    """How Code Factory isolates agent work via worktrees."""

    NONE = "none"
    PER_GRAPH = "per_graph"
    PER_SPRINT = "per_sprint"
    PER_AGENT = "per_agent"


_STRATEGY_MAP: dict[FactoryWorktreeStrategy, WorkspaceStrategy] = {
    FactoryWorktreeStrategy.NONE: WorkspaceStrategy.TEMP_DIR,
    FactoryWorktreeStrategy.PER_GRAPH: WorkspaceStrategy.GIT_WORKTREE,
    FactoryWorktreeStrategy.PER_SPRINT: WorkspaceStrategy.GIT_WORKTREE,
    FactoryWorktreeStrategy.PER_AGENT: WorkspaceStrategy.GIT_WORKTREE,
}


@dataclass(frozen=True)
class WorktreePolicy:
    """Describes how the factory should isolate agent workspaces."""

    strategy: FactoryWorktreeStrategy
    base_path: str
    branch_template: str = "factory/{context}/{agent}"
    auto_merge: bool = False
    cleanup_on_success: bool = True
    merge_target: str = "main"

    def to_workspace_spec(
        self,
        agent_id: str,
        task_id: str,
        context: str = "",
    ) -> WorkspaceSpec:
        """Convert policy to a WorkspaceSpec for ExecutionWorkspace.create()."""
        ws_strategy = _STRATEGY_MAP[self.strategy]
        branch = self.branch_template.format(context=context, agent=agent_id)
        return WorkspaceSpec(
            strategy=ws_strategy,
            base_path=self.base_path,
            branch_template=branch,
        )


@dataclass(frozen=True)
class MergeResult:
    """Outcome of merging a worktree branch into the target branch."""

    success: bool
    source_branch: str
    target_branch: str
    error: str | None = None
    conflicts: tuple[str, ...] = ()
