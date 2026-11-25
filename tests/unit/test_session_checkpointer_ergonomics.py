"""Ergonomics tests for SessionManager acheckpoint/arestore + SessionBackendCheckpointer.

Covers REQ-012..016 of the checkpointer-protocol spec: opt-in checkpoint/restore
on SessionManager (byte-identical when no checkpointer is configured), and
SessionBackendCheckpointer as a single-latest adapter over an existing
SessionBackend.
"""

from __future__ import annotations

from swarmline.protocols import Checkpointer
from swarmline.session import InMemoryCheckpointer, InMemorySessionBackend
from swarmline.session.manager import InMemorySessionManager
from swarmline.session.session_backend_checkpointer import SessionBackendCheckpointer
from swarmline.session.types import SessionKey, SessionState


def _make_state(
    user_id: str = "u1", topic_id: str = "t1", role_id: str = "coach"
) -> SessionState:
    return SessionState(
        key=SessionKey(user_id=user_id, topic_id=topic_id),
        role_id=role_id,
        active_skill_ids=["skill-a", "skill-b"],
    )


# ---------------------------------------------------------------------------
# REQ-015: no checkpointer configured -> byte-identical, no-op checkpoint API
# ---------------------------------------------------------------------------


class TestManagerWithoutCheckpointer:
    async def test_manager_without_checkpointer_acheckpoint_returns_none(self) -> None:
        manager = InMemorySessionManager()
        state = _make_state()
        await manager.aregister(state)

        result = await manager.acheckpoint(state.key)

        assert result is None

    async def test_manager_without_checkpointer_arestore_returns_false(self) -> None:
        manager = InMemorySessionManager()
        key = SessionKey(user_id="u1", topic_id="t1")

        result = await manager.arestore(key)

        assert result is False

    async def test_manager_without_checkpointer_existing_behavior_unchanged(
        self,
    ) -> None:
        manager = InMemorySessionManager()
        state = _make_state()

        await manager.aregister(state)
        fetched = await manager.aget(state.key)

        assert fetched is not None
        assert fetched.role_id == "coach"
        assert fetched.active_skill_ids == ["skill-a", "skill-b"]


# ---------------------------------------------------------------------------
# REQ-014/016: opt-in checkpoint/restore round-trip
# ---------------------------------------------------------------------------


class TestCheckpointRestoreRoundTrip:
    async def test_acheckpoint_then_arestore_round_trips_session_state(self) -> None:
        checkpointer = InMemoryCheckpointer()
        manager = InMemorySessionManager(checkpointer=checkpointer)
        state = _make_state(role_id="tutor")
        await manager.aregister(state)

        cid = await manager.acheckpoint(state.key)
        assert cid is not None

        # Overwrite the live session so restore must actually replace it.
        await manager.aregister(_make_state(role_id="other", user_id="u1"))

        restored = await manager.arestore(state.key)
        assert restored is True

        fetched = await manager.aget(state.key)
        assert fetched is not None
        assert fetched.role_id == "tutor"
        assert fetched.active_skill_ids == ["skill-a", "skill-b"]
        assert fetched.runtime_messages == []

    async def test_acheckpoint_missing_session_returns_none(self) -> None:
        checkpointer = InMemoryCheckpointer()
        manager = InMemorySessionManager(checkpointer=checkpointer)
        key = SessionKey(user_id="ghost", topic_id="t1")

        result = await manager.acheckpoint(key)

        assert result is None

    async def test_arestore_missing_checkpoint_returns_false(self) -> None:
        checkpointer = InMemoryCheckpointer()
        manager = InMemorySessionManager(checkpointer=checkpointer)
        key = SessionKey(user_id="u1", topic_id="never-checkpointed")

        result = await manager.arestore(key)

        assert result is False

    async def test_acheckpoint_defaults_resource_id_to_user_id(self) -> None:
        checkpointer = InMemoryCheckpointer()
        manager = InMemorySessionManager(checkpointer=checkpointer)
        state = _make_state(user_id="user-42")
        await manager.aregister(state)

        await manager.acheckpoint(state.key)

        history = await checkpointer.list(str(state.key))
        assert history[0].resource_id == "user-42"

        await manager.acheckpoint(state.key, resource_id="explicit-id")

        history = await checkpointer.list(str(state.key))
        assert history[-1].resource_id == "explicit-id"

    async def test_acheckpoint_thread_id_is_session_key_str(self) -> None:
        checkpointer = InMemoryCheckpointer()
        manager = InMemorySessionManager(checkpointer=checkpointer)
        state = _make_state()
        await manager.aregister(state)

        await manager.acheckpoint(state.key)

        history = await checkpointer.list(str(state.key))
        assert len(history) == 1


# ---------------------------------------------------------------------------
# C1.3: time-travel ergonomics — SessionManager.aget_state_history / afork
# ---------------------------------------------------------------------------


class TestSessionManagerTimeTravelErgonomics:
    async def test_session_manager_without_checkpointer_history_is_empty(
        self,
    ) -> None:
        manager = InMemorySessionManager()
        key = SessionKey(user_id="u1", topic_id="t1")

        assert await manager.aget_state_history(key) == []
        assert await manager.afork(key, checkpoint_id="anything") is None

    async def test_session_manager_afork_branches_from_checkpoint(self) -> None:
        checkpointer = InMemoryCheckpointer()
        manager = InMemorySessionManager(checkpointer=checkpointer)
        state = _make_state()
        await manager.aregister(state)

        first = await manager.acheckpoint(state.key)
        await manager.acheckpoint(state.key)
        assert first is not None

        forked_id = await manager.afork(state.key, checkpoint_id=first)

        assert forked_id is not None
        assert forked_id != first
        forked = await checkpointer.get(str(state.key), checkpoint_id=forked_id)
        assert forked is not None
        assert forked.parent_id == first


# ---------------------------------------------------------------------------
# REQ-012/013: SessionBackendCheckpointer — single-latest adapter
# ---------------------------------------------------------------------------


class TestSessionBackendCheckpointer:
    async def test_session_backend_checkpointer_is_checkpointer(self) -> None:
        backend = InMemorySessionBackend()
        adapter = SessionBackendCheckpointer(backend)

        assert isinstance(adapter, Checkpointer)

        cid = await adapter.put("thread-1", {"a": 1})
        cp = await adapter.get("thread-1", checkpoint_id=cid)
        assert cp is not None
        assert cp.state == {"a": 1}

        deleted = await adapter.delete("thread-1")
        assert deleted == 1
        assert await adapter.get("thread-1") is None

    async def test_session_backend_checkpointer_list_returns_at_most_one(
        self,
    ) -> None:
        backend = InMemorySessionBackend()
        adapter = SessionBackendCheckpointer(backend)

        assert await adapter.list("thread-empty") == []

        await adapter.put("thread-1", {"a": 1})
        await adapter.put("thread-1", {"a": 2})  # overwrite-latest, no history

        history = await adapter.list("thread-1")
        assert len(history) == 1
