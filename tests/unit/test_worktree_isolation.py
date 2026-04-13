"""Tests for worktree isolation in ThinSubagentOrchestrator — TDD.

Covers: SubagentSpec.isolation field, worktree lifecycle (create/cleanup),
validation (invalid mode, missing base_path, max limit), stale cleanup,
and branch naming convention.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from swarmline.multi_agent.workspace_types import (
    WorkspaceHandle,
    WorkspaceSpec,
    WorkspaceStrategy,
)
from swarmline.orchestration.subagent_types import SubagentSpec


def _make_handle(n: int = 1) -> WorkspaceHandle:
    return WorkspaceHandle(
        workspace_id=f"ws-{n:03d}",
        agent_id="worker",
        task_id=f"task{n:04d}",
        path=f"/tmp/wt/{n}",
        strategy=WorkspaceStrategy.GIT_WORKTREE,
        branch_name=f"swarmline/worker/task{n:04d}",
    )


@pytest.fixture()
def mock_workspace() -> AsyncMock:
    """Mock ExecutionWorkspace — each create() returns a unique handle."""
    ws = AsyncMock()
    counter = {"n": 0}

    async def _create(*args: object, **kwargs: object) -> WorkspaceHandle:
        counter["n"] += 1
        return _make_handle(counter["n"])

    ws.create = AsyncMock(side_effect=_create)
    ws.cleanup = AsyncMock(return_value=True)
    ws.list_active = AsyncMock(return_value=[])
    return ws


@pytest.fixture()
def mock_runtime() -> AsyncMock:
    """Mock runtime whose run() returns immediately."""
    rt = AsyncMock()
    rt.run = AsyncMock(return_value="result")
    rt._cwd = None  # allow cwd injection
    return rt


def _make_orchestrator(
    mock_workspace: AsyncMock | None = None,
    mock_runtime: AsyncMock | None = None,
    **kwargs: object,
) -> object:
    from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

    defaults: dict[str, object] = {
        "max_concurrent": 10,
        "max_worktrees": 5,
        "base_path": "/repo",
    }
    defaults.update(kwargs)
    if mock_workspace is not None:
        defaults["workspace"] = mock_workspace

    orch = ThinSubagentOrchestrator(**defaults)  # type: ignore[arg-type]
    if mock_runtime is not None:
        orch._create_runtime = lambda spec: mock_runtime  # type: ignore[assignment]
    return orch


# ---------------------------------------------------------------------------
# SubagentSpec.isolation field
# ---------------------------------------------------------------------------


class TestSubagentSpecIsolation:
    def test_isolation_defaults_to_none(self) -> None:
        spec = SubagentSpec(name="w", system_prompt="p")
        assert spec.isolation is None

    def test_isolation_accepts_worktree(self) -> None:
        spec = SubagentSpec(name="w", system_prompt="p", isolation="worktree")
        assert spec.isolation == "worktree"

    def test_isolation_is_frozen(self) -> None:
        spec = SubagentSpec(name="w", system_prompt="p", isolation="worktree")
        with pytest.raises(AttributeError):
            spec.isolation = None  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Worktree lifecycle — create / cleanup
# ---------------------------------------------------------------------------


class TestWorktreeLifecycle:
    async def test_spawn_worktree_calls_workspace_create(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_workspace, mock_runtime)
        spec = SubagentSpec(name="worker", system_prompt="p", isolation="worktree")
        agent_id = await orch.spawn(spec, "do work")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        mock_workspace.create.assert_called_once()
        ws_spec: WorkspaceSpec = mock_workspace.create.call_args[0][0]
        assert ws_spec.strategy == WorkspaceStrategy.GIT_WORKTREE
        assert ws_spec.base_path == "/repo"
        assert "swarmline" in ws_spec.branch_template

    async def test_spawn_worktree_cleanup_on_success(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_workspace, mock_runtime)
        spec = SubagentSpec(name="worker", system_prompt="p", isolation="worktree")
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        mock_workspace.cleanup.assert_called_once()

    async def test_spawn_worktree_cleanup_on_runtime_error(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        mock_runtime.run = AsyncMock(side_effect=RuntimeError("boom"))
        orch = _make_orchestrator(mock_workspace, mock_runtime)
        spec = SubagentSpec(name="worker", system_prompt="p", isolation="worktree")
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        status = await orch.get_status(agent_id)  # type: ignore[union-attr]
        assert status.state == "failed"
        mock_workspace.cleanup.assert_called_once()

    async def test_spawn_worktree_cleanup_on_cancellation(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        async def slow_run(*_a: object, **_kw: object) -> str:
            await asyncio.sleep(10)
            return "done"

        mock_runtime.run = slow_run  # type: ignore[assignment]
        orch = _make_orchestrator(mock_workspace, mock_runtime)
        spec = SubagentSpec(name="worker", system_prompt="p", isolation="worktree")
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await asyncio.sleep(0.05)
        await orch.cancel(agent_id)  # type: ignore[union-attr]

        mock_workspace.cleanup.assert_called_once()

    async def test_none_isolation_skips_workspace(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_workspace, mock_runtime)
        spec = SubagentSpec(name="worker", system_prompt="p")  # isolation=None
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        mock_workspace.create.assert_not_called()
        mock_workspace.cleanup.assert_not_called()

    async def test_spawn_worktree_passes_cwd_to_runtime(
        self, mock_workspace: AsyncMock
    ) -> None:
        captured_cwd: list[str | None] = []

        class _FakeRuntime:
            def __init__(self) -> None:
                self._cwd: str | None = None

            async def run(self, task: str) -> str:
                captured_cwd.append(self._cwd)
                return "result"

        fake_rt = _FakeRuntime()
        orch = _make_orchestrator(mock_workspace)
        orch._create_runtime = lambda spec: fake_rt  # type: ignore[union-attr, assignment]

        spec = SubagentSpec(name="worker", system_prompt="p", isolation="worktree")
        agent_id = await orch.spawn(spec, "work")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        assert len(captured_cwd) == 1
        assert captured_cwd[0] is not None
        assert captured_cwd[0].startswith("/tmp/wt/")


# ---------------------------------------------------------------------------
# Validation — fail-fast on bad config
# ---------------------------------------------------------------------------


class TestWorktreeValidation:
    async def test_invalid_isolation_mode_raises_valueerror(self) -> None:
        orch = _make_orchestrator()
        spec = SubagentSpec(name="w", system_prompt="p", isolation="docker")
        with pytest.raises(ValueError, match="Invalid isolation mode"):
            await orch.spawn(spec, "t")  # type: ignore[union-attr]

    async def test_worktree_without_base_path_raises_valueerror(self) -> None:
        from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

        orch = ThinSubagentOrchestrator(max_concurrent=4)
        spec = SubagentSpec(name="w", system_prompt="p", isolation="worktree")
        with pytest.raises(ValueError, match="base_path"):
            await orch.spawn(spec, "t")

    async def test_max_worktrees_exceeded_raises_valueerror(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        async def slow_run(*_a: object, **_kw: object) -> str:
            await asyncio.sleep(10)
            return "done"

        mock_runtime.run = slow_run  # type: ignore[assignment]
        orch = _make_orchestrator(mock_workspace, mock_runtime, max_worktrees=2)
        spec = SubagentSpec(name="w", system_prompt="p", isolation="worktree")
        await orch.spawn(spec, "t1")  # type: ignore[union-attr]
        await orch.spawn(spec, "t2")  # type: ignore[union-attr]

        with pytest.raises(ValueError, match="Max worktrees"):
            await orch.spawn(spec, "t3")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Stale cleanup — fire-and-forget, once
# ---------------------------------------------------------------------------


class TestStaleCleanup:
    async def test_stale_cleanup_fires_once_on_first_worktree_spawn(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        cleanup_count = 0

        async def mock_cleanup() -> None:
            nonlocal cleanup_count
            cleanup_count += 1

        orch = _make_orchestrator(
            mock_workspace,
            mock_runtime,
            stale_cleanup_fn=mock_cleanup,
        )
        spec = SubagentSpec(name="w", system_prompt="p", isolation="worktree")
        await orch.spawn(spec, "t1")  # type: ignore[union-attr]
        await orch.spawn(spec, "t2")  # type: ignore[union-attr]

        # Give fire-and-forget task time to execute
        await asyncio.sleep(0.05)
        assert cleanup_count == 1


# ---------------------------------------------------------------------------
# Branch naming convention
# ---------------------------------------------------------------------------


class TestWorktreeBranchNaming:
    async def test_branch_template_uses_swarmline_prefix_and_agent_name(
        self, mock_workspace: AsyncMock, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_workspace, mock_runtime)
        spec = SubagentSpec(name="researcher", system_prompt="p", isolation="worktree")
        agent_id = await orch.spawn(spec, "research")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        ws_spec: WorkspaceSpec = mock_workspace.create.call_args[0][0]
        assert ws_spec.branch_template.startswith("swarmline/")
        # spec.name is passed as agent_name to workspace.create
        agent_name_arg = mock_workspace.create.call_args[0][1]
        assert agent_name_arg == "researcher"
