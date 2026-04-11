"""Unit tests for PostgresGraphTaskBoard namespace and validation guards."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cognitia.multi_agent.graph_task_board_postgres import PostgresGraphTaskBoard
from cognitia.multi_agent.graph_task_types import GraphTaskItem
from cognitia.multi_agent.task_types import TaskStatus


def _task(
    id: str,
    title: str = "Task",
    **kwargs,
) -> GraphTaskItem:
    return GraphTaskItem(id=id, title=title, **kwargs)


def _session_factory(session: AsyncMock) -> MagicMock:
    @asynccontextmanager
    async def _ctx():
        yield session

    factory = MagicMock()
    factory.side_effect = lambda: _ctx()
    return factory


def _result(*, fetchone=None, fetchall=None) -> MagicMock:
    result = MagicMock()
    result.fetchone.return_value = fetchone
    result.fetchall.return_value = fetchall if fetchall is not None else []
    return result


class TestCreationValidation:

    @pytest.mark.asyncio
    async def test_create_task_rejects_self_parent(self) -> None:
        session = AsyncMock()
        board = PostgresGraphTaskBoard(_session_factory(session))

        with pytest.raises(ValueError, match="own parent"):
            await board.create_task(_task("t1", parent_task_id="t1"))

    @pytest.mark.asyncio
    async def test_create_task_rejects_cycle(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_result(
                fetchone=(PostgresGraphTaskBoard._serialize_task(
                    _task("a", parent_task_id="b")
                ),)
            )
        )
        board = PostgresGraphTaskBoard(_session_factory(session))

        with pytest.raises(ValueError, match="Cycle"):
            await board.create_task(_task("b", parent_task_id="a"))


class TestCompletionStatus:

    @pytest.mark.asyncio
    async def test_complete_task_requires_in_progress(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_result(
                fetchone=(PostgresGraphTaskBoard._serialize_task(_task("t1")),)
            )
        )
        board = PostgresGraphTaskBoard(_session_factory(session))

        ok = await board.complete_task("t1")

        assert ok is False
        assert session.execute.await_count == 1


class TestNamespaceQueries:

    @pytest.mark.asyncio
    async def test_get_comments_filters_namespace(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result())
        board = PostgresGraphTaskBoard(_session_factory(session), namespace="goal-a")

        await board.get_comments("root")

        statement = str(session.execute.call_args.args[0])
        assert "JOIN graph_tasks" in statement
        assert "t.namespace = :ns" in statement

    @pytest.mark.asyncio
    async def test_get_thread_filters_namespace(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result())
        board = PostgresGraphTaskBoard(_session_factory(session), namespace="goal-a")

        await board.get_thread("root")

        statement = str(session.execute.call_args.args[0])
        assert "WITH RECURSIVE sub" in statement
        assert "t.namespace = :ns" in statement

    @pytest.mark.asyncio
    async def test_get_goal_ancestry_filters_namespace(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_result())
        board = PostgresGraphTaskBoard(_session_factory(session), namespace="goal-a")

        await board.get_goal_ancestry("leaf")

        statement = str(session.execute.call_args.args[0])
        assert "WITH RECURSIVE ancestry" in statement
        assert "namespace = :ns" in statement

    @pytest.mark.asyncio
    async def test_get_blocked_by_filters_namespace(self) -> None:
        session = AsyncMock()
        task_row = PostgresGraphTaskBoard._serialize_task(
            _task("child", dependencies=("dep-a",))
        )
        session.execute = AsyncMock(
            side_effect=[
                _result(fetchone=(task_row,)),
                _result(fetchall=[]),
            ]
        )
        board = PostgresGraphTaskBoard(_session_factory(session), namespace="goal-a")

        await board.get_blocked_by("child")

        statement = str(session.execute.call_args_list[1].args[0])
        assert "namespace = :ns" in statement


class TestPropagationIsolation:

    @pytest.mark.asyncio
    async def test_complete_task_keeps_parent_namespace_isolated(self) -> None:
        session = AsyncMock()
        child = _task("child", parent_task_id="root", status=TaskStatus.IN_PROGRESS)
        done_child = replace(child, status=TaskStatus.DONE, completed_at=1.0, progress=1.0)
        parent = _task("root")
        session.execute = AsyncMock(
            side_effect=[
                _result(fetchone=(PostgresGraphTaskBoard._serialize_task(child),)),
                _result(),
                _result(fetchall=[(PostgresGraphTaskBoard._serialize_task(done_child),)]),
                _result(fetchone=(PostgresGraphTaskBoard._serialize_task(parent),)),
                _result(),
            ]
        )
        board = PostgresGraphTaskBoard(_session_factory(session), namespace="goal-a")

        ok = await board.complete_task("child")

        assert ok is True
        child_select = str(session.execute.call_args_list[0].args[0])
        parent_select = str(session.execute.call_args_list[3].args[0])
        assert "namespace = :ns" in child_select
        assert "namespace = :ns" in parent_select
