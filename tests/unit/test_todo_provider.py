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
                TodoItem(
                    id="1",
                    content="old",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await provider.write_todos(
            [
                TodoItem(
                    id="2",
                    content="new",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                ),
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
            TodoItem(
                id=str(i),
                content=f"t{i}",
                status="pending",
                created_at=now,
                updated_at=now,
            )
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
                    id="1",
                    content="alice task",
                    status="pending",
                    created_at=now,
                    updated_at=now,
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


class TestTodoToolsStage6:
    """taskloom Sprint 1ce Stage 6 (AGR-082): English schemas, todo_edit, full-list responses."""

    @staticmethod
    def _tools(provider=None, **kw):
        from swarmline.todo.inmemory_provider import InMemoryTodoProvider
        from swarmline.todo.tools import create_todo_tools

        provider = provider or InMemoryTodoProvider(user_id="u", topic_id="t")
        specs, executors = create_todo_tools(provider, **kw)
        return provider, specs, executors

    def test_tool_descriptions_are_english(self) -> None:
        import re

        _p, specs, _e = self._tools()
        blob = json.dumps(
            {name: [s.description, s.parameters] for name, s in specs.items()},
            ensure_ascii=False,
        )
        assert set(specs) == {"todo_read", "todo_write", "todo_edit"}
        assert re.search("[А-Яа-яЁё]", blob) is None

    async def test_todo_write_preserves_created_at_of_existing_ids(self) -> None:
        from swarmline.todo.types import TodoItem

        provider, _s, executors = self._tools()
        old = datetime(2026, 1, 1, tzinfo=UTC)
        await provider.write_todos(
            [
                TodoItem(
                    id="a",
                    content="keep",
                    status="pending",
                    created_at=old,
                    updated_at=old,
                )
            ]
        )

        raw = await executors["todo_write"](
            {
                "todos": [
                    {"id": "a", "content": "keep", "status": "in_progress"},
                    {"id": "b", "content": "new", "status": "pending"},
                ]
            }
        )

        assert json.loads(raw)["status"] == "ok"
        a, b = await provider.read_todos()
        assert a.created_at == old
        assert a.updated_at > old
        assert b.created_at > old

    async def test_todo_write_accepts_several_in_progress(self) -> None:
        provider, _s, executors = self._tools()

        raw = await executors["todo_write"](
            {
                "todos": [
                    {"id": "a", "content": "one", "status": "in_progress"},
                    {"id": "b", "content": "two", "status": "in_progress"},
                ]
            }
        )

        data = json.loads(raw)
        assert data["status"] != "error"
        assert [t.status for t in await provider.read_todos()] == [
            "in_progress",
            "in_progress",
        ]

    async def test_todo_tool_descriptions_allow_parallel_in_progress(self) -> None:
        _provider, specs, _executors = self._tools()

        for name in ("todo_write", "todo_edit"):
            description = specs[name].description
            assert "exactly one" not in description
            assert "several items may be in_progress" in description

    async def test_todo_write_rejects_non_list(self) -> None:
        _p, _s, executors = self._tools()

        data = json.loads(await executors["todo_write"]({"todos": "a,b"}))

        assert data == {"status": "error", "message": "todos must be an array"}

    def test_todo_edit_registered_only_for_edit_provider(self) -> None:
        from swarmline.todo.tools import create_todo_tools

        class ReadWriteOnly:
            async def read_todos(self) -> list:
                return []

            async def write_todos(self, todos: list) -> None:
                return None

        specs, executors = create_todo_tools(ReadWriteOnly())
        assert "todo_edit" not in specs and "todo_edit" not in executors
        _p, specs, executors = self._tools()
        assert "todo_edit" in specs and "todo_edit" in executors
        op_schema = specs["todo_edit"].parameters["properties"]["ops"]["items"]
        assert {v["properties"]["op"]["const"] for v in op_schema["oneOf"]} == {
            "add",
            "update",
            "remove",
        }

    def test_include_read_false_omits_todo_read(self) -> None:
        _p, specs, executors = self._tools(include_read=False)

        assert set(specs) == {"todo_write", "todo_edit"}
        assert set(executors) == {"todo_write", "todo_edit"}

    async def test_full_list_response_returns_items_and_hint(self) -> None:
        _p, _s, executors = self._tools(full_list_response=True)

        written = json.loads(
            await executors["todo_write"](
                {"todos": [{"id": "a", "content": "one", "status": "in_progress"}]}
            )
        )
        edited = json.loads(
            await executors["todo_edit"](
                {
                    "ops": [
                        {"op": "update", "id": "a", "status": "completed"},
                        {"op": "add", "content": "two"},
                    ]
                }
            )
        )

        assert written == {
            "status": "ok",
            "todos": [{"id": "a", "content": "one", "status": "in_progress"}],
            "hint": None,
        }
        assert edited["status"] == "ok"
        assert [(t["content"], t["status"]) for t in edited["todos"]] == [
            ("one", "completed"),
            ("two", "pending"),
        ]
        assert edited["hint"] == "mark the item you start next as in_progress"

    async def test_todo_edit_failed_batch_reports_op_and_keeps_list(self) -> None:
        provider, _s, executors = self._tools(full_list_response=True)
        await executors["todo_write"](
            {"todos": [{"id": "a", "content": "one", "status": "pending"}]}
        )

        data = json.loads(
            await executors["todo_edit"](
                {
                    "ops": [
                        {"op": "update", "id": "a", "status": "completed"},
                        {"op": "remove", "id": "x"},
                    ]
                }
            )
        )
        bad_shape = json.loads(await executors["todo_edit"]({"ops": {}}))

        assert data["status"] == "error" and data["message"].startswith("op 1:")
        assert bad_shape == {
            "status": "error",
            "message": "ops must be a non-empty array",
        }
        assert [t.status for t in await provider.read_todos()] == ["pending"]

    async def test_default_flags_response_shape_unchanged(self) -> None:
        _p, _s, executors = self._tools()

        written = json.loads(
            await executors["todo_write"](
                {"todos": [{"id": "a", "content": "one", "status": "pending"}]}
            )
        )
        edited = json.loads(
            await executors["todo_edit"]({"ops": [{"op": "add", "content": "two"}]})
        )

        assert written == {"status": "ok", "count": 1}
        assert edited == {"status": "ok", "count": 2}

    async def test_todo_edit_store_failure_is_reported_not_raised(self, caplog) -> None:
        from swarmline.todo.tools import create_todo_tools

        class DownStore:
            async def read_todos(self) -> list:
                return []

            async def write_todos(self, todos: list) -> None:
                return None

            async def apply_edit(self, ops: list) -> None:
                raise ConnectionError("database unavailable")

        _specs, executors = create_todo_tools(DownStore())

        data = json.loads(
            await executors["todo_edit"]({"ops": [{"op": "add", "content": "x"}]})
        )

        # Store internals (SQL text, hosts) never reach the model; the log keeps them.
        assert data == {
            "status": "error",
            "message": "the todo list is unavailable right now; try again",
        }
        assert "database unavailable" in caplog.text

    async def test_todo_read_store_failure_is_reported_not_raised(self, caplog) -> None:
        from swarmline.todo.tools import create_todo_tools

        class DownStore:
            async def read_todos(self) -> list:
                raise ConnectionError("database unavailable")

            async def write_todos(self, todos: list) -> None:
                return None

        _specs, executors = create_todo_tools(DownStore())

        data = json.loads(await executors["todo_read"]({}))

        # Store internals (SQL text, hosts) never reach the model; the log keeps them.
        assert data == {
            "status": "error",
            "message": "the todo list is unavailable right now; try again",
        }
        assert "database unavailable" in caplog.text

    async def test_todo_write_store_failure_is_generic_but_validation_is_specific(
        self, caplog
    ) -> None:
        from swarmline.todo.tools import create_todo_tools

        class BrokenWrites:
            async def read_todos(self) -> list:
                return []

            async def write_todos(self, todos: list) -> None:
                if todos and todos[0].id == "bad":
                    raise ValueError("id must be 1-64 characters")
                raise RuntimeError('INSERT INTO run_todos violates "pk_run_todos"')

        _specs, executors = create_todo_tools(BrokenWrites())
        todo = {"content": "x", "status": "pending"}

        failed = json.loads(
            await executors["todo_write"]({"todos": [{"id": "ok", **todo}]})
        )
        invalid = json.loads(
            await executors["todo_write"]({"todos": [{"id": "bad", **todo}]})
        )

        assert failed["message"] == "the todo list is unavailable right now; try again"
        assert "run_todos" not in json.dumps(failed) and "pk_run_todos" in caplog.text
        assert invalid["message"] == "id must be 1-64 characters"
