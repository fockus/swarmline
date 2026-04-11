"""Tests for InMemorySessionManager - upravlenie sessionmi agent."""

import time
import warnings
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from swarmline.runtime.types import Message, RuntimeEvent, ToolSpec
from swarmline.session.backends import InMemorySessionBackend
from swarmline.session.manager import InMemorySessionManager
from swarmline.session.types import SessionKey, SessionState
from conftest import FakeStreamEvent


def _make_adapter(connected: bool = True, events: list[Any] | None = None) -> MagicMock:
    """Create mock RuntimePort."""
    adapter = MagicMock()
    type(adapter).is_connected = PropertyMock(return_value=connected)
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()

    async def _stream_reply(user_text: str) -> AsyncIterator[Any]:
        for e in events or []:
            yield e

    adapter.stream_reply = _stream_reply
    return adapter


def _make_state(
    user_id: str = "u1",
    topic_id: str = "t1",
    role_id: str = "coach",
    connected: bool = True,
    events: list[Any] | None = None,
) -> SessionState:
    key = SessionKey(user_id=user_id, topic_id=topic_id)
    adapter = _make_adapter(connected=connected, events=events)
    # Suppress DeprecationWarning — this is intentional legacy-path testing
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return SessionState(key=key, adapter=adapter, role_id=role_id)


class _FakeRuntime:
    """Minimal implementation AgentRuntime for testov SessionManager.run_turn()."""

    def __init__(self, events: list[RuntimeEvent]) -> None:
        self._events = events
        self.calls: list[dict[str, Any]] = []
        self.cleanup = AsyncMock()

    async def run(self, **kwargs: Any):  # type: ignore[override]
        self.calls.append(kwargs)
        for event in self._events:
            yield event


class TestRegisterAndGet:
    """Registratsiya and receiving sessiy."""

    def test_get_nonexistent_returns_none(self) -> None:
        mgr = InMemorySessionManager()
        assert mgr.get(SessionKey("u1", "t1")) is None

    def test_register_and_get(self) -> None:
        mgr = InMemorySessionManager()
        state = _make_state()
        mgr.register(state)
        result = mgr.get(SessionKey("u1", "t1"))
        assert result is state

    def test_register_overwrites(self) -> None:
        mgr = InMemorySessionManager()
        s1 = _make_state(role_id="coach")
        s2 = _make_state(role_id="diagnostician")
        mgr.register(s1)
        mgr.register(s2)
        assert mgr.get(SessionKey("u1", "t1")).role_id == "diagnostician"


class TestListSessions:
    """list_sessions - active sessions."""

    def test_empty(self) -> None:
        mgr = InMemorySessionManager()
        assert mgr.list_sessions() == []

    def test_lists_all(self) -> None:
        mgr = InMemorySessionManager()
        mgr.register(_make_state(user_id="u1", topic_id="t1"))
        mgr.register(_make_state(user_id="u1", topic_id="t2"))
        keys = mgr.list_sessions()
        assert len(keys) == 2


class TestUpdateRole:
    """update_role - update roli sessions."""

    def test_update_existing(self) -> None:
        mgr = InMemorySessionManager()
        mgr.register(_make_state())
        result = mgr.update_role(SessionKey("u1", "t1"), "diagnostician", ["iss"])
        assert result is True
        state = mgr.get(SessionKey("u1", "t1"))
        assert state.role_id == "diagnostician"
        assert state.active_skill_ids == ["iss"]

    def test_update_nonexistent(self) -> None:
        mgr = InMemorySessionManager()
        result = mgr.update_role(SessionKey("u1", "t1"), "coach", [])
        assert result is False

    @pytest.mark.asyncio
    async def test_update_role_persists_snapshot_to_backend(self) -> None:
        backend = InMemorySessionBackend()
        mgr = InMemorySessionManager(backend=backend)
        mgr.register(_make_state())

        assert mgr.update_role(SessionKey("u1", "t1"), "diagnostician", ["iss"]) is True

        payload = await backend.load(str(SessionKey("u1", "t1")))
        assert payload is not None
        assert payload["role_id"] == "diagnostician"
        assert payload["active_skill_ids"] == ["iss"]


class TestClose:
    """close / close_all - zakrytie sessiy."""

    @pytest.mark.asyncio
    async def test_close_disconnects_adapter(self) -> None:
        mgr = InMemorySessionManager()
        state = _make_state()
        mgr.register(state)
        await mgr.close(SessionKey("u1", "t1"))
        state.adapter.disconnect.assert_awaited_once()
        assert mgr.get(SessionKey("u1", "t1")) is None

    @pytest.mark.asyncio
    async def test_close_nonexistent_no_error(self) -> None:
        mgr = InMemorySessionManager()
        await mgr.close(SessionKey("u1", "t_missing"))

    @pytest.mark.asyncio
    async def test_close_already_disconnected(self) -> None:
        mgr = InMemorySessionManager()
        state = _make_state(connected=False)
        mgr.register(state)
        await mgr.close(SessionKey("u1", "t1"))
        state.adapter.disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_all(self) -> None:
        mgr = InMemorySessionManager()
        s1 = _make_state(user_id="u1", topic_id="t1")
        s2 = _make_state(user_id="u2", topic_id="t2")
        mgr.register(s1)
        mgr.register(s2)
        await mgr.close_all()
        assert mgr.list_sessions() == []
        s1.adapter.disconnect.assert_awaited_once()
        s2.adapter.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_preserves_backend_snapshots(self) -> None:
        backend = InMemorySessionBackend()
        mgr = InMemorySessionManager(backend=backend)
        mgr.register(_make_state())

        await mgr.close_all()

        payload = await backend.load(str(SessionKey("u1", "t1")))
        assert payload is not None
        assert payload["role_id"] == "coach"


class TestStreamReply:
    """stream_reply - striming responsea cherez adapter."""

    @pytest.mark.asyncio
    async def test_stream_no_session_yields_error(self) -> None:
        """Otsutstvuyushchaya session -> error."""
        mgr = InMemorySessionManager()
        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)
        assert len(events) == 1
        assert events[0].type == "error"
        assert "not found" in events[0].text.lower()

    @pytest.mark.asyncio
    async def test_stream_disconnected_yields_error(self) -> None:
        """Otklyuchennyy adapter -> error."""
        mgr = InMemorySessionManager()
        mgr.register(_make_state(connected=False))
        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)
        assert len(events) == 1
        assert "not connected" in events[0].text.lower()

    @pytest.mark.asyncio
    async def test_stream_forwards_events(self) -> None:
        """Connectednyy adapter -> events prokidyvayutsya."""
        test_events = [
            FakeStreamEvent("text_delta", text="Привет!"),
            FakeStreamEvent("done", text="Привет!", is_final=True),
        ]
        mgr = InMemorySessionManager()
        mgr.register(_make_state(events=test_events))
        collected = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            collected.append(event)
        assert len(collected) == 2
        assert collected[0].type == "text_delta"
        assert collected[1].type == "done"

    @pytest.mark.asyncio
    async def test_stream_runtime_path_preserves_history(self) -> None:
        """Legacy runtime path passes nakoplennuyu istoriyu mezhdu turn'ami."""
        mgr = InMemorySessionManager()
        fake_runtime = _FakeRuntime([RuntimeEvent.final("ok")])
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            system_prompt="system",
            active_tools=[],
            role_id="coach",
        )
        mgr.register(state)

        first_events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            first_events.append(event)
        assert any(e.type == "done" for e in first_events)
        assert len(fake_runtime.calls) == 1
        first_messages = fake_runtime.calls[0]["messages"]
        assert [m.role for m in first_messages] == ["user"]
        assert [m.content for m in first_messages] == ["привет"]

        second_events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "как дела?"):
            second_events.append(event)
        assert any(e.type == "done" for e in second_events)
        assert len(fake_runtime.calls) == 2
        second_messages = fake_runtime.calls[1]["messages"]
        assert [m.role for m in second_messages] == ["user", "assistant", "user"]
        assert [m.content for m in second_messages] == ["привет", "ok", "как дела?"]

    @pytest.mark.asyncio
    async def test_stream_runtime_path_preserves_final_metadata(self) -> None:
        """final metadata not teryaetsya in StreamEvent(done)."""
        mgr = InMemorySessionManager()
        fake_runtime = _FakeRuntime(
            [
                RuntimeEvent.final(
                    "ok",
                    session_id="session-1",
                    total_cost_usd=1.25,
                    usage={"input_tokens": 7, "output_tokens": 2},
                    structured_output={"answer": 42},
                    native_metadata={"provider": "thin"},
                )
            ]
        )
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            system_prompt="system",
            active_tools=[],
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)

        done_events = [event for event in events if event.type == "done"]
        assert len(done_events) == 1
        done = done_events[0]
        assert done.session_id == "session-1"
        assert done.total_cost_usd == 1.25
        assert done.usage == {"input_tokens": 7, "output_tokens": 2}
        assert done.structured_output == {"answer": 42}
        assert done.native_metadata == {"provider": "thin"}

    @pytest.mark.asyncio
    async def test_stream_runtime_path_preserves_final_new_messages_in_history(self) -> None:
        """canonical final.new_messages should savesya in session history."""
        mgr = InMemorySessionManager()
        fake_runtime = _FakeRuntime(
            [
                RuntimeEvent.assistant_delta("Final answer"),
                RuntimeEvent.final(
                    "Final answer",
                    new_messages=[
                        Message(role="assistant", content="Thinking"),
                        Message(role="tool", content="42", name="calc"),
                        Message(role="assistant", content="Final answer"),
                    ],
                ),
            ]
        )
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            system_prompt="system",
            active_tools=[],
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)

        assert [event.type for event in events] == ["text_delta", "done"]
        assert [m.role for m in state.runtime_messages] == ["user", "assistant", "tool", "assistant"]
        assert [m.content for m in state.runtime_messages[1:]] == [
            "Thinking",
            "42",
            "Final answer",
        ]
        assert state.runtime_messages[2].name == "calc"

    @pytest.mark.asyncio
    async def test_stream_runtime_path_without_terminal_event_yields_error(self) -> None:
        """silent EOF in runtime path not should schitatsya uspeshnym done."""
        mgr = InMemorySessionManager()
        fake_runtime = _FakeRuntime([RuntimeEvent.assistant_delta("partial")])
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            system_prompt="system",
            active_tools=[],
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)

        assert [event.type for event in events] == ["text_delta", "error"]
        assert "without final RuntimeEvent" in events[-1].text
        assert [m.role for m in state.runtime_messages] == ["user"]

    @pytest.mark.asyncio
    async def test_stream_runtime_path_persists_history_to_backend(self) -> None:
        backend = InMemorySessionBackend()
        mgr = InMemorySessionManager(backend=backend)
        fake_runtime = _FakeRuntime(
            [
                RuntimeEvent.final(
                    "ok",
                    new_messages=[
                        Message(role="assistant", content="Thinking"),
                        Message(role="tool", content="4", name="calc"),
                        Message(role="assistant", content="ok"),
                    ],
                )
            ]
        )
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            runtime_config=MagicMock(),
            system_prompt="system",
            active_tools=[ToolSpec(name="calc", description="d", parameters={})],
            role_id="coach",
            active_skill_ids=["skill-1"],
        )
        mgr.register(state)

        async for _ in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            pass

        restored_mgr = InMemorySessionManager(backend=backend)
        restored = restored_mgr.get(SessionKey("u1", "t1"))
        assert restored is not None
        assert restored.is_rehydrated is True
        assert restored.runtime is None
        assert restored.adapter is None
        assert restored.runtime_config is None
        assert [m.role for m in restored.runtime_messages] == ["user", "assistant", "tool", "assistant"]
        assert [m.content for m in restored.runtime_messages] == ["привет", "Thinking", "4", "ok"]
        assert restored.runtime_messages[2].name == "calc"
        assert restored.active_skill_ids == ["skill-1"]
        assert restored.active_tools[0].name == "calc"

    @pytest.mark.asyncio
    async def test_stream_runtime_exception_yields_error_without_persisting_partial_history(self) -> None:
        class BrokenRuntime:
            async def run(self, **kwargs: Any):
                raise RuntimeError("boom-runtime")
                yield  # pragma: no cover

            async def cleanup(self) -> None:
                return None

        mgr = InMemorySessionManager()
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=BrokenRuntime(),
            system_prompt="system",
            active_tools=[],
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)

        assert [event.type for event in events] == ["error"]
        assert "boom-runtime" in events[0].text
        assert [m.role for m in state.runtime_messages] == ["user"]


class TestRunTurn:
    """run_turn - new contract AgentRuntime v1."""

    @pytest.mark.asyncio
    async def test_run_turn_no_session_yields_error(self) -> None:
        mgr = InMemorySessionManager()
        events = []
        async for event in mgr.run_turn(
            SessionKey("u1", "t1"),
            messages=[Message(role="user", content="привет")],
            system_prompt="system",
            active_tools=[],
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0].type == "error"
        assert "not found" in events[0].data["message"].lower()

    @pytest.mark.asyncio
    async def test_run_turn_forwards_runtime_events(self) -> None:
        mgr = InMemorySessionManager()
        runtime_events = [
            RuntimeEvent.assistant_delta("ok"),
            RuntimeEvent.final("ok", new_messages=[Message(role="assistant", content="ok")]),
        ]
        fake_runtime = _FakeRuntime(runtime_events)
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.run_turn(
            SessionKey("u1", "t1"),
            messages=[Message(role="user", content="привет")],
            system_prompt="system",
            active_tools=[ToolSpec(name="calc", description="d", parameters={})],
        ):
            events.append(event)

        assert [e.type for e in events] == ["assistant_delta", "final"]
        assert len(fake_runtime.calls) == 1
        assert fake_runtime.calls[0]["system_prompt"] == "system"

    @pytest.mark.asyncio
    async def test_run_turn_runtime_exception_without_partial_yields_error_event(self) -> None:
        class BrokenRuntime:
            async def run(self, **kwargs: Any):
                raise RuntimeError("boom-runtime")
                yield  # pragma: no cover

            async def cleanup(self) -> None:
                return None

        mgr = InMemorySessionManager()
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=BrokenRuntime(),
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.run_turn(
            SessionKey("u1", "t1"),
            messages=[Message(role="user", content="привет")],
            system_prompt="system",
            active_tools=[],
        ):
            events.append(event)

        assert [event.type for event in events] == ["error"]
        assert events[0].data["kind"] == "runtime_crash"
        assert "boom-runtime" in events[0].data["message"]

    @pytest.mark.asyncio
    async def test_run_turn_runtime_exception_yields_error_event(self) -> None:
        mgr = InMemorySessionManager()

        class BrokenRuntime:
            def __init__(self) -> None:
                self.cleanup = AsyncMock()

            async def run(self, **kwargs: Any):
                yield RuntimeEvent.assistant_delta("partial")
                raise RuntimeError("boom-runtime")

        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=BrokenRuntime(),
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.run_turn(
            SessionKey("u1", "t1"),
            messages=[Message(role="user", content="привет")],
            system_prompt="system",
            active_tools=[],
        ):
            events.append(event)

        assert [event.type for event in events] == ["assistant_delta", "error"]
        assert events[-1].data["kind"] == "runtime_crash"
        assert "boom-runtime" in events[-1].data["message"]

    @pytest.mark.asyncio
    async def test_stream_runtime_exception_yields_error_without_persisting_partial_history(
        self,
    ) -> None:
        mgr = InMemorySessionManager()

        class BrokenRuntime:
            async def run(self, **kwargs: Any):
                yield RuntimeEvent.assistant_delta("partial")
                raise RuntimeError("boom-runtime")

        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=BrokenRuntime(),
            system_prompt="system",
            active_tools=[],
            role_id="coach",
        )
        mgr.register(state)

        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)

        assert [event.type for event in events] == ["text_delta", "error"]
        assert "boom-runtime" in events[-1].text
        assert [message.role for message in state.runtime_messages] == ["user"]
        assert state.runtime_messages[0].content == "привет"


class TestSessionTTL:
    """TTL eviction - session expires posle N sekund notaktivnosti."""

    def test_session_state_has_last_activity_at(self) -> None:
        """Pole last_activity_at sushchestvuet and zapolnyaetsya pri createdii."""
        state = _make_state()
        assert hasattr(state, "last_activity_at")
        assert isinstance(state.last_activity_at, float)
        assert state.last_activity_at > 0

    def test_get_returns_none_for_expired_session(self) -> None:
        """get() returns None for expired sessions (TTL istek)."""
        mgr = InMemorySessionManager(ttl_seconds=1.0)
        state = _make_state()
        mgr.register(state)
        # Sdvigaem last_activity_at in proshloe
        state.last_activity_at = time.monotonic() - 10.0
        result = mgr.get(SessionKey("u1", "t1"))
        assert result is None

    def test_get_returns_session_within_ttl(self) -> None:
        """get() returns sessiyu do istecheniya TTL."""
        mgr = InMemorySessionManager(ttl_seconds=600.0)
        state = _make_state()
        mgr.register(state)
        result = mgr.get(SessionKey("u1", "t1"))
        assert result is state

    @pytest.mark.asyncio
    async def test_run_turn_updates_last_activity(self) -> None:
        """run_turn() updates last_activity_at pri kazhdom turn'e."""
        mgr = InMemorySessionManager(ttl_seconds=600.0)
        fake_runtime = _FakeRuntime([RuntimeEvent.final("ok")])
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            role_id="coach",
        )
        mgr.register(state)
        old_ts = state.last_activity_at

        # Notbolshaya zaderzhka chtoby monotonic sdvinulsya
        import asyncio

        await asyncio.sleep(0.01)

        async for _ in mgr.run_turn(
            SessionKey("u1", "t1"),
            messages=[Message(role="user", content="привет")],
            system_prompt="system",
            active_tools=[],
        ):
            pass

        assert state.last_activity_at > old_ts

    def test_ttl_zero_disables_eviction(self) -> None:
        """TTL=0 otklyuchaet proverku: session zhivet vechno."""
        mgr = InMemorySessionManager(ttl_seconds=0)
        state = _make_state()
        mgr.register(state)
        # Sdvigaem last_activity_at daleko in proshloe
        state.last_activity_at = time.monotonic() - 999999.0
        result = mgr.get(SessionKey("u1", "t1"))
        assert result is state
