"""Tests TodoProvider - Protocol, InMemory, tools.

TDD: RED -> GREEN -> REFACTOR.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest


class TestTodoItem:
    """Validation TodoItem dataclass."""

    def test_create_item(self) -> None:
        from swarmline.todo.types import TodoItem

        item = TodoItem(
            id="t1",
            content="Сделать тесты",
            status="pending",
            created_at=datetime(2026, 2, 12, tzinfo=UTC),
            updated_at=datetime(2026, 2, 12, tzinfo=UTC),
        )
        assert item.id == "t1"
        assert item.status == "pending"

    def test_item_frozen(self) -> None:
        from swarmline.todo.types import TodoItem

        item = TodoItem(
            id="t1",
            content="x",
            status="pending",
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        with pytest.raises(AttributeError):
            item.status = "completed"  # type: ignore[misc]

    def test_to_dict(self) -> None:
        from swarmline.todo.types import TodoItem

        item = TodoItem(
            id="t1",
            content="task",
            status="in_progress",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        d = item.to_dict()
        assert d["id"] == "t1"
        assert d["status"] == "in_progress"
        assert "created_at" in d


class TestTodoConfig:
    """Validation TodoConfig."""

    def test_defaults(self) -> None:
        from swarmline.todo.types import TodoConfig

        config = TodoConfig()
        assert config.enabled is False
        assert config.backend == "memory"
        assert config.max_todos == 100

    def test_custom(self) -> None:
        from swarmline.todo.types import TodoConfig

        config = TodoConfig(enabled=True, backend="database", max_todos=50)
        assert config.enabled is True
        assert config.backend == "database"


class TestTodoProviderProtocol:
    """Contract tests for TodoProvider Protocol."""

    def test_runtime_checkable(self) -> None:
        from swarmline.todo.protocols import TodoProvider

        class FakeTodo:
            async def read_todos(self) -> list:
                return []

            async def write_todos(self, todos: list) -> None:
                pass

        assert isinstance(FakeTodo(), TodoProvider)

    def test_incomplete_not_instance(self) -> None:
        from swarmline.todo.protocols import TodoProvider

        class Incomplete:
            async def read_todos(self) -> list:
                return []

        assert not isinstance(Incomplete(), TodoProvider)

    def test_protocol_has_two_methods(self) -> None:
        """ISP: TodoProvider has ≤5 methods."""
        from swarmline.todo.protocols import TodoProvider

        methods = [
            n
            for n in dir(TodoProvider)
            if not n.startswith("_") and callable(getattr(TodoProvider, n, None))
        ]
        assert len(methods) <= 5


class TestInMemoryTodoProvider:
    """Tests InMemoryTodoProvider."""

    async def test_empty_read(self) -> None:
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider

        provider = InMemoryTodoProvider(user_id="u1", topic_id="t1")
        todos = await provider.read_todos()
        assert todos == []

    async def test_write_and_read(self) -> None:
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.types import TodoItem

        provider = InMemoryTodoProvider(user_id="u1", topic_id="t1")
        items = [
            TodoItem(
                id="1",
                content="Задача 1",
                status="pending",
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            ),
            TodoItem(
                id="2",
                content="Задача 2",
                status="in_progress",
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            ),
        ]
        await provider.write_todos(items)
        result = await provider.read_todos()
        assert len(result) == 2
        assert result[0].id == "1"

    async def test_bulk_replace(self) -> None:
        """write_todos replaces the entire todos."""
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.types import TodoItem

        provider = InMemoryTodoProvider(user_id="u1", topic_id="t1")
        now = datetime.now(tz=UTC)

        await provider.write_todos(
            [
                TodoItem(id="1", content="old", status="pending", created_at=now, updated_at=now),
            ]
        )
        await provider.write_todos(
            [
                TodoItem(id="2", content="new", status="pending", created_at=now, updated_at=now),
            ]
        )

        result = await provider.read_todos()
        assert len(result) == 1
        assert result[0].id == "2"

    async def test_max_todos_limit(self) -> None:
        """Exceeding max_todos -> ValueError."""
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.types import TodoItem

        provider = InMemoryTodoProvider(user_id="u1", topic_id="t1", max_todos=2)
        now = datetime.now(tz=UTC)

        items = [
            TodoItem(id=str(i), content=f"t{i}", status="pending", created_at=now, updated_at=now)
            for i in range(5)
        ]
        with pytest.raises(ValueError, match="max_todos"):
            await provider.write_todos(items)

    async def test_multi_tenant_isolation(self) -> None:
        """Different user_id/topic_id - isolated data."""
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.types import TodoItem

        now = datetime.now(tz=UTC)
        p1 = InMemoryTodoProvider(user_id="alice", topic_id="t1")
        p2 = InMemoryTodoProvider(user_id="bob", topic_id="t1")

        await p1.write_todos(
            [
                TodoItem(
                    id="1", content="alice task", status="pending", created_at=now, updated_at=now
                ),
            ]
        )

        assert len(await p1.read_todos()) == 1
        assert len(await p2.read_todos()) == 0

    async def test_isinstance_protocol(self) -> None:
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.protocols import TodoProvider

        provider = InMemoryTodoProvider(user_id="u", topic_id="t")
        assert isinstance(provider, TodoProvider)


class TestTodoTools:
    """Tests todo_read / todo_write tools."""

    async def test_todo_read_empty(self) -> None:
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.tools import create_todo_tools

        provider = InMemoryTodoProvider(user_id="u", topic_id="t")
        _specs, executors = create_todo_tools(provider)

        result = await executors["todo_read"]({})
        data = json.loads(result)
        assert data["todos"] == []

    async def test_todo_write_and_read(self) -> None:
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.tools import create_todo_tools

        provider = InMemoryTodoProvider(user_id="u", topic_id="t")
        _specs, executors = create_todo_tools(provider)

        result = await executors["todo_write"](
            {
                "todos": [
                    {"id": "1", "content": "task one", "status": "pending"},
                    {"id": "2", "content": "task two", "status": "in_progress"},
                ],
            }
        )
        data = json.loads(result)
        assert data["status"] == "ok"

        result = await executors["todo_read"]({})
        data = json.loads(result)
        assert len(data["todos"]) == 2

    async def test_todo_read_with_status_filter(self) -> None:
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.tools import create_todo_tools

        provider = InMemoryTodoProvider(user_id="u", topic_id="t")
        _specs, executors = create_todo_tools(provider)

        await executors["todo_write"](
            {
                "todos": [
                    {"id": "1", "content": "done", "status": "completed"},
                    {"id": "2", "content": "wip", "status": "in_progress"},
                ],
            }
        )

        result = await executors["todo_read"]({"status_filter": "in_progress"})
        data = json.loads(result)
        assert len(data["todos"]) == 1
        assert data["todos"][0]["status"] == "in_progress"

    def test_tool_specs(self) -> None:
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.tools import create_todo_tools

        provider = InMemoryTodoProvider(user_id="u", topic_id="t")
        specs, executors = create_todo_tools(provider)

        assert "todo_read" in specs
        assert "todo_write" in specs
        assert "todo_read" in executors
        assert "todo_write" in executors
