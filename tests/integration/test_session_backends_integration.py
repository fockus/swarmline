"""Integration tests for session backends with SessionManager (Phase 8A)."""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.session.backends import (
    InMemorySessionBackend,
    MemoryScope,
    SqliteSessionBackend,
    scoped_key,
)
from swarmline.session.manager import InMemorySessionManager
from swarmline.session.types import SessionKey, SessionState


def _make_state(
    user_id: str = "u1",
    topic_id: str = "t1",
    role_id: str = "coach",
) -> SessionState:
    return SessionState(
        key=SessionKey(user_id=user_id, topic_id=topic_id),
        role_id=role_id,
    )


class TestSessionManagerWithInMemoryBackend:
    """SessionManager + InMemorySessionBackend full flow."""

    @pytest.mark.asyncio
    async def test_full_flow(self) -> None:
        backend = InMemorySessionBackend()
        mgr = InMemorySessionManager(backend=backend)

        state = _make_state()
        mgr.register(state)
        assert mgr.get(SessionKey("u1", "t1")) is state

        # Backend should have received the state via register
        assert mgr.list_sessions() == [SessionKey("u1", "t1")]

        await mgr.close(SessionKey("u1", "t1"))
        assert mgr.get(SessionKey("u1", "t1")) is None


class TestSessionManagerWithSqliteBackend:
    """SessionManager + SqliteSessionBackend full flow."""

    @pytest.mark.asyncio
    async def test_full_flow(self, tmp_path: Any) -> None:
        db = str(tmp_path / "mgr.db")
        backend = SqliteSessionBackend(db_path=db)
        mgr = InMemorySessionManager(backend=backend)

        state = _make_state()
        mgr.register(state)
        assert mgr.get(SessionKey("u1", "t1")) is state
        assert len(mgr.list_sessions()) == 1

        await mgr.close(SessionKey("u1", "t1"))
        assert mgr.get(SessionKey("u1", "t1")) is None
        backend.close()

    @pytest.mark.asyncio
    async def test_lazy_restore_rehydrates_snapshot_without_live_runtime(self, tmp_path: Any) -> None:
        db = str(tmp_path / "rehydrate.db")
        backend = SqliteSessionBackend(db_path=db)
        mgr = InMemorySessionManager(backend=backend)

        state = _make_state()
        state.system_prompt = "system"
        state.active_skill_ids = ["skill-1"]
        mgr.register(state)

        restored_mgr = InMemorySessionManager(backend=backend)
        restored = restored_mgr.get(SessionKey("u1", "t1"))

        assert restored is not None
        assert restored.is_rehydrated is True
        assert restored.runtime is None
        assert restored.adapter is None
        assert restored.runtime_config is None
        assert restored.system_prompt == "system"
        assert restored.active_skill_ids == ["skill-1"]

        await restored_mgr.close(SessionKey("u1", "t1"))
        assert await backend.load(str(SessionKey("u1", "t1"))) is None
        backend.close()

    @pytest.mark.asyncio
    async def test_close_all_keeps_snapshot_for_later_rehydration(self, tmp_path: Any) -> None:
        db = str(tmp_path / "close_all_persist.db")
        backend = SqliteSessionBackend(db_path=db)
        mgr = InMemorySessionManager(backend=backend)

        state = _make_state()
        state.system_prompt = "system"
        state.active_skill_ids = ["skill-1"]
        mgr.register(state)

        await mgr.close_all()

        restored_mgr = InMemorySessionManager(backend=backend)
        restored = restored_mgr.get(SessionKey("u1", "t1"))

        assert restored is not None
        assert restored.is_rehydrated is True
        assert restored.system_prompt == "system"
        assert restored.active_skill_ids == ["skill-1"]

        await restored_mgr.close(SessionKey("u1", "t1"))
        backend.close()

    @pytest.mark.asyncio
    async def test_delimiter_containing_session_keys_do_not_collide(self, tmp_path: Any) -> None:
        db = str(tmp_path / "collisions.db")
        backend = SqliteSessionBackend(db_path=db)
        mgr = InMemorySessionManager(backend=backend)

        first = _make_state(user_id="a:b", topic_id="c", role_id="first")
        second = _make_state(user_id="a", topic_id="b:c", role_id="second")
        mgr.register(first)
        mgr.register(second)

        restored_first = mgr.get(SessionKey("a:b", "c"))
        restored_second = mgr.get(SessionKey("a", "b:c"))

        assert restored_first is not None
        assert restored_second is not None
        assert restored_first.role_id == "first"
        assert restored_second.role_id == "second"
        assert len(await backend.list_keys()) == 2

        await mgr.close(SessionKey("a:b", "c"))
        await mgr.close(SessionKey("a", "b:c"))
        backend.close()


class TestSessionManagerBackwardCompat:
    """SessionManager without backend arg works as before (backward compat)."""

    @pytest.mark.asyncio
    async def test_no_backend_works(self) -> None:
        mgr = InMemorySessionManager()
        state = _make_state()
        mgr.register(state)
        assert mgr.get(SessionKey("u1", "t1")) is state
        await mgr.close(SessionKey("u1", "t1"))
        assert mgr.get(SessionKey("u1", "t1")) is None


class TestCrossScopeIsolation:
    """Agent scope vs global scope produce isolated data."""

    @pytest.mark.asyncio
    async def test_cross_scope_isolation(self) -> None:
        backend = InMemorySessionBackend()
        base_key = "session:user1:topic1"

        global_key = scoped_key(MemoryScope.GLOBAL, base_key)
        agent_key = scoped_key(MemoryScope.AGENT, base_key)
        shared_key = scoped_key(MemoryScope.SHARED, base_key)

        await backend.save(global_key, {"level": "global"})
        await backend.save(agent_key, {"level": "agent"})
        await backend.save(shared_key, {"level": "shared"})

        assert (await backend.load(global_key))["level"] == "global"
        assert (await backend.load(agent_key))["level"] == "agent"
        assert (await backend.load(shared_key))["level"] == "shared"

        # Deleting one scope does not affect others
        await backend.delete(global_key)
        assert await backend.load(global_key) is None
        assert await backend.load(agent_key) is not None


class TestSqlitePersistenceAcrossInstances:
    """SQLite backend preserves state across close/reopen."""

    @pytest.mark.asyncio
    async def test_create_close_reopen(self, tmp_path: Any) -> None:
        db = str(tmp_path / "persist.db")

        b1 = SqliteSessionBackend(db_path=db)
        await b1.save("sess:1", {"role": "coach", "turn": 5})
        await b1.save("sess:2", {"role": "advisor", "turn": 3})
        b1.close()

        b2 = SqliteSessionBackend(db_path=db)
        assert (await b2.load("sess:1")) == {"role": "coach", "turn": 5}
        assert (await b2.load("sess:2")) == {"role": "advisor", "turn": 3}
        keys = await b2.list_keys()
        assert sorted(keys) == ["sess:1", "sess:2"]
        b2.close()


class TestBackendSwap:
    """Start with InMemory, switch to Sqlite — data migration pattern."""

    @pytest.mark.asyncio
    async def test_swap_backends(self, tmp_path: Any) -> None:
        # Start with InMemory
        mem_backend = InMemorySessionBackend()
        await mem_backend.save("k1", {"data": "original"})

        # "Migrate" to SQLite
        db = str(tmp_path / "swap.db")
        sqlite_backend = SqliteSessionBackend(db_path=db)

        # Transfer data
        for key in await mem_backend.list_keys():
            state = await mem_backend.load(key)
            if state is not None:
                await sqlite_backend.save(key, state)

        # Verify in new backend
        loaded = await sqlite_backend.load("k1")
        assert loaded == {"data": "original"}
        sqlite_backend.close()
