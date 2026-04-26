"""Contract tests for TaskSessionStore — parametrized over InMemory and SQLite backends."""

from __future__ import annotations

import asyncio
import time

import pytest

from swarmline.session.task_session_store import (
    InMemoryTaskSessionStore,
    SqliteTaskSessionStore,
    TaskSessionStore,
)
from swarmline.session.task_session_types import TaskSessionParams


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["inmemory", "sqlite"])
def store(request, tmp_path):
    if request.param == "inmemory":
        return InMemoryTaskSessionStore()
    else:
        return SqliteTaskSessionStore(str(tmp_path / "test.db"))


# ---------------------------------------------------------------------------
# Protocol shape
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_protocol_shape_inmemory(self) -> None:
        store = InMemoryTaskSessionStore()
        assert isinstance(store, TaskSessionStore)

    def test_protocol_shape_sqlite(self, tmp_path) -> None:
        store = SqliteTaskSessionStore(str(tmp_path / "proto.db"))
        assert isinstance(store, TaskSessionStore)


# ---------------------------------------------------------------------------
# Save & Load (round-trip)
# ---------------------------------------------------------------------------


class TestSaveAndLoad:
    async def test_save_and_load_roundtrip(self, store) -> None:
        params = {"model": "sonnet", "temperature": 0.7, "tools": ["web", "code"]}
        await store.save("agent-1", "task-42", params)
        loaded = await store.load("agent-1", "task-42")
        assert loaded == params

    async def test_load_missing_returns_none(self, store) -> None:
        result = await store.load("nonexistent-agent", "nonexistent-task")
        assert result is None

    async def test_load_returns_deep_copy(self, store) -> None:
        """Mutating loaded dict must not affect stored data."""
        params = {"nested": {"key": "original"}}
        await store.save("a1", "t1", params)
        loaded = await store.load("a1", "t1")
        assert loaded is not None
        loaded["nested"]["key"] = "mutated"
        reloaded = await store.load("a1", "t1")
        assert reloaded is not None
        assert reloaded["nested"]["key"] == "original"

    async def test_save_and_load_distinguishes_ids_with_colons(self, store) -> None:
        await store.save("agent:1", "task", {"value": 1})
        await store.save("agent", "1:task", {"value": 2})

        first = await store.load("agent:1", "task")
        second = await store.load("agent", "1:task")

        assert first == {"value": 1}
        assert second == {"value": 2}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_existing_returns_true(self, store) -> None:
        await store.save("a1", "t1", {"x": 1})
        result = await store.delete("a1", "t1")
        assert result is True
        assert await store.load("a1", "t1") is None

    async def test_delete_missing_returns_false(self, store) -> None:
        result = await store.delete("nonexistent", "nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# List by agent
# ---------------------------------------------------------------------------


class TestListByAgent:
    async def test_list_by_agent_filters_correctly(self, store) -> None:
        await store.save("agent-1", "task-a", {"a": 1})
        await store.save("agent-1", "task-b", {"b": 2})
        await store.save("agent-2", "task-c", {"c": 3})

        results = await store.list_by_agent("agent-1")
        assert len(results) == 2
        task_ids = {r.task_id for r in results}
        assert task_ids == {"task-a", "task-b"}
        for r in results:
            assert isinstance(r, TaskSessionParams)
            assert r.agent_id == "agent-1"

    async def test_list_by_agent_empty(self, store) -> None:
        results = await store.list_by_agent("no-such-agent")
        assert results == []

    async def test_list_by_agent_no_false_prefix_match(self, store) -> None:
        """agent-1 must not match agent-10."""
        await store.save("agent-1", "t1", {"x": 1})
        await store.save("agent-10", "t2", {"x": 2})
        results = await store.list_by_agent("agent-1")
        assert len(results) == 1
        assert results[0].task_id == "t1"

    async def test_list_by_agent_returns_defensive_copy(self, store) -> None:
        await store.save("agent-1", "task-a", {"nested": {"value": "original"}})

        results = await store.list_by_agent("agent-1")
        assert len(results) == 1
        results[0].params["nested"]["value"] = "mutated"

        loaded = await store.load("agent-1", "task-a")
        assert loaded == {"nested": {"value": "original"}}


# ---------------------------------------------------------------------------
# Upsert semantics
# ---------------------------------------------------------------------------


class TestUpsert:
    async def test_save_overwrites_existing(self, store) -> None:
        await store.save("a1", "t1", {"v": 1})
        first = await store.list_by_agent("a1")
        first_updated = first[0].updated_at

        # Small delay to ensure updated_at changes
        await asyncio.sleep(0.01)

        await store.save("a1", "t1", {"v": 2})
        loaded = await store.load("a1", "t1")
        assert loaded == {"v": 2}

        second = await store.list_by_agent("a1")
        assert len(second) == 1  # still one record, not two
        assert second[0].updated_at >= first_updated

    async def test_save_upsert_preserves_created_at(self, store) -> None:
        await store.save("a1", "t1", {"v": 1})
        first = await store.list_by_agent("a1")
        created = first[0].created_at

        await asyncio.sleep(0.01)

        await store.save("a1", "t1", {"v": 2})
        second = await store.list_by_agent("a1")
        assert second[0].created_at == pytest.approx(created, abs=0.001)


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------


class TestConcurrency:
    async def test_concurrent_save_load(self, store) -> None:
        """Multiple concurrent saves and loads must not corrupt data."""

        async def save_and_load(agent_id: str, task_id: str, value: int) -> dict | None:
            await store.save(agent_id, task_id, {"value": value})
            return await store.load(agent_id, task_id)

        results = await asyncio.gather(
            save_and_load("a1", "t1", 1),
            save_and_load("a1", "t2", 2),
            save_and_load("a2", "t1", 3),
            save_and_load("a2", "t2", 4),
        )
        # All loads must return a dict (not None)
        for r in results:
            assert r is not None
            assert "value" in r


# ---------------------------------------------------------------------------
# TaskSessionParams structure
# ---------------------------------------------------------------------------


class TestTaskSessionParamsType:
    def test_frozen(self) -> None:
        p = TaskSessionParams(agent_id="a", task_id="t")
        with pytest.raises(AttributeError):
            p.agent_id = "x"  # type: ignore[misc]

    def test_defaults(self) -> None:
        before = time.time()
        p = TaskSessionParams(agent_id="a", task_id="t")
        after = time.time()
        assert p.params == {}
        assert before <= p.created_at <= after
        assert before <= p.updated_at <= after
