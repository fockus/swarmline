"""InMemorySessionManager — управление сессиями агента в памяти."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from cognitia.runtime import StreamEvent
from cognitia.runtime.types import Message, RuntimeErrorData, RuntimeEvent, ToolSpec
from cognitia.session.types import SessionKey, SessionState

logger = logging.getLogger(__name__)


class InMemorySessionManager:
    """Менеджер сессий (in-memory, для MVP).

    - Хранит активные сессии в dict
    - asyncio.Lock per SessionKey для последовательной обработки
    - TTL eviction: сессия считается протухшей после ttl_seconds неактивности
    """

    def __init__(self, ttl_seconds: float = 900.0) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._ttl_seconds = ttl_seconds

    def _key_str(self, key: SessionKey) -> str:
        return str(key)

    def _get_lock(self, key: SessionKey) -> asyncio.Lock:
        """Получить или создать lock для сессии."""
        ks = self._key_str(key)
        if ks not in self._locks:
            self._locks[ks] = asyncio.Lock()
        return self._locks[ks]

    def get(self, key: SessionKey) -> SessionState | None:
        """Получить существующую сессию. Возвращает None если TTL истёк."""
        ks = self._key_str(key)
        state = self._sessions.get(ks)
        if state is None:
            return None
        if self._ttl_seconds > 0 and (time.monotonic() - state.last_activity_at) > self._ttl_seconds:
            logger.info("get[%s]: сессия протухла (TTL=%.0fs), удаляю", ks, self._ttl_seconds)
            self._sessions.pop(ks, None)
            return None
        return state

    def register(self, state: SessionState) -> None:
        """Зарегистрировать новую сессию."""
        state.last_activity_at = time.monotonic()
        self._sessions[self._key_str(state.key)] = state

    async def close(self, key: SessionKey) -> None:
        """Закрыть сессию и отключить SDK."""
        ks = self._key_str(key)
        state = self._sessions.pop(ks, None)
        if state:
            if state.runtime is not None:
                await state.runtime.cleanup()
            elif state.adapter and state.adapter.is_connected:
                await state.adapter.disconnect()
        self._locks.pop(ks, None)

    async def close_all(self) -> None:
        """Закрыть все сессии."""
        keys = list(self._sessions.keys())
        for ks in keys:
            state = self._sessions.pop(ks, None)
            if state:
                if state.runtime is not None:
                    await state.runtime.cleanup()
                elif state.adapter and state.adapter.is_connected:
                    await state.adapter.disconnect()
        self._locks.clear()

    async def run_turn(
        self,
        key: SessionKey,
        *,
        messages: list[Message],
        system_prompt: str,
        active_tools: list[ToolSpec],
        mode_hint: str | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Выполнить turn через AgentRuntime v1 (новый контракт)."""
        ks = self._key_str(key)
        lock = self._get_lock(key)
        logger.info("run_turn[%s]: ожидание lock (locked=%s)", ks, lock.locked())
        async with lock:
            logger.info("run_turn[%s]: lock получен", ks)
            state = self.get(key)
            if state:
                state.last_activity_at = time.monotonic()
            if not state:
                logger.error("run_turn[%s]: сессия не найдена", ks)
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message="Сессия не найдена",
                        recoverable=False,
                    )
                )
                return

            if state.runtime is None:
                logger.error("run_turn[%s]: runtime is None", ks)
                yield RuntimeEvent.error(
                    RuntimeErrorData(
                        kind="runtime_crash",
                        message="Runtime не инициализирован в сессии",
                        recoverable=False,
                    )
                )
                return

            logger.info(
                "run_turn[%s]: вызов runtime.run() (type=%s, user_text_len=%d)",
                ks,
                type(state.runtime).__name__,
                len(messages[-1].content) if messages else 0,
            )
            event_count = 0
            async for event in state.runtime.run(
                messages=messages,
                system_prompt=system_prompt,
                active_tools=active_tools,
                config=state.runtime_config,
                mode_hint=mode_hint,
            ):
                event_count += 1
                yield event
            logger.info("run_turn[%s]: завершён, events=%d", ks, event_count)
        logger.info("run_turn[%s]: lock отпущен", ks)

    async def stream_reply(self, key: SessionKey, user_text: str) -> AsyncIterator[Any]:
        """Legacy API: отправить сообщение и стримить ответ (RuntimePort/adapter path)."""
        lock = self._get_lock(key)
        async with lock:
            state = self.get(key)
            if not state:
                yield StreamEvent(type="error", text="Сессия не найдена")
                return

            # Новый runtime путь (fallback для мест, где ещё вызывают stream_reply).
            if state.runtime is not None and state.adapter is None:
                state.runtime_messages.append(Message(role="user", content=user_text))
                full_text = ""
                assistant_emitted = False
                async for runtime_event in state.runtime.run(
                    messages=list(state.runtime_messages),
                    system_prompt=state.system_prompt,
                    active_tools=state.active_tools,
                    config=state.runtime_config,
                ):
                    if runtime_event.type == "assistant_delta":
                        text = str(runtime_event.data.get("text", ""))
                        full_text += text
                        assistant_emitted = True
                        yield StreamEvent(type="text_delta", text=text)
                    elif runtime_event.type == "tool_call_started":
                        yield StreamEvent(
                            type="tool_use_start",
                            tool_name=str(runtime_event.data.get("name", "")),
                            tool_input=runtime_event.data.get("args"),
                        )
                    elif runtime_event.type == "tool_call_finished":
                        yield StreamEvent(
                            type="tool_use_result",
                            tool_name=str(runtime_event.data.get("name", "")),
                            tool_result=str(runtime_event.data.get("result_summary", "")),
                        )
                    elif runtime_event.type == "error":
                        yield StreamEvent(
                            type="error",
                            text=str(runtime_event.data.get("message", "Ошибка runtime")),
                        )
                        return
                    elif runtime_event.type == "final":
                        final_text = str(runtime_event.data.get("text", ""))
                        if final_text and not full_text:
                            full_text = final_text
                            yield StreamEvent(type="text_delta", text=final_text)
                            assistant_emitted = True
                        if assistant_emitted and full_text:
                            state.runtime_messages.append(
                                Message(role="assistant", content=full_text),
                            )
                        yield StreamEvent(type="done", text=full_text, is_final=True)
                        return

                if assistant_emitted and full_text:
                    state.runtime_messages.append(
                        Message(role="assistant", content=full_text),
                    )
                yield StreamEvent(type="done", text=full_text, is_final=True)
                return

            if not state.adapter or not state.adapter.is_connected:
                yield StreamEvent(type="error", text="SDK не подключён")
                return

            async for event in state.adapter.stream_reply(user_text):
                yield event

    def list_sessions(self) -> list[SessionKey]:
        """Список активных сессий."""
        return [s.key for s in self._sessions.values()]

    def update_role(self, key: SessionKey, role_id: str, skill_ids: list[str]) -> bool:
        """Обновить роль и скилы сессии. Возвращает True если сессия найдена."""
        state = self.get(key)
        if not state:
            return False
        state.role_id = role_id
        state.active_skill_ids = skill_ids
        return True
