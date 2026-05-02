"""Unit tests for WorktreeOrchestrator lifecycle management."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from swarmline.multi_agent.worktree_orchestrator import WorktreeOrchestrator
from swarmline.multi_agent.worktree_strategy import (
    FactoryWorktreeStrategy,
    MergeResult,
    WorktreePolicy,
)
from swarmline.multi_agent.workspace_types import WorkspaceHandle, WorkspaceStrategy


# --- Fixtures ---


def _make_handle(
    *,
    workspace_id: str = "ws001",
    agent_id: str = "dev1",
    task_id: str = "t1",
    path: str = "/repo/.worktrees/dev1_t1",
    strategy: WorkspaceStrategy = WorkspaceStrategy.GIT_WORKTREE,
    branch_name: str | None = "factory/goal-a/dev1",
) -> WorkspaceHandle:
    return WorkspaceHandle(
        workspace_id=workspace_id,
        agent_id=agent_id,
        task_id=task_id,
        path=path,
        strategy=strategy,
        branch_name=branch_name,
    )


@pytest.fixture
def mock_workspace() -> AsyncMock:
    ws = AsyncMock()
    ws.create = AsyncMock(return_value=_make_handle())
    ws.cleanup = AsyncMock(return_value=True)
    ws.list_active = AsyncMock(return_value=[])
    return ws


@pytest.fixture
def mock_event_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def policy() -> WorktreePolicy:
    return WorktreePolicy(
        strategy=FactoryWorktreeStrategy.PER_AGENT,
        base_path="/repo",
    )


@pytest.fixture
def none_policy() -> WorktreePolicy:
    return WorktreePolicy(
        strategy=FactoryWorktreeStrategy.NONE,
        base_path="/tmp",
    )


# --- Constructor tests ---


class TestWorktreeOrchestratorConstructor:
    def test_accepts_workspace_only(self, mock_workspace: AsyncMock) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        assert orch._workspace is mock_workspace

    def test_accepts_workspace_and_event_bus(
        self, mock_workspace: AsyncMock, mock_event_bus: AsyncMock
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace, event_bus=mock_event_bus)
        assert orch._bus is mock_event_bus


# --- create_workspace ---


class TestCreateWorkspace:
    async def test_delegates_to_execution_workspace(
        self, mock_workspace: AsyncMock, policy: WorktreePolicy
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        mock_workspace.create.assert_awaited_once()
        assert isinstance(handle, WorkspaceHandle)

    async def test_emits_worktree_created_event(
        self,
        mock_workspace: AsyncMock,
        mock_event_bus: AsyncMock,
        policy: WorktreePolicy,
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace, event_bus=mock_event_bus)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        mock_event_bus.emit.assert_awaited()
        call_args = mock_event_bus.emit.call_args
        assert call_args[0][0] == "worktree:created"
        assert call_args[0][1]["workspace_id"] == handle.workspace_id

    async def test_none_strategy_uses_temp_dir(
        self, mock_workspace: AsyncMock, none_policy: WorktreePolicy
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        await orch.create_workspace(none_policy, agent_id="dev1", task_id="t1")
        call_args = mock_workspace.create.call_args
        spec = call_args[0][0]
        assert spec.strategy is WorkspaceStrategy.TEMP_DIR

    async def test_tracks_active_handle(
        self, mock_workspace: AsyncMock, policy: WorktreePolicy
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        assert handle.workspace_id in orch._active

    async def test_no_event_bus_does_not_fail(
        self, mock_workspace: AsyncMock, policy: WorktreePolicy
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        assert handle is not None


# --- merge_workspace ---


class TestMergeWorkspace:
    async def test_non_worktree_returns_failure(
        self, mock_workspace: AsyncMock
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = _make_handle(strategy=WorkspaceStrategy.TEMP_DIR, branch_name=None)
        result = await orch.merge_workspace(handle)
        assert isinstance(result, MergeResult)
        assert result.success is False
        assert result.error == "Not a git worktree"

    async def test_successful_merge(self, mock_workspace: AsyncMock) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = _make_handle()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await orch.merge_workspace(handle, target_branch="main")
        assert result.success is True
        assert result.source_branch == "factory/goal-a/dev1"
        assert result.target_branch == "main"

    async def test_merge_conflict_returns_failure(
        self, mock_workspace: AsyncMock
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = _make_handle()
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"", b"CONFLICT (content): Merge conflict in file.py\n")
        )
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await orch.merge_workspace(handle)
        assert result.success is False
        assert result.error is not None
        assert "file.py" in (result.conflicts or ())

    async def test_emits_merge_started_and_completed(
        self, mock_workspace: AsyncMock, mock_event_bus: AsyncMock
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace, event_bus=mock_event_bus)
        handle = _make_handle()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await orch.merge_workspace(handle)
        event_types = [call[0][0] for call in mock_event_bus.emit.call_args_list]
        assert "worktree:merge_started" in event_types
        assert "worktree:merge_completed" in event_types

    async def test_emits_merge_failed_on_conflict(
        self, mock_workspace: AsyncMock, mock_event_bus: AsyncMock
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace, event_bus=mock_event_bus)
        handle = _make_handle()
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"CONFLICT\n"))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await orch.merge_workspace(handle)
        event_types = [call[0][0] for call in mock_event_bus.emit.call_args_list]
        assert "worktree:merge_started" in event_types
        assert "worktree:merge_failed" in event_types


# --- cleanup_workspace ---


class TestCleanupWorkspace:
    async def test_delegates_to_execution_workspace(
        self, mock_workspace: AsyncMock, policy: WorktreePolicy
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        result = await orch.cleanup_workspace(handle)
        mock_workspace.cleanup.assert_awaited_once_with(handle)
        assert result is True

    async def test_emits_worktree_cleaned_event(
        self,
        mock_workspace: AsyncMock,
        mock_event_bus: AsyncMock,
        policy: WorktreePolicy,
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace, event_bus=mock_event_bus)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        mock_event_bus.emit.reset_mock()
        await orch.cleanup_workspace(handle)
        call_args = mock_event_bus.emit.call_args
        assert call_args[0][0] == "worktree:cleaned"

    async def test_removes_from_active_tracking(
        self, mock_workspace: AsyncMock, policy: WorktreePolicy
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        assert handle.workspace_id in orch._active
        await orch.cleanup_workspace(handle)
        assert handle.workspace_id not in orch._active


# --- scan_orphans ---


class TestScanOrphans:
    async def test_finds_orphan_worktrees(self, mock_workspace: AsyncMock) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        porcelain_output = (
            b"worktree /repo\n"
            b"HEAD abc123\n"
            b"branch refs/heads/main\n"
            b"\n"
            b"worktree /repo/.worktrees/orphan1\n"
            b"HEAD def456\n"
            b"branch refs/heads/factory/goal-a/dev1\n"
            b"\n"
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(porcelain_output, b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            orphans = await orch.scan_orphans("/repo")
        # main worktree is never an orphan; the second worktree is not in _active
        assert "/repo/.worktrees/orphan1" in orphans

    async def test_ignores_unmanaged_worktrees(self, mock_workspace: AsyncMock) -> None:
        """Manual worktrees are not Swarmline orphans after process restart."""
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        porcelain_output = (
            b"worktree /repo\n"
            b"HEAD abc123\n"
            b"branch refs/heads/main\n"
            b"\n"
            b"worktree /repo/manual-worktree\n"
            b"HEAD def456\n"
            b"branch refs/heads/feature/manual\n"
            b"\n"
            b"worktree /repo/.worktrees/manual-inside\n"
            b"HEAD fedcba\n"
            b"branch refs/heads/main\n"
            b"\n"
            b"worktree /repo/.worktrees/managed-factory\n"
            b"HEAD 111111\n"
            b"branch refs/heads/factory/goal-a/dev1\n"
            b"\n"
            b"worktree /repo/.worktrees/managed-swarmline\n"
            b"HEAD 222222\n"
            b"branch refs/heads/swarmline/dev1/task1\n"
            b"\n"
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(porcelain_output, b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            orphans = await orch.scan_orphans("/repo")

        assert "/repo/manual-worktree" not in orphans
        assert "/repo/.worktrees/manual-inside" not in orphans
        assert orphans == [
            "/repo/.worktrees/managed-factory",
            "/repo/.worktrees/managed-swarmline",
        ]

    async def test_active_worktree_not_orphan(
        self, mock_workspace: AsyncMock, policy: WorktreePolicy
    ) -> None:
        handle = _make_handle(path="/repo/.worktrees/dev1_t1")
        mock_workspace.create = AsyncMock(return_value=handle)
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        await orch.create_workspace(policy, agent_id="dev1", task_id="t1")

        porcelain_output = (
            b"worktree /repo\n"
            b"HEAD abc123\n"
            b"branch refs/heads/main\n"
            b"\n"
            b"worktree /repo/.worktrees/dev1_t1\n"
            b"HEAD def456\n"
            b"branch refs/heads/factory/goal-a/dev1\n"
            b"\n"
        )
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(porcelain_output, b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            orphans = await orch.scan_orphans("/repo")
        assert "/repo/.worktrees/dev1_t1" not in orphans


# --- cleanup_orphans ---


class TestCleanupOrphans:
    async def test_removes_orphan_worktrees(self, mock_workspace: AsyncMock) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        porcelain_output = (
            b"worktree /repo\n"
            b"HEAD abc123\n"
            b"branch refs/heads/main\n"
            b"\n"
            b"worktree /repo/.worktrees/orphan1\n"
            b"HEAD def456\n"
            b"branch refs/heads/factory/orphan\n"
            b"\n"
        )
        mock_scan_proc = AsyncMock()
        mock_scan_proc.returncode = 0
        mock_scan_proc.communicate = AsyncMock(return_value=(porcelain_output, b""))
        mock_remove_proc = AsyncMock()
        mock_remove_proc.returncode = 0
        mock_remove_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=[mock_scan_proc, mock_remove_proc],
        ):
            count = await orch.cleanup_orphans("/repo")
        assert count == 1


# --- Full lifecycle ---


class TestFullLifecycle:
    async def test_create_merge_cleanup(
        self,
        mock_workspace: AsyncMock,
        mock_event_bus: AsyncMock,
        policy: WorktreePolicy,
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace, event_bus=mock_event_bus)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        assert handle.workspace_id in orch._active

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            merge_result = await orch.merge_workspace(handle)
        assert merge_result.success is True

        await orch.cleanup_workspace(handle)
        assert handle.workspace_id not in orch._active

    async def test_create_cleanup_without_merge(
        self, mock_workspace: AsyncMock, policy: WorktreePolicy
    ) -> None:
        orch = WorktreeOrchestrator(workspace=mock_workspace)
        handle = await orch.create_workspace(policy, agent_id="dev1", task_id="t1")
        result = await orch.cleanup_workspace(handle)
        assert result is True
        assert handle.workspace_id not in orch._active
