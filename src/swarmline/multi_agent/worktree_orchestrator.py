"""WorktreeOrchestrator — lifecycle management for factory worktrees.

Bridges WorktreePolicy to ExecutionWorkspace, managing create/merge/cleanup
with event emission at each step.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from swarmline.multi_agent.worktree_strategy import MergeResult, WorktreePolicy
from swarmline.multi_agent.workspace import ExecutionWorkspace
from swarmline.multi_agent.workspace_types import WorkspaceHandle, WorkspaceStrategy

_CONFLICT_RE = re.compile(r"CONFLICT.*?:\s+.*?in\s+(\S+)")
_MANAGED_BRANCH_PREFIXES = ("refs/heads/factory/", "refs/heads/swarmline/")


class WorktreeOrchestrator:
    """Manages the full worktree lifecycle: create -> merge -> cleanup.

    Delegates actual workspace creation to an ExecutionWorkspace implementation
    and emits events via an optional EventBus.
    """

    def __init__(
        self,
        workspace: ExecutionWorkspace,
        *,
        event_bus: Any | None = None,
    ) -> None:
        self._workspace = workspace
        self._bus = event_bus
        self._active: dict[str, WorkspaceHandle] = {}

    # --- public API ---

    async def create_workspace(
        self,
        policy: WorktreePolicy,
        agent_id: str,
        task_id: str,
        context: str = "",
    ) -> WorkspaceHandle:
        """Create an isolated workspace according to *policy*."""
        spec = policy.to_workspace_spec(
            agent_id=agent_id, task_id=task_id, context=context
        )
        handle = await self._workspace.create(spec, agent_id, task_id)
        self._active[handle.workspace_id] = handle
        await self._emit(
            "worktree:created",
            {"workspace_id": handle.workspace_id, "agent_id": agent_id},
        )
        return handle

    async def merge_workspace(
        self,
        handle: WorkspaceHandle,
        target_branch: str = "main",
    ) -> MergeResult:
        """Forward-merge *target_branch* into the worktree branch for conflict resolution.

        After this call, the worktree branch contains all changes from target_branch
        merged with the worktree's work. The caller (factory lead) is responsible for
        the final merge of the worktree branch into target via the main repo:
        ``git -C <main_repo> merge <source_branch>``
        """
        if handle.strategy != WorkspaceStrategy.GIT_WORKTREE:
            return MergeResult(
                success=False,
                source_branch=handle.branch_name or "",
                target_branch=target_branch,
                error="Not a git worktree",
            )

        await self._emit(
            "worktree:merge_started",
            {
                "workspace_id": handle.workspace_id,
                "source_branch": handle.branch_name or "",
                "target_branch": target_branch,
            },
        )

        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            handle.path,
            "merge",
            target_branch,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode == 0:
            result = MergeResult(
                success=True,
                source_branch=handle.branch_name or "",
                target_branch=target_branch,
            )
            await self._emit(
                "worktree:merge_completed",
                {
                    "workspace_id": handle.workspace_id,
                },
            )
            return result

        stderr_text = stderr.decode()
        conflicts = tuple(m.group(1) for m in _CONFLICT_RE.finditer(stderr_text))
        result = MergeResult(
            success=False,
            source_branch=handle.branch_name or "",
            target_branch=target_branch,
            error=stderr_text.strip() or "merge failed",
            conflicts=conflicts,
        )
        await self._emit(
            "worktree:merge_failed",
            {
                "workspace_id": handle.workspace_id,
                "error": result.error,
            },
        )
        return result

    async def cleanup_workspace(self, handle: WorkspaceHandle) -> bool:
        """Clean up a workspace and remove it from active tracking."""
        result = await self._workspace.cleanup(handle)
        self._active.pop(handle.workspace_id, None)
        await self._emit("worktree:cleaned", {"workspace_id": handle.workspace_id})
        return result

    async def scan_orphans(self, base_path: str) -> list[str]:
        """Find worktrees not tracked in active handles."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            base_path,
            "worktree",
            "list",
            "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        active_paths = {os.path.abspath(h.path) for h in self._active.values()}
        main_path = os.path.abspath(base_path)
        managed_root = os.path.join(main_path, ".worktrees")
        orphans: list[str] = []
        current_path: str | None = None
        current_branch: str | None = None

        def flush_entry() -> None:
            if current_path is None:
                return
            path = os.path.abspath(current_path)
            if path == main_path or path in active_paths:
                return
            try:
                if os.path.commonpath([managed_root, path]) != managed_root:
                    return
            except ValueError:
                return
            if not current_branch or not current_branch.startswith(
                _MANAGED_BRANCH_PREFIXES
            ):
                return
            orphans.append(current_path)

        for line in stdout.decode().splitlines():
            if not line:
                flush_entry()
                current_path = None
                current_branch = None
                continue
            if line.startswith("worktree "):
                flush_entry()
                current_path = line[len("worktree ") :]
                current_branch = None
            elif line.startswith("branch "):
                current_branch = line[len("branch ") :]
        flush_entry()

        return orphans

    async def cleanup_orphans(self, base_path: str) -> int:
        """Remove orphan worktrees. Returns count removed."""
        orphans = await self.scan_orphans(base_path)
        removed = 0
        for path in orphans:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                base_path,
                "worktree",
                "remove",
                path,
                "--force",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                removed += 1
        return removed

    # --- private ---

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self._bus is not None and hasattr(self._bus, "emit"):
            try:
                await self._bus.emit(event_type, data)
            except Exception:  # noqa: BLE001
                pass  # observability must not break the orchestrator
