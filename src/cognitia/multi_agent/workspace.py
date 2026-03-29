"""ExecutionWorkspace protocol and LocalWorkspace implementation."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import uuid
from typing import Any, Protocol, runtime_checkable

from cognitia.multi_agent.workspace_types import (
    WorkspaceHandle,
    WorkspaceSpec,
    WorkspaceStrategy,
)


@runtime_checkable
class ExecutionWorkspace(Protocol):
    """Isolated work environment per agent+task. ISP: 3 methods."""

    async def create(
        self, spec: WorkspaceSpec, agent_id: str, task_id: str
    ) -> WorkspaceHandle: ...

    async def cleanup(self, handle: WorkspaceHandle) -> bool: ...

    async def list_active(self) -> list[WorkspaceHandle]: ...


_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_slug(value: str, name: str) -> None:
    """Validate that *value* is a safe filesystem slug.

    Allows alphanumeric characters, dashes, and underscores.
    Length 1-64 chars, must start with alphanumeric.
    Rejects path traversal, slashes, and other special characters.
    """
    if not _SLUG_RE.match(value):
        raise ValueError(
            f"Invalid {name}: must be alphanumeric/dash/underscore, "
            f"1-64 chars, start with alphanumeric, got: {value!r}"
        )


class LocalWorkspace:
    """File-system backed workspace manager.

    Supports three isolation strategies:
    - TEMP_DIR: creates a fresh temporary directory
    - GIT_WORKTREE: creates a git worktree + branch
    - COPY: copies base_path into a temp location
    """

    def __init__(self, *, event_bus: Any | None = None) -> None:
        self._active: dict[str, WorkspaceHandle] = {}
        self._lock = asyncio.Lock()
        self._bus = event_bus

    # --- public API ---

    async def create(
        self, spec: WorkspaceSpec, agent_id: str, task_id: str
    ) -> WorkspaceHandle:
        """Create an isolated workspace according to *spec*."""
        _validate_slug(agent_id, "agent_id")
        _validate_slug(task_id, "task_id")
        path, branch_name = await self._create_path(spec, agent_id, task_id)
        workspace_id = uuid.uuid4().hex[:12]
        handle = WorkspaceHandle(
            workspace_id=workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            path=path,
            strategy=spec.strategy,
            branch_name=branch_name,
        )
        async with self._lock:
            self._active[workspace_id] = handle
        await self._emit("workspace.created", handle)
        return handle

    async def cleanup(self, handle: WorkspaceHandle) -> bool:
        """Remove the workspace from disk and tracking.

        Returns True if the handle was active, False otherwise.
        """
        async with self._lock:
            was_active = handle.workspace_id in self._active
            if was_active:
                del self._active[handle.workspace_id]

        if not was_active:
            return False

        await self._cleanup_path(handle)
        await self._emit("workspace.cleaned", handle)
        return True

    async def list_active(self) -> list[WorkspaceHandle]:
        """Return all currently active workspace handles."""
        async with self._lock:
            return list(self._active.values())

    # --- private helpers ---

    async def _create_path(
        self, spec: WorkspaceSpec, agent_id: str, task_id: str
    ) -> tuple[str, str | None]:
        if spec.strategy == WorkspaceStrategy.TEMP_DIR:
            return await self._create_temp_dir(agent_id, task_id), None
        if spec.strategy == WorkspaceStrategy.GIT_WORKTREE:
            return await self._create_git_worktree(spec, agent_id, task_id)
        if spec.strategy == WorkspaceStrategy.COPY:
            return await self._create_copy(spec, agent_id, task_id), None
        msg = f"Unknown strategy: {spec.strategy}"
        raise ValueError(msg)

    async def _create_temp_dir(self, agent_id: str, task_id: str) -> str:
        return await asyncio.to_thread(
            tempfile.mkdtemp, prefix=f"cognitia_{agent_id}_{task_id}_"
        )

    async def _create_git_worktree(
        self, spec: WorkspaceSpec, agent_id: str, task_id: str
    ) -> tuple[str, str]:
        branch_name = spec.branch_template.format(
            agent_name=agent_id, task_id=task_id
        )
        target_path = os.path.join(
            spec.base_path, ".worktrees", f"{agent_id}_{task_id}"
        )
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            spec.base_path,
            "worktree",
            "add",
            target_path,
            "-b",
            branch_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"git worktree add failed: {stderr.decode()}"
            raise RuntimeError(msg)
        return target_path, branch_name

    async def _create_copy(
        self, spec: WorkspaceSpec, agent_id: str, task_id: str
    ) -> str:
        target_path = os.path.join(
            tempfile.gettempdir(),
            f"cognitia_copy_{agent_id}_{task_id}_{uuid.uuid4().hex[:8]}",
        )
        await asyncio.to_thread(shutil.copytree, spec.base_path, target_path)
        return target_path

    async def _cleanup_path(self, handle: WorkspaceHandle) -> None:
        if handle.strategy in (WorkspaceStrategy.TEMP_DIR, WorkspaceStrategy.COPY):
            await asyncio.to_thread(shutil.rmtree, handle.path, True)
        elif handle.strategy == WorkspaceStrategy.GIT_WORKTREE:
            await self._cleanup_git_worktree(handle)

    async def _cleanup_git_worktree(self, handle: WorkspaceHandle) -> None:
        # Derive the main repo path: handle.path is inside <repo>/.worktrees/<name>
        repo_path = os.path.dirname(os.path.dirname(handle.path))

        # Remove the worktree (must run from the main repo)
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "worktree",
            "remove",
            handle.path,
            "--force",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Best-effort branch deletion -- use the exact branch created for the worktree
        if handle.branch_name is not None:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                repo_path,
                "branch",
                "-D",
                handle.branch_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            # ignore errors -- best effort

    async def _emit(self, event: str, handle: WorkspaceHandle) -> None:
        if self._bus is not None and hasattr(self._bus, "emit"):
            try:
                await self._bus.emit(event, {"workspace_id": handle.workspace_id})
            except Exception:  # noqa: BLE001
                pass  # observability must not break the workspace
