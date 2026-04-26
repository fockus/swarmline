"""Unit tests for session backends and memory scopes (Phase 8A)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from swarmline.session.backends import (
    InMemorySessionBackend,
    MemoryScope,
    SqliteSessionBackend,
    SessionBackend,
    scoped_key,
)
from swarmline.session.types import SessionKey


# ---------------------------------------------------------------------------
# SessionBackend Protocol compliance
# ---------------------------------------------------------------------------


class TestSessionBackendProtocolCompliance:
    """Both backends satisfy the SessionBackend protocol."""

    def test_inmemory_is_session_backend(self) -> None:
        assert isinstance(InMemorySessionBackend(), SessionBackend)

    def test_sqlite_is_session_backend(self, tmp_path: Any) -> None:
        db = str(tmp_path / "test.db")
        backend = SqliteSessionBackend(db_path=db)
        assert isinstance(backend, SessionBackend)
        backend.close()


# ---------------------------------------------------------------------------
# MemoryScope
# ---------------------------------------------------------------------------


class TestMemoryScope:
    """MemoryScope enum values and key prefixing."""

    def test_scope_values(self) -> None:
        assert MemoryScope.GLOBAL.value == "global"
        assert MemoryScope.AGENT.value == "agent"
        assert MemoryScope.SHARED.value == "shared"

    def test_scope_is_str_enum(self) -> None:
        assert isinstance(MemoryScope.GLOBAL, str)

    @pytest.mark.parametrize(
        ("scope", "original", "expected"),
        [
            (MemoryScope.GLOBAL, "user:123", "global:user:123"),
            (MemoryScope.AGENT, "session:abc", "agent:session:abc"),
            (MemoryScope.SHARED, "data", "shared:data"),
        ],
    )
    def test_scoped_key_prefixing(
        self, scope: MemoryScope, original: str, expected: str
    ) -> None:
        assert scoped_key(scope, original) == expected

    def test_different_scopes_produce_different_keys(self) -> None:
        key = "session:1"
        keys = {scoped_key(scope, key) for scope in MemoryScope}
        assert len(keys) == 3


# ---------------------------------------------------------------------------
# InMemorySessionBackend
# ---------------------------------------------------------------------------


class TestInMemorySessionBackend:
    """InMemorySessionBackend — full CRUD."""

    @pytest.mark.asyncio
    async def test_save_and_load(self) -> None:
        backend = InMemorySessionBackend()
        state = {"role": "coach", "counter": 1}
        await backend.save("k1", state)
        loaded = await backend.load("k1")
        assert loaded == state

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self) -> None:
        backend = InMemorySessionBackend()
        assert await backend.load("nonexistent") is None

    @pytest.mark.asyncio
    async def test_save_overwrites(self) -> None:
        backend = InMemorySessionBackend()
        await backend.save("k1", {"v": 1})
        await backend.save("k1", {"v": 2})
        loaded = await backend.load("k1")
        assert loaded == {"v": 2}

    @pytest.mark.asyncio
    async def test_delete_existing_returns_true(self) -> None:
        backend = InMemorySessionBackend()
        await backend.save("k1", {"v": 1})
        result = await backend.delete("k1")
        assert result is True
        assert await backend.load("k1") is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self) -> None:
        backend = InMemorySessionBackend()
        result = await backend.delete("missing")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_keys_empty(self) -> None:
        backend = InMemorySessionBackend()
        assert await backend.list_keys() == []

    @pytest.mark.asyncio
    async def test_list_keys_returns_all(self) -> None:
        backend = InMemorySessionBackend()
        await backend.save("a", {"x": 1})
        await backend.save("b", {"x": 2})
        keys = await backend.list_keys()
        assert sorted(keys) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_save_and_load_use_snapshot_semantics(self) -> None:
        backend = InMemorySessionBackend()
        original = {"nested": {"value": 1}, "items": ["a"]}

        await backend.save("k1", original)
        original["nested"]["value"] = 2
        original["items"].append("b")

        loaded = await backend.load("k1")
        assert loaded == {"nested": {"value": 1}, "items": ["a"]}

        assert loaded is not None
        loaded["nested"]["value"] = 3
        loaded["items"].append("c")

        reloaded = await backend.load("k1")
        assert reloaded == {"nested": {"value": 1}, "items": ["a"]}


# ---------------------------------------------------------------------------
# SqliteSessionBackend
# ---------------------------------------------------------------------------


class TestSqliteSessionBackend:
    """SqliteSessionBackend — full CRUD + persistence."""

    @pytest.fixture
    def db_path(self, tmp_path: Any) -> str:
        return str(tmp_path / "sessions.db")

    @pytest.mark.asyncio
    async def test_save_and_load(self, db_path: str) -> None:
        backend = SqliteSessionBackend(db_path=db_path)
        state = {"role": "coach", "counter": 1}
        await backend.save("k1", state)
        loaded = await backend.load("k1")
        assert loaded == state
        backend.close()

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self, db_path: str) -> None:
        backend = SqliteSessionBackend(db_path=db_path)
        assert await backend.load("nonexistent") is None
        backend.close()

    @pytest.mark.asyncio
    async def test_save_overwrites(self, db_path: str) -> None:
        backend = SqliteSessionBackend(db_path=db_path)
        await backend.save("k1", {"v": 1})
        await backend.save("k1", {"v": 2})
        loaded = await backend.load("k1")
        assert loaded == {"v": 2}
        backend.close()

    @pytest.mark.asyncio
    async def test_delete_existing_returns_true(self, db_path: str) -> None:
        backend = SqliteSessionBackend(db_path=db_path)
        await backend.save("k1", {"v": 1})
        result = await backend.delete("k1")
        assert result is True
        assert await backend.load("k1") is None
        backend.close()

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, db_path: str) -> None:
        backend = SqliteSessionBackend(db_path=db_path)
        result = await backend.delete("missing")
        assert result is False
        backend.close()

    @pytest.mark.asyncio
    async def test_list_keys(self, db_path: str) -> None:
        backend = SqliteSessionBackend(db_path=db_path)
        await backend.save("x", {"a": 1})
        await backend.save("y", {"b": 2})
        keys = await backend.list_keys()
        assert sorted(keys) == ["x", "y"]
        backend.close()

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, db_path: str) -> None:
        """Data persists when backend is closed and reopened with same db."""
        backend1 = SqliteSessionBackend(db_path=db_path)
        await backend1.save("persist_key", {"data": "survives"})
        backend1.close()

        backend2 = SqliteSessionBackend(db_path=db_path)
        loaded = await backend2.load("persist_key")
        assert loaded == {"data": "survives"}
        backend2.close()

    @pytest.mark.asyncio
    async def test_concurrent_access_does_not_raise(self, db_path: str) -> None:
        backend = SqliteSessionBackend(db_path=db_path)

        async def worker(index: int) -> None:
            key = f"k{index % 5}"
            await backend.save(key, {"i": index})
            await backend.load(key)
            await backend.list_keys()
            if index % 7 == 0:
                await backend.delete(key)

        await asyncio.gather(*(worker(index) for index in range(200)))
        backend.close()


class TestSessionKey:
    def test_string_serialization_avoids_delimiter_collisions(self) -> None:
        first = SessionKey(user_id="a:b", topic_id="c")
        second = SessionKey(user_id="a", topic_id="b:c")

        assert str(first) != str(second)


# ---------------------------------------------------------------------------
# Agent isolation via scoped keys
# ---------------------------------------------------------------------------


class TestAgentIsolation:
    """Different scopes produce isolated namespaces."""

    @pytest.mark.asyncio
    async def test_scope_isolation_inmemory(self) -> None:
        backend = InMemorySessionBackend()
        global_key = scoped_key(MemoryScope.GLOBAL, "session:1")
        agent_key = scoped_key(MemoryScope.AGENT, "session:1")

        await backend.save(global_key, {"scope": "global"})
        await backend.save(agent_key, {"scope": "agent"})

        assert (await backend.load(global_key))["scope"] == "global"
        assert (await backend.load(agent_key))["scope"] == "agent"

    @pytest.mark.asyncio
    async def test_scope_isolation_sqlite(self, tmp_path: Any) -> None:
        db = str(tmp_path / "iso.db")
        backend = SqliteSessionBackend(db_path=db)
        global_key = scoped_key(MemoryScope.GLOBAL, "session:1")
        agent_key = scoped_key(MemoryScope.AGENT, "session:1")

        await backend.save(global_key, {"scope": "global"})
        await backend.save(agent_key, {"scope": "agent"})

        assert (await backend.load(global_key))["scope"] == "global"
        assert (await backend.load(agent_key))["scope"] == "agent"
        backend.close()
