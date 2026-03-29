"""ExecutionWorkspace domain types — strategy, spec, handle."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class WorkspaceStrategy(str, Enum):
    """How to isolate the workspace filesystem."""

    TEMP_DIR = "temp_dir"
    GIT_WORKTREE = "git_worktree"
    COPY = "copy"


@dataclass(frozen=True)
class WorkspaceSpec:
    """What to create: strategy + base path + options."""

    strategy: WorkspaceStrategy
    base_path: str
    branch_template: str = "{agent_name}/{task_id}"
    auto_cleanup: bool = True


@dataclass(frozen=True)
class WorkspaceHandle:
    """Opaque handle returned after workspace creation."""

    workspace_id: str
    agent_id: str
    task_id: str
    path: str
    strategy: WorkspaceStrategy
    branch_name: str | None = None
    created_at: float = field(default_factory=time.time)
