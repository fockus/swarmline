"""PostgresMemoryProvider — реализация MemoryProvider на asyncpg + SQLAlchemy."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognitia.memory.types import GoalState, MemoryMessage, PhaseState, ToolEvent, UserProfile

# Подзапрос для получения внутреннего id пользователя по external_id (DRY)
_USER_ID_SUB = "(SELECT id FROM users WHERE external_id = :user_id)"


class PostgresMemoryProvider:
    """Провайдер памяти на базе Postgres (SQLAlchemy async).

    Реализует протоколы: MessageStore, FactStore, SummaryStore,
    GoalStore, SessionStateStore, UserStore.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # --- Утилиты (DRY) ---

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        """Контекстный менеджер для сессии БД — устраняет дубликат async with."""
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    # --- Сообщения (MessageStore) ---

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Сохранить сообщение в историю темы."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(f"""
                    INSERT INTO messages (user_id, topic_id, role, content, tool_calls)
                    VALUES ({_USER_ID_SUB}, :topic_id, :role, :content, CAST(:tool_calls AS jsonb))
                """),
                {
                    "user_id": user_id,
                    "topic_id": topic_id,
                    "role": role,
                    "content": content,
                    "tool_calls": _json_or_none(tool_calls),
                },
            )

    async def get_messages(
        self, user_id: str, topic_id: str, limit: int = 10
    ) -> list[MemoryMessage]:
        """Получить последние N сообщений темы (ASC по времени)."""
        async with self._session() as session:
            result = await session.execute(
                text(f"""
                    SELECT role, content, tool_calls
                    FROM messages
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"user_id": user_id, "topic_id": topic_id, "limit": limit},
            )
            rows = result.fetchall()
        # Разворачиваем — от старых к новым
        return [
            MemoryMessage(role=r.role, content=r.content, tool_calls=r.tool_calls)
            for r in reversed(rows)
        ]

    async def count_messages(self, user_id: str, topic_id: str) -> int:
        """Количество сообщений в теме."""
        async with self._session() as session:
            result = await session.execute(
                text(f"""
                    SELECT COUNT(*) as cnt FROM messages
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                """),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            return row.cnt if row else 0

    async def delete_messages_before(self, user_id: str, topic_id: str, keep_last: int = 10) -> int:
        """Удалить старые сообщения, оставив последние keep_last."""
        async with self._session(commit=True) as session:
            result = await session.execute(
                text(f"""
                    DELETE FROM messages
                    WHERE id IN (
                        SELECT id FROM messages
                        WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                        ORDER BY created_at ASC
                        LIMIT (
                            SELECT GREATEST(COUNT(*) - :keep_last, 0)
                            FROM messages
                            WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                        )
                    )
                """),
                {"user_id": user_id, "topic_id": topic_id, "keep_last": keep_last},
            )
            return int(result.rowcount)  # type: ignore[attr-defined]

    # --- Факты (FactStore) ---

    async def upsert_fact(
        self,
        user_id: str,
        key: str,
        value: Any,
        topic_id: str | None = None,
        source: str = "user",
    ) -> None:
        """Сохранить/обновить факт. Приоритет: user > ai_inferred > mcp.

        Использует partial unique indexes (миграция 005):
        - topic_id IS NOT NULL → ON CONFLICT на uq_facts_user_topic_key
        - topic_id IS NULL → ON CONFLICT на uq_facts_user_global_key
        """
        json_value = json.dumps(value)
        async with self._session(commit=True) as session:
            if topic_id is not None:
                # Факт привязан к теме
                await session.execute(
                    text(f"""
                        INSERT INTO facts (user_id, topic_id, key, value, source)
                        VALUES ({_USER_ID_SUB}, :topic_id, :key, CAST(:value AS jsonb), :source)
                        ON CONFLICT (user_id, topic_id, key)
                            WHERE topic_id IS NOT NULL
                        DO UPDATE SET
                            value = EXCLUDED.value,
                            source = EXCLUDED.source,
                            updated_at = now()
                        WHERE facts.source != 'user' OR EXCLUDED.source = 'user'
                    """),
                    {
                        "user_id": user_id,
                        "topic_id": topic_id,
                        "key": key,
                        "value": json_value,
                        "source": source,
                    },
                )
            else:
                # Глобальный факт (topic_id IS NULL)
                await session.execute(
                    text(f"""
                        INSERT INTO facts (user_id, topic_id, key, value, source)
                        VALUES ({_USER_ID_SUB}, NULL, :key, CAST(:value AS jsonb), :source)
                        ON CONFLICT (user_id, key)
                            WHERE topic_id IS NULL
                        DO UPDATE SET
                            value = EXCLUDED.value,
                            source = EXCLUDED.source,
                            updated_at = now()
                        WHERE facts.source != 'user' OR EXCLUDED.source = 'user'
                    """),
                    {
                        "user_id": user_id,
                        "key": key,
                        "value": json_value,
                        "source": source,
                    },
                )

    async def get_facts(self, user_id: str, topic_id: str | None = None) -> dict[str, Any]:
        """Получить факты: глобальные + по теме (если указана)."""
        async with self._session() as session:
            if topic_id:
                result = await session.execute(
                    text(f"""
                        SELECT key, value FROM facts
                        WHERE user_id = {_USER_ID_SUB}
                          AND (topic_id IS NULL OR topic_id = :topic_id)
                        ORDER BY updated_at DESC
                    """),
                    {"user_id": user_id, "topic_id": topic_id},
                )
            else:
                result = await session.execute(
                    text(f"""
                        SELECT key, value FROM facts
                        WHERE user_id = {_USER_ID_SUB} AND topic_id IS NULL
                        ORDER BY updated_at DESC
                    """),
                    {"user_id": user_id},
                )
            rows = result.fetchall()
        return {r.key: r.value for r in rows}

    # --- Summaries (SummaryStore) ---

    async def save_summary(
        self,
        user_id: str,
        topic_id: str,
        summary: str,
        messages_covered: int,
    ) -> None:
        """Сохранить/обновить rolling summary с версионированием."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(f"""
                    INSERT INTO summaries (user_id, topic_id, summary, messages_covered, version)
                    VALUES ({_USER_ID_SUB}, :topic_id, :summary, :messages_covered, 1)
                    ON CONFLICT (user_id, topic_id)
                    DO UPDATE SET
                        summary = EXCLUDED.summary,
                        messages_covered = EXCLUDED.messages_covered,
                        version = summaries.version + 1,
                        updated_at = now()
                """),
                {
                    "user_id": user_id,
                    "topic_id": topic_id,
                    "summary": summary,
                    "messages_covered": messages_covered,
                },
            )

    async def get_summary(self, user_id: str, topic_id: str) -> str | None:
        """Получить summary темы."""
        async with self._session() as session:
            result = await session.execute(
                text(f"""
                    SELECT summary FROM summaries
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                """),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            return row.summary if row else None

    # --- Users (UserStore) ---

    async def ensure_user(self, external_id: str) -> str:
        """Создать пользователя если не существует, вернуть external_id."""
        async with self._session(commit=True) as session:
            await session.execute(
                text("""
                    INSERT INTO users (external_id)
                    VALUES (:external_id)
                    ON CONFLICT (external_id) DO NOTHING
                """),
                {"external_id": external_id},
            )
        return external_id

    # --- Goals (GoalStore) ---

    async def save_goal(self, user_id: str, goal: GoalState) -> None:
        """Сохранить/обновить цель."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(f"""
                    INSERT INTO goals (user_id, topic_id, title, target_amount, current_amount,
                                       phase, is_main, plan, status)
                    VALUES (
                        {_USER_ID_SUB},
                        :topic_id, :title, :target_amount, :current_amount,
                        :phase, :is_main, CAST(:plan AS jsonb), 'active'
                    )
                    ON CONFLICT (user_id, topic_id) DO NOTHING
                """),
                {
                    "user_id": user_id,
                    "topic_id": goal.goal_id,
                    "title": goal.title,
                    "target_amount": goal.target_amount,
                    "current_amount": goal.current_amount,
                    "phase": goal.phase,
                    "is_main": goal.is_main,
                    "plan": json.dumps(goal.plan) if goal.plan else None,
                },
            )

    async def get_active_goal(self, user_id: str, topic_id: str) -> GoalState | None:
        """Получить активную цель темы."""
        async with self._session() as session:
            result = await session.execute(
                text(f"""
                    SELECT topic_id, title, target_amount, current_amount, phase, plan, is_main
                    FROM goals
                    WHERE user_id = {_USER_ID_SUB}
                      AND topic_id = :topic_id
                      AND status = 'active'
                    ORDER BY priority DESC, created_at DESC
                    LIMIT 1
                """),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return GoalState(
                goal_id=row.topic_id,
                title=row.title,
                target_amount=row.target_amount,
                current_amount=row.current_amount,
                phase=row.phase,
                plan=row.plan,
                is_main=row.is_main,
            )

    # --- Session state (SessionStateStore — таблица topics) ---

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
        """Сохранить состояние сессии для rehydration (таблица topics, §8.4)."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(f"""
                    INSERT INTO topics (user_id, topic_id, role_id, active_skill_ids, prompt_hash,
                                        delegated_from, delegation_turn_count, pending_delegation, delegation_summary)
                    VALUES ({_USER_ID_SUB}, :topic_id, :role_id, CAST(:skill_ids AS jsonb), :prompt_hash,
                            :delegated_from, :delegation_turn_count, :pending_delegation, :delegation_summary)
                    ON CONFLICT (user_id, topic_id)
                    DO UPDATE SET
                        role_id = EXCLUDED.role_id,
                        active_skill_ids = EXCLUDED.active_skill_ids,
                        prompt_hash = EXCLUDED.prompt_hash,
                        delegated_from = EXCLUDED.delegated_from,
                        delegation_turn_count = EXCLUDED.delegation_turn_count,
                        pending_delegation = EXCLUDED.pending_delegation,
                        delegation_summary = EXCLUDED.delegation_summary,
                        updated_at = now()
                """),
                {
                    "user_id": user_id,
                    "topic_id": topic_id,
                    "role_id": role_id,
                    "skill_ids": json.dumps(active_skill_ids),
                    "prompt_hash": prompt_hash,
                    "delegated_from": delegated_from,
                    "delegation_turn_count": delegation_turn_count,
                    "pending_delegation": pending_delegation,
                    "delegation_summary": delegation_summary,
                },
            )

    async def get_session_state(self, user_id: str, topic_id: str) -> dict[str, Any] | None:
        """Получить состояние сессии (из таблицы topics)."""
        async with self._session() as session:
            result = await session.execute(
                text(f"""
                    SELECT role_id, active_skill_ids, title, COALESCE(prompt_hash, '') as prompt_hash,
                           delegated_from, COALESCE(delegation_turn_count, 0) as delegation_turn_count,
                           pending_delegation, delegation_summary
                    FROM topics
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                """),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return {
                "role_id": row.role_id,
                "active_skill_ids": row.active_skill_ids or [],
                "title": row.title,
                "prompt_hash": row.prompt_hash,
                "delegated_from": row.delegated_from,
                "delegation_turn_count": row.delegation_turn_count or 0,
                "pending_delegation": row.pending_delegation,
                "delegation_summary": row.delegation_summary,
            }

    # --- Profile (UserStore) ---

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """Получить профиль с глобальными фактами."""
        facts = await self.get_facts(user_id, topic_id=None)
        return UserProfile(user_id=user_id, facts=facts)

    # --- Phase state ---

    async def save_phase_state(
        self,
        user_id: str,
        phase: str,
        notes: str = "",
    ) -> None:
        """Сохранить/обновить текущую фазу пользователя."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(f"""
                    INSERT INTO phase_state (user_id, phase, notes)
                    VALUES ({_USER_ID_SUB}, :phase, :notes)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        phase = EXCLUDED.phase,
                        notes = EXCLUDED.notes,
                        updated_at = now()
                """),
                {"user_id": user_id, "phase": phase, "notes": notes},
            )

    async def get_phase_state(self, user_id: str) -> PhaseState | None:
        """Получить текущую фазу пользователя."""
        async with self._session() as session:
            result = await session.execute(
                text(f"""
                    SELECT phase, notes FROM phase_state
                    WHERE user_id = {_USER_ID_SUB}
                """),
                {"user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return PhaseState(
                user_id=user_id,
                phase=row.phase,
                notes=row.notes or "",
            )

    # --- Tool events (§9.1) ---

    async def save_tool_event(
        self,
        user_id: str,
        event: ToolEvent,
    ) -> None:
        """Сохранить событие вызова инструмента."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(f"""
                    INSERT INTO tool_events (user_id, topic_id, tool_name,
                                             input_json, output_json, latency_ms)
                    VALUES ({_USER_ID_SUB}, :topic_id, :tool_name,
                            CAST(:input_json AS jsonb), CAST(:output_json AS jsonb), :latency_ms)
                """),
                {
                    "user_id": user_id,
                    "topic_id": event.topic_id,
                    "tool_name": event.tool_name,
                    "input_json": _json_or_none(event.input_json),
                    "output_json": _json_or_none(event.output_json),
                    "latency_ms": event.latency_ms,
                },
            )


def _json_or_none(value: Any) -> str | None:
    """Сериализовать значение в JSON-строку или вернуть None."""
    if value is None:
        return None
    return json.dumps(value)
