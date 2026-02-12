"""InMemoryMemoryProvider — dev-mode провайдер памяти без БД (R-521).

Все данные хранятся в dict'ах в памяти процесса.
Идеален для разработки, тестов и демонстрации без Postgres.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from cognitia.memory.types import GoalState, MemoryMessage, PhaseState, ToolEvent, UserProfile


class InMemoryMemoryProvider:
    """Pluggable memory provider для dev/test без БД.

    Реализует полный MemoryProvider Protocol.
    """

    def __init__(self) -> None:
        # messages: (user_id, topic_id) -> list[MemoryMessage]
        self._messages: dict[tuple[str, str], list[MemoryMessage]] = defaultdict(list)
        # facts: (user_id, topic_id|None) -> {key: value}
        self._facts: dict[tuple[str, str | None], dict[str, Any]] = defaultdict(dict)
        # summaries: (user_id, topic_id) -> summary_text
        self._summaries: dict[tuple[str, str], str] = {}
        # goals: (user_id, topic_id) -> GoalState
        self._goals: dict[tuple[str, str], GoalState] = {}
        # session_state: (user_id, topic_id) -> dict
        self._session_states: dict[tuple[str, str], dict[str, Any]] = {}
        # users: external_id -> True
        self._users: set[str] = set()
        # phase_state: user_id -> PhaseState
        self._phase_states: dict[str, PhaseState] = {}
        # tool_events: list
        self._tool_events: list[dict[str, Any]] = []

    # --- Сообщения ---

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Сохранить сообщение."""
        key = (user_id, topic_id)
        self._messages[key].append(MemoryMessage(role=role, content=content, tool_calls=tool_calls))

    async def get_messages(
        self,
        user_id: str,
        topic_id: str,
        limit: int = 10,
    ) -> list[MemoryMessage]:
        """Получить последние N сообщений."""
        key = (user_id, topic_id)
        msgs = self._messages[key]
        return msgs[-limit:]

    async def count_messages(self, user_id: str, topic_id: str) -> int:
        """Количество сообщений."""
        return len(self._messages[(user_id, topic_id)])

    async def delete_messages_before(
        self,
        user_id: str,
        topic_id: str,
        keep_last: int = 10,
    ) -> int:
        """Удалить старые сообщения."""
        key = (user_id, topic_id)
        msgs = self._messages[key]
        to_delete = max(0, len(msgs) - keep_last)
        if to_delete > 0:
            self._messages[key] = msgs[-keep_last:]
        return to_delete

    # --- Факты ---

    async def upsert_fact(
        self,
        user_id: str,
        key: str,
        value: Any,
        topic_id: str | None = None,
        source: str = "user",
    ) -> None:
        """Сохранить факт."""
        fk = (user_id, topic_id)
        self._facts[fk][key] = value

    async def get_facts(
        self,
        user_id: str,
        topic_id: str | None = None,
    ) -> dict[str, Any]:
        """Получить факты: глобальные + по теме."""
        result: dict[str, Any] = {}
        # Глобальные
        result.update(self._facts.get((user_id, None), {}))
        # По теме
        if topic_id:
            result.update(self._facts.get((user_id, topic_id), {}))
        return result

    # --- Summaries ---

    async def save_summary(
        self,
        user_id: str,
        topic_id: str,
        summary: str,
        messages_covered: int,
    ) -> None:
        """Сохранить summary."""
        self._summaries[(user_id, topic_id)] = summary

    async def get_summary(self, user_id: str, topic_id: str) -> str | None:
        """Получить summary."""
        return self._summaries.get((user_id, topic_id))

    # --- Users ---

    async def ensure_user(self, external_id: str) -> str:
        """Создать пользователя."""
        self._users.add(external_id)
        return external_id

    # --- Goals ---

    async def save_goal(self, user_id: str, goal: GoalState) -> None:
        """Сохранить цель."""
        self._goals[(user_id, goal.goal_id)] = goal

    async def get_active_goal(self, user_id: str, topic_id: str) -> GoalState | None:
        """Получить активную цель."""
        return self._goals.get((user_id, topic_id))

    # --- Session state ---

    async def save_session_state(
        self,
        user_id: str,
        topic_id: str,
        role_id: str,
        active_skill_ids: list[str],
        prompt_hash: str = "",
        *,
        delegated_from: str | None = None,
        delegation_turn_count: int = 0,
        pending_delegation: str | None = None,
        delegation_summary: str | None = None,
    ) -> None:
        """Сохранить состояние сессии."""
        self._session_states[(user_id, topic_id)] = {
            "role_id": role_id,
            "active_skill_ids": active_skill_ids,
            "prompt_hash": prompt_hash,
            "delegated_from": delegated_from,
            "delegation_turn_count": delegation_turn_count,
            "pending_delegation": pending_delegation,
            "delegation_summary": delegation_summary,
        }

    async def get_session_state(
        self,
        user_id: str,
        topic_id: str,
    ) -> dict[str, Any] | None:
        """Получить состояние сессии."""
        return self._session_states.get((user_id, topic_id))

    # --- Profile ---

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """Получить профиль."""
        facts = await self.get_facts(user_id, topic_id=None)
        return UserProfile(user_id=user_id, facts=facts)

    # --- Phase state ---

    async def save_phase_state(
        self,
        user_id: str,
        phase: str,
        notes: str = "",
    ) -> None:
        """Сохранить фазу."""
        self._phase_states[user_id] = PhaseState(
            user_id=user_id,
            phase=phase,
            notes=notes,
        )

    async def get_phase_state(self, user_id: str) -> PhaseState | None:
        """Получить текущую фазу."""
        return self._phase_states.get(user_id)

    # --- Tool events (§9.1) ---

    async def save_tool_event(
        self,
        user_id: str,
        event: ToolEvent,
    ) -> None:
        """Сохранить событие вызова инструмента."""
        self._tool_events.append(
            {
                "user_id": user_id,
                "topic_id": event.topic_id,
                "tool_name": event.tool_name,
                "input_json": event.input_json,
                "output_json": event.output_json,
                "latency_ms": event.latency_ms,
            }
        )
