"""Behavioral integration tests for Postgres backends.

These tests require a disposable Postgres database. Set either
`SWARMLINE_TEST_POSTGRES_DSN` or `TEST_POSTGRES_DSN` to an async SQLAlchemy DSN,
for example `postgresql+asyncpg://user:pass@localhost:5432/swarmline_test`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from swarmline.multi_agent.graph_store_postgres import (
    POSTGRES_GRAPH_SCHEMA,
    PostgresAgentGraph,
)
from swarmline.multi_agent.graph_task_board_postgres import (
    POSTGRES_GRAPH_TASK_SCHEMA,
    PostgresGraphTaskBoard,
)
from swarmline.multi_agent.graph_task_types import GraphTaskItem
from swarmline.multi_agent.graph_types import AgentNode
from swarmline.session.backends_postgres import (
    POSTGRES_SESSION_SCHEMA,
    PostgresSessionBackend,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_dsn() -> str:
    dsn = os.getenv("SWARMLINE_TEST_POSTGRES_DSN") or os.getenv("TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "Set SWARMLINE_TEST_POSTGRES_DSN or TEST_POSTGRES_DSN for Postgres integration"
        )
    return dsn


@pytest.fixture
async def session_factory(
    postgres_dsn: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(postgres_dsn, future=True)
    async with engine.begin() as conn:
        for schema in [
            POSTGRES_GRAPH_SCHEMA,
            POSTGRES_GRAPH_TASK_SCHEMA,
            POSTGRES_SESSION_SCHEMA,
        ]:
            for statement in schema.split(";"):
                if statement.strip():
                    await conn.execute(text(statement))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    async with session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE graph_task_comments, graph_tasks RESTART IDENTITY CASCADE"
            )
        )
        await session.execute(text("TRUNCATE TABLE sessions RESTART IDENTITY CASCADE"))
        await session.execute(
            text("TRUNCATE TABLE agent_nodes RESTART IDENTITY CASCADE")
        )
        await session.commit()
    yield


class TestPostgresGraphTaskBoardIntegration:
    async def test_task_lifecycle_and_namespace_isolation(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        board_a = PostgresGraphTaskBoard(session_factory, namespace="goal-a")
        board_b = PostgresGraphTaskBoard(session_factory, namespace="goal-b")

        await board_a.create_task(GraphTaskItem(id="a1", title="Task A"))
        await board_b.create_task(GraphTaskItem(id="b1", title="Task B"))

        checked_out = await board_a.checkout_task("a1", "agent-a")
        assert checked_out is not None
        assert checked_out.status.value == "in_progress"

        completed = await board_a.complete_task("a1")
        assert completed is True

        tasks_a = await board_a.list_tasks()
        tasks_b = await board_b.list_tasks()
        assert [task.id for task in tasks_a] == ["a1"]
        assert [task.id for task in tasks_b] == ["b1"]
        assert tasks_a[0].status.value == "done"


class TestPostgresSessionBackendIntegration:
    async def test_save_load_delete_roundtrip(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        backend = PostgresSessionBackend(session_factory)

        await backend.save("u1:t1", {"role_id": "coach", "issues": ["a"]})

        loaded = await backend.load("u1:t1")
        assert loaded == {"role_id": "coach", "issues": ["a"]}

        deleted = await backend.delete("u1:t1")
        assert deleted is True
        assert await backend.load("u1:t1") is None


class TestPostgresAgentGraphIntegration:
    async def test_add_get_update_and_subtree(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        graph = PostgresAgentGraph(session_factory)

        await graph.add_node(AgentNode(id="root", name="Root", role="ceo"))
        await graph.add_node(
            AgentNode(id="child", name="Child", role="cto", parent_id="root")
        )

        root = await graph.get_root()
        assert root is not None
        assert root.id == "root"

        updated = await graph.update_node("child", system_prompt="Lead engineering")
        assert updated is not None
        assert updated.system_prompt == "Lead engineering"

        subtree = await graph.get_subtree("root")
        assert {node.id for node in subtree} == {"root", "child"}
