"""Тесты для InMemorySessionManager — управление сессиями агента."""

import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from cognitia.runtime.types import Message, RuntimeEvent, ToolSpec
from cognitia.session.manager import InMemorySessionManager
from cognitia.session.types import SessionKey, SessionState


def _make_adapter(connected: bool = True, events: list[Any] | None = None) -> MagicMock:
    """Создать мок RuntimePort."""
    adapter = MagicMock()
    type(adapter).is_connected = PropertyMock(return_value=connected)
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()

    async def _stream_reply(user_text: str) -> AsyncIterator[Any]:
        for e in (events or []):
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
    return SessionState(key=key, adapter=adapter, role_id=role_id)


class _FakeRuntime:
    """Минимальная реализация AgentRuntime для тестов SessionManager.run_turn()."""

    def __init__(self, events: list[RuntimeEvent]) -> None:
        self._events = events
        self.calls: list[dict[str, Any]] = []
        self.cleanup = AsyncMock()

    async def run(self, **kwargs: Any):  # type: ignore[override]
        self.calls.append(kwargs)
        for event in self._events:
            yield event


class TestRegisterAndGet:
    """Регистрация и получение сессий."""

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
    """list_sessions — активные сессии."""

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
    """update_role — обновление роли сессии."""

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


class TestClose:
    """close / close_all — закрытие сессий."""

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


class TestStreamReply:
    """stream_reply — стриминг ответа через адаптер."""

    @pytest.mark.asyncio
    async def test_stream_no_session_yields_error(self) -> None:
        """Отсутствующая сессия → ошибка."""
        mgr = InMemorySessionManager()
        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)
        assert len(events) == 1
        assert events[0].type == "error"
        assert "не найдена" in events[0].text

    @pytest.mark.asyncio
    async def test_stream_disconnected_yields_error(self) -> None:
        """Отключённый адаптер → ошибка."""
        mgr = InMemorySessionManager()
        mgr.register(_make_state(connected=False))
        events = []
        async for event in mgr.stream_reply(SessionKey("u1", "t1"), "привет"):
            events.append(event)
        assert len(events) == 1
        assert "не подключён" in events[0].text

    @pytest.mark.asyncio
    async def test_stream_forwards_events(self) -> None:
        """Подключённый адаптер → события прокидываются."""
        from cognitia.runtime.adapter import StreamEvent

        test_events = [
            StreamEvent(type="text_delta", text="Привет!"),
            StreamEvent(type="done", text="Привет!", is_final=True),
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
        """Legacy runtime path передаёт накопленную историю между turn'ами."""
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


class TestRunTurn:
    """run_turn — новый контракт AgentRuntime v1."""

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
        assert "не найдена" in events[0].data["message"]

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


class TestSessionTTL:
    """TTL eviction — сессия протухает после N секунд неактивности."""

    def test_session_state_has_last_activity_at(self) -> None:
        """Поле last_activity_at существует и заполняется при создании."""
        state = _make_state()
        assert hasattr(state, "last_activity_at")
        assert isinstance(state.last_activity_at, float)
        assert state.last_activity_at > 0

    def test_get_returns_none_for_expired_session(self) -> None:
        """get() возвращает None для протухшей сессии (TTL истёк)."""
        mgr = InMemorySessionManager(ttl_seconds=1.0)
        state = _make_state()
        mgr.register(state)
        # Сдвигаем last_activity_at в прошлое
        state.last_activity_at = time.monotonic() - 10.0
        result = mgr.get(SessionKey("u1", "t1"))
        assert result is None

    def test_get_returns_session_within_ttl(self) -> None:
        """get() возвращает сессию до истечения TTL."""
        mgr = InMemorySessionManager(ttl_seconds=600.0)
        state = _make_state()
        mgr.register(state)
        result = mgr.get(SessionKey("u1", "t1"))
        assert result is state

    @pytest.mark.asyncio
    async def test_run_turn_updates_last_activity(self) -> None:
        """run_turn() обновляет last_activity_at при каждом turn'е."""
        mgr = InMemorySessionManager(ttl_seconds=600.0)
        fake_runtime = _FakeRuntime([RuntimeEvent.final("ok")])
        state = SessionState(
            key=SessionKey("u1", "t1"),
            runtime=fake_runtime,
            role_id="coach",
        )
        mgr.register(state)
        old_ts = state.last_activity_at

        # Небольшая задержка чтобы monotonic сдвинулся
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
        """TTL=0 отключает проверку: сессия живёт вечно."""
        mgr = InMemorySessionManager(ttl_seconds=0)
        state = _make_state()
        mgr.register(state)
        # Сдвигаем last_activity_at далеко в прошлое
        state.last_activity_at = time.monotonic() - 999999.0
        result = mgr.get(SessionKey("u1", "t1"))
        assert result is state
