"""Tests FilesystemTodoProvider - TDD."""

from __future__ import annotations

from datetime import UTC, datetime

from cognitia.todo.types import TodoItem


def _now() -> datetime:
    return datetime.now(tz=UTC)


class TestFilesystemTodoProvider:
    async def test_empty_read(self, tmp_path) -> None:
        from cognitia.todo.fs_provider import FilesystemTodoProvider

        p = FilesystemTodoProvider(tmp_path, "u1", "t1")
        assert await p.read_todos() == []

    async def test_write_and_read(self, tmp_path) -> None:
        from cognitia.todo.fs_provider import FilesystemTodoProvider

        p = FilesystemTodoProvider(tmp_path, "u1", "t1")
        items = [
            TodoItem(id="1", content="task", status="pending", created_at=_now(), updated_at=_now())
        ]
        await p.write_todos(items)
        result = await p.read_todos()
        assert len(result) == 1
        assert result[0].id == "1"

    async def test_bulk_replace(self, tmp_path) -> None:
        from cognitia.todo.fs_provider import FilesystemTodoProvider

        p = FilesystemTodoProvider(tmp_path, "u1", "t1")
        now = _now()
        await p.write_todos(
            [TodoItem(id="1", content="old", status="pending", created_at=now, updated_at=now)]
        )
        await p.write_todos(
            [TodoItem(id="2", content="new", status="pending", created_at=now, updated_at=now)]
        )
        result = await p.read_todos()
        assert len(result) == 1
        assert result[0].id == "2"

    async def test_cross_user_isolation(self, tmp_path) -> None:
        from cognitia.todo.fs_provider import FilesystemTodoProvider

        p1 = FilesystemTodoProvider(tmp_path, "alice", "t1")
        p2 = FilesystemTodoProvider(tmp_path, "bob", "t1")
        now = _now()
        await p1.write_todos(
            [TodoItem(id="1", content="t", status="pending", created_at=now, updated_at=now)]
        )
        assert len(await p1.read_todos()) == 1
        assert len(await p2.read_todos()) == 0

    async def test_isinstance_protocol(self, tmp_path) -> None:
        from cognitia.todo.fs_provider import FilesystemTodoProvider
        from cognitia.todo.protocols import TodoProvider

        p = FilesystemTodoProvider(tmp_path, "u", "t")
        assert isinstance(p, TodoProvider)
