"""Integration test: RoutineBridge with real Scheduler + InMemoryGraphTaskBoard."""

from __future__ import annotations

import asyncio

import pytest

from swarmline.daemon.routine_bridge import RoutineBridge
from swarmline.daemon.routine_types import Routine
from swarmline.daemon.scheduler import Scheduler
from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard


pytestmark = pytest.mark.integration


class TestRoutineBridgeIntegration:
    async def test_routine_creates_task_after_interval(self) -> None:
        """Real Scheduler + real InMemoryGraphTaskBoard -- routine fires and creates task."""
        scheduler = Scheduler(tick_interval=0.05)
        board = InMemoryGraphTaskBoard()
        bridge = RoutineBridge(scheduler, board)

        routine = Routine(
            id="r1",
            name="Daily check",
            interval_seconds=0.1,
            agent_id="agent-1",
            goal_template="Check metrics",
        )
        await bridge.register(routine)

        stop = asyncio.Event()
        task = asyncio.create_task(scheduler.run_until(stop))
        await asyncio.sleep(0.3)  # Should fire ~2-3 times
        stop.set()
        await task

        all_tasks = await board.list_tasks()
        assert len(all_tasks) >= 1
        assert all_tasks[0].assignee_agent_id == "agent-1"
        assert all_tasks[0].title == "Check metrics"

    async def test_routine_dedup_prevents_duplicates(self) -> None:
        """With dedup_key, only one TODO/IN_PROGRESS task exists at a time."""
        scheduler = Scheduler(tick_interval=0.05)
        board = InMemoryGraphTaskBoard()
        bridge = RoutineBridge(scheduler, board)

        routine = Routine(
            id="r2",
            name="Dedup check",
            interval_seconds=0.1,
            agent_id="agent-1",
            goal_template="Dedup task",
            dedup_key="dedup-test",
        )
        await bridge.register(routine)

        stop = asyncio.Event()
        task = asyncio.create_task(scheduler.run_until(stop))
        await asyncio.sleep(0.3)  # Multiple ticks, but dedup should prevent extras
        stop.set()
        await task

        all_tasks = await board.list_tasks()
        # First trigger creates, subsequent ones should be deduped
        assert len(all_tasks) == 1

    async def test_unregister_stops_task_creation(self) -> None:
        """After unregister, no new tasks are created."""
        scheduler = Scheduler(tick_interval=0.05)
        board = InMemoryGraphTaskBoard()
        bridge = RoutineBridge(scheduler, board)

        routine = Routine(
            id="r3",
            name="Short-lived",
            interval_seconds=0.1,
            agent_id="agent-1",
            goal_template="Will stop",
        )
        await bridge.register(routine)

        stop = asyncio.Event()
        task = asyncio.create_task(scheduler.run_until(stop))
        await asyncio.sleep(0.15)  # Let it fire once

        await bridge.unregister("r3")
        count_after_unreg = len(await board.list_tasks())

        await asyncio.sleep(0.2)  # Wait more -- no new tasks
        stop.set()
        await task

        count_final = len(await board.list_tasks())
        assert count_final == count_after_unreg
