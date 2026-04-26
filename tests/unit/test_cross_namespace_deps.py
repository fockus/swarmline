"""Tests for CrossNamespaceResolver (COG-08)."""

from __future__ import annotations

import pytest

from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.multi_agent.shared_agents import CrossNamespaceResolver


def _task(id: str, title: str = "Task", **kwargs) -> GraphTaskItem:
    return GraphTaskItem(id=id, title=title, **kwargs)


@pytest.fixture
async def boards():
    board_a = InMemoryGraphTaskBoard(namespace="goal-a")
    board_b = InMemoryGraphTaskBoard(namespace="goal-b")
    return {"goal-a": board_a, "goal-b": board_b}


@pytest.fixture
async def resolver(boards):
    return CrossNamespaceResolver(boards=boards)


class TestCrossNamespaceResolverBasics:
    async def test_resolve_task_found(self, boards, resolver) -> None:
        await boards["goal-a"].create_task(_task("t1"))
        result = await resolver.resolve_task("t1")
        assert result is not None
        ns, task = result
        assert ns == "goal-a"
        assert task.id == "t1"

    async def test_resolve_task_not_found(self, resolver) -> None:
        result = await resolver.resolve_task("nonexistent")
        assert result is None

    async def test_resolve_task_in_second_board(self, boards, resolver) -> None:
        await boards["goal-b"].create_task(_task("t2"))
        result = await resolver.resolve_task("t2")
        assert result is not None
        ns, _ = result
        assert ns == "goal-b"


class TestCrossNamespaceDependencies:
    async def _complete(self, board: InMemoryGraphTaskBoard, task_id: str) -> None:
        await board.checkout_task(task_id, "agent")
        await board.complete_task(task_id)

    async def test_get_blocked_by_cross_namespace(self, boards, resolver) -> None:
        # task_b in goal-b is a dependency
        await boards["goal-b"].create_task(_task("dep-b"))
        # task_a in goal-a depends on dep-b
        await boards["goal-a"].create_task(_task("t1", dependencies=("dep-b",)))
        blockers = await resolver.get_blocked_by("t1", namespace="goal-a")
        assert len(blockers) == 1
        assert blockers[0].id == "dep-b"

    async def test_are_deps_met_false_when_dep_not_done(self, boards, resolver) -> None:
        await boards["goal-b"].create_task(_task("dep-b"))
        await boards["goal-a"].create_task(_task("t1", dependencies=("dep-b",)))
        met = await resolver.are_dependencies_met("t1", namespace="goal-a")
        assert met is False

    async def test_are_deps_met_true_after_dep_completed(
        self, boards, resolver
    ) -> None:
        await boards["goal-b"].create_task(_task("dep-b"))
        await boards["goal-a"].create_task(_task("t1", dependencies=("dep-b",)))
        await self._complete(boards["goal-b"], "dep-b")
        met = await resolver.are_dependencies_met("t1", namespace="goal-a")
        assert met is True

    async def test_local_deps_resolved_normally(self, boards, resolver) -> None:
        await boards["goal-a"].create_task(_task("dep-a"))
        await boards["goal-a"].create_task(_task("t1", dependencies=("dep-a",)))
        met = await resolver.are_dependencies_met("t1", namespace="goal-a")
        assert met is False

        await self._complete(boards["goal-a"], "dep-a")
        met = await resolver.are_dependencies_met("t1", namespace="goal-a")
        assert met is True

    async def test_mixed_local_and_cross_deps(self, boards, resolver) -> None:
        await boards["goal-a"].create_task(_task("local-dep"))
        await boards["goal-b"].create_task(_task("cross-dep"))
        await boards["goal-a"].create_task(
            _task("t1", dependencies=("local-dep", "cross-dep"))
        )
        # Neither done
        assert await resolver.are_dependencies_met("t1", namespace="goal-a") is False

        # Complete local dep only
        await self._complete(boards["goal-a"], "local-dep")
        assert await resolver.are_dependencies_met("t1", namespace="goal-a") is False

        # Complete cross dep too
        await self._complete(boards["goal-b"], "cross-dep")
        assert await resolver.are_dependencies_met("t1", namespace="goal-a") is True

    async def test_task_with_no_deps_is_met(self, boards, resolver) -> None:
        await boards["goal-a"].create_task(_task("t1"))
        met = await resolver.are_dependencies_met("t1", namespace="goal-a")
        assert met is True

    async def test_get_blocked_by_returns_empty_for_task_with_no_deps(
        self, boards, resolver
    ) -> None:
        await boards["goal-a"].create_task(_task("t1"))
        blockers = await resolver.get_blocked_by("t1", namespace="goal-a")
        assert blockers == []

    async def test_nonexistent_task_returns_empty_blockers(
        self, boards, resolver
    ) -> None:
        blockers = await resolver.get_blocked_by("nonexistent", namespace="goal-a")
        assert blockers == []
