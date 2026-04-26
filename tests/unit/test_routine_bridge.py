"""Unit tests for RoutineBridge — scheduler-to-task-board bridge.

Tests use AsyncMock/Mock for scheduler and task_board dependencies.
TDD Red phase: tests written before implementation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from swarmline.daemon.routine_bridge import RoutineBridge, RoutineManager
from swarmline.daemon.routine_types import (
    Routine,
    RunStatus,
)
from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.multi_agent.task_types import TaskStatus


# --- Fixtures ---


@pytest.fixture
def mock_scheduler() -> Mock:
    sched = Mock()
    sched.every = Mock(return_value="task-name")
    sched.cancel = Mock(return_value=True)
    return sched


@pytest.fixture
def mock_task_board() -> AsyncMock:
    board = AsyncMock()
    board.list_tasks = AsyncMock(return_value=[])
    board.create_task = AsyncMock()
    return board


@pytest.fixture
def bridge(mock_scheduler: Mock, mock_task_board: AsyncMock) -> RoutineBridge:
    return RoutineBridge(mock_scheduler, mock_task_board)


@pytest.fixture
def sample_routine() -> Routine:
    return Routine(
        id="r1",
        name="Daily check",
        interval_seconds=60.0,
        agent_id="agent-1",
        goal_template="Check metrics",
        dedup_key="metrics-check",
    )


@pytest.fixture
def sample_routine_no_dedup() -> Routine:
    return Routine(
        id="r2",
        name="Always run",
        interval_seconds=30.0,
        agent_id="agent-2",
        goal_template="Run cleanup",
    )


# --- Tests ---


class TestRegister:
    async def test_register_stores_routine(
        self, bridge: RoutineBridge, sample_routine: Routine
    ) -> None:
        result = await bridge.register(sample_routine)

        assert result == "r1"
        routines = await bridge.list_routines()
        assert len(routines) == 1
        assert routines[0].id == "r1"
        assert routines[0].name == "Daily check"

    async def test_register_calls_scheduler_every(
        self,
        bridge: RoutineBridge,
        mock_scheduler: Mock,
        sample_routine: Routine,
    ) -> None:
        await bridge.register(sample_routine)

        mock_scheduler.every.assert_called_once()
        call_args = mock_scheduler.every.call_args
        assert call_args[0][0] == 60.0  # interval
        assert call_args[1]["name"] == "routine:r1"


class TestUnregister:
    async def test_unregister_removes_routine(
        self, bridge: RoutineBridge, sample_routine: Routine
    ) -> None:
        await bridge.register(sample_routine)

        result = await bridge.unregister("r1")

        assert result is True
        routines = await bridge.list_routines()
        assert len(routines) == 0

    async def test_unregister_calls_scheduler_cancel(
        self,
        bridge: RoutineBridge,
        mock_scheduler: Mock,
        sample_routine: Routine,
    ) -> None:
        await bridge.register(sample_routine)

        await bridge.unregister("r1")

        mock_scheduler.cancel.assert_called_once_with("routine:r1")

    async def test_unregister_missing_returns_false(
        self, bridge: RoutineBridge
    ) -> None:
        result = await bridge.unregister("nonexistent")

        assert result is False


class TestTrigger:
    async def test_trigger_creates_task_on_board(
        self,
        bridge: RoutineBridge,
        mock_task_board: AsyncMock,
        sample_routine: Routine,
    ) -> None:
        trigger = bridge._make_trigger(sample_routine)

        await trigger()

        mock_task_board.create_task.assert_called_once()
        created_task: GraphTaskItem = mock_task_board.create_task.call_args[0][0]
        assert created_task.title == "Check metrics"
        assert created_task.assignee_agent_id == "agent-1"
        assert created_task.metadata["routine_id"] == "r1"
        assert created_task.metadata["dedup_key"] == "metrics-check"

    async def test_trigger_dedup_skips_when_open_task_exists(
        self,
        bridge: RoutineBridge,
        mock_task_board: AsyncMock,
        sample_routine: Routine,
    ) -> None:
        existing_task = GraphTaskItem(
            id="existing-1",
            title="Check metrics",
            status=TaskStatus.TODO,
            metadata={"dedup_key": "metrics-check"},
        )
        mock_task_board.list_tasks = AsyncMock(return_value=[existing_task])

        trigger = bridge._make_trigger(sample_routine)
        await trigger()

        mock_task_board.create_task.assert_not_called()

    async def test_trigger_dedup_allows_when_only_done_tasks(
        self,
        bridge: RoutineBridge,
        mock_task_board: AsyncMock,
        sample_routine: Routine,
    ) -> None:
        done_task = GraphTaskItem(
            id="done-1",
            title="Check metrics",
            status=TaskStatus.DONE,
            metadata={"dedup_key": "metrics-check"},
        )
        mock_task_board.list_tasks = AsyncMock(return_value=[done_task])

        trigger = bridge._make_trigger(sample_routine)
        await trigger()

        mock_task_board.create_task.assert_called_once()

    async def test_trigger_no_dedup_creates_always(
        self,
        bridge: RoutineBridge,
        mock_task_board: AsyncMock,
        sample_routine_no_dedup: Routine,
    ) -> None:
        some_task = GraphTaskItem(
            id="some-1",
            title="Run cleanup",
            status=TaskStatus.TODO,
        )
        mock_task_board.list_tasks = AsyncMock(return_value=[some_task])

        trigger = bridge._make_trigger(sample_routine_no_dedup)
        await trigger()

        mock_task_board.create_task.assert_called_once()

    async def test_trigger_task_id_has_routine_prefix(
        self,
        bridge: RoutineBridge,
        mock_task_board: AsyncMock,
        sample_routine: Routine,
    ) -> None:
        trigger = bridge._make_trigger(sample_routine)
        await trigger()

        created_task: GraphTaskItem = mock_task_board.create_task.call_args[0][0]
        assert created_task.id.startswith("routine-r1-")


class TestGetRuns:
    async def test_get_runs_returns_history(
        self,
        bridge: RoutineBridge,
        mock_task_board: AsyncMock,
        sample_routine: Routine,
    ) -> None:
        trigger = bridge._make_trigger(sample_routine)
        await trigger()

        runs = await bridge.get_runs("r1")

        assert len(runs) == 1
        assert runs[0].routine_id == "r1"
        assert runs[0].status == RunStatus.CREATED
        assert runs[0].task_id is not None

    async def test_get_runs_records_skipped_dedup(
        self,
        bridge: RoutineBridge,
        mock_task_board: AsyncMock,
        sample_routine: Routine,
    ) -> None:
        existing_task = GraphTaskItem(
            id="existing-1",
            title="Check metrics",
            status=TaskStatus.IN_PROGRESS,
            metadata={"dedup_key": "metrics-check"},
        )
        mock_task_board.list_tasks = AsyncMock(return_value=[existing_task])

        trigger = bridge._make_trigger(sample_routine)
        await trigger()

        runs = await bridge.get_runs("r1")
        assert len(runs) == 1
        assert runs[0].status == RunStatus.SKIPPED_DEDUP
        assert runs[0].task_id is None

    async def test_get_runs_empty_for_unknown_routine(
        self, bridge: RoutineBridge
    ) -> None:
        runs = await bridge.get_runs("unknown")
        assert runs == []


class TestProtocol:
    def test_protocol_shape(self, bridge: RoutineBridge) -> None:
        assert isinstance(bridge, RoutineManager)
