"""SQLiteMemoryProvider - MemoryProvider implementation on SQLAlchemy + SQLite."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cognitia.memory.types import GoalState, MemoryMessage, PhaseState, ToolEvent, UserProfile

_USER_ID_SUB = "(SELECT id FROM users WHERE external_id = :user_id)"
_SQLITE_EXISTING_SOURCE_PRIORITY = (
    "CASE source "
    "WHEN 'user' THEN 3 "
    "WHEN 'ai_inferred' THEN 2 "
    "WHEN 'mcp' THEN 1 "
    "ELSE 0 END"
)
_SQLITE_INCOMING_SOURCE_PRIORITY = (
    "CASE :source "
    "WHEN 'user' THEN 3 "
    "WHEN 'ai_inferred' THEN 2 "
    "WHEN 'mcp' THEN 1 "
    "ELSE 0 END"
)


class SQLiteMemoryProvider:
    """Memory provider backed by SQLite (SQLAlchemy async)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    # --- Messages ---

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO messages (user_id, topic_id, role, content, tool_calls)
                    VALUES ({_USER_ID_SUB}, :topic_id, :role, :content, :tool_calls)
                """
                ),
                {
                    "user_id": user_id,
                    "topic_id": topic_id,
                    "role": role,
                    "content": content,
                    "tool_calls": _json_or_none(tool_calls),
                },
            )

    async def get_messages(
        self,
        user_id: str,
        topic_id: str,
        limit: int = 10,
    ) -> list[MemoryMessage]:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT role, content, tool_calls
                    FROM messages
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit
                """
                ),
                {"user_id": user_id, "topic_id": topic_id, "limit": limit},
            )
            rows = result.fetchall()
        return [
            MemoryMessage(
                role=str(row.role),
                content=str(row.content),
                tool_calls=_load_json_or_none(row.tool_calls),
            )
            for row in reversed(rows)
        ]

    async def count_messages(self, user_id: str, topic_id: str) -> int:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT COUNT(*) AS cnt
                    FROM messages
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                """
                ),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            if row is None:
                return 0
            return int(row.cnt)

    async def delete_messages_before(self, user_id: str, topic_id: str, keep_last: int = 10) -> int:
        async with self._session(commit=True) as session:
            result = await session.execute(
                text(
                    f"""
                    DELETE FROM messages
                    WHERE id IN (
                        SELECT id FROM messages
                        WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                        ORDER BY created_at ASC, id ASC
                        LIMIT (
                            SELECT CASE
                                WHEN COUNT(*) > :keep_last THEN COUNT(*) - :keep_last
                                ELSE 0
                            END
                            FROM messages
                            WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                        )
                    )
                """
                ),
                {"user_id": user_id, "topic_id": topic_id, "keep_last": keep_last},
            )
            return int(getattr(result, "rowcount", 0) or 0)

    # --- Facts ---

    async def upsert_fact(
        self,
        user_id: str,
        key: str,
        value: Any,
        topic_id: str | None = None,
        source: str = "user",
    ) -> None:
        json_value = json.dumps(value)
        async with self._session(commit=True) as session:
            if topic_id is not None:
                await session.execute(
                    text(
                        f"""
                        INSERT INTO facts (user_id, topic_id, key, value, source)
                        VALUES ({_USER_ID_SUB}, :topic_id, :key, :value, :source)
                        ON CONFLICT (user_id, topic_id, key)
                            WHERE topic_id IS NOT NULL
                        DO UPDATE SET
                            value = excluded.value,
                            source = excluded.source,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE {_SQLITE_EXISTING_SOURCE_PRIORITY}
                              <= {_SQLITE_INCOMING_SOURCE_PRIORITY}
                    """
                    ),
                    {
                        "user_id": user_id,
                        "topic_id": topic_id,
                        "key": key,
                        "value": json_value,
                        "source": source,
                    },
                )
            else:
                await session.execute(
                    text(
                        f"""
                        INSERT INTO facts (user_id, topic_id, key, value, source)
                        VALUES ({_USER_ID_SUB}, NULL, :key, :value, :source)
                        ON CONFLICT (user_id, key)
                            WHERE topic_id IS NULL
                        DO UPDATE SET
                            value = excluded.value,
                            source = excluded.source,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE {_SQLITE_EXISTING_SOURCE_PRIORITY}
                              <= {_SQLITE_INCOMING_SOURCE_PRIORITY}
                    """
                    ),
                    {
                        "user_id": user_id,
                        "key": key,
                        "value": json_value,
                        "source": source,
                    },
                )

    async def get_facts(self, user_id: str, topic_id: str | None = None) -> dict[str, Any]:
        async with self._session() as session:
            if topic_id:
                result = await session.execute(
                    text(
                        f"""
                        SELECT key, value, topic_id FROM facts
                        WHERE user_id = {_USER_ID_SUB}
                          AND (topic_id IS NULL OR topic_id = :topic_id)
                        ORDER BY updated_at DESC, id DESC
                    """
                    ),
                    {"user_id": user_id, "topic_id": topic_id},
                )
            else:
                result = await session.execute(
                    text(
                        f"""
                        SELECT key, value FROM facts
                        WHERE user_id = {_USER_ID_SUB}
                          AND topic_id IS NULL
                        ORDER BY updated_at DESC, id DESC
                    """
                    ),
                    {"user_id": user_id},
                )
            rows = result.fetchall()
        if not topic_id:
            return {str(row.key): _load_json_value(row.value) for row in rows}
        return _merge_scoped_sqlite_facts(rows)

    # --- Summaries ---

    async def save_summary(
        self,
        user_id: str,
        topic_id: str,
        summary: str,
        messages_covered: int,
    ) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO summaries (user_id, topic_id, summary, messages_covered, version)
                    VALUES ({_USER_ID_SUB}, :topic_id, :summary, :messages_covered, 1)
                    ON CONFLICT (user_id, topic_id)
                    DO UPDATE SET
                        summary = excluded.summary,
                        messages_covered = excluded.messages_covered,
                        version = summaries.version + 1,
                        updated_at = CURRENT_TIMESTAMP
                """
                ),
                {
                    "user_id": user_id,
                    "topic_id": topic_id,
                    "summary": summary,
                    "messages_covered": messages_covered,
                },
            )

    async def get_summary(self, user_id: str, topic_id: str) -> str | None:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT summary FROM summaries
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                """
                ),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            return str(row.summary) if row else None

    # --- Users ---

    async def ensure_user(self, external_id: str) -> str:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    """
                    INSERT INTO users (external_id)
                    VALUES (:external_id)
                    ON CONFLICT (external_id) DO NOTHING
                """
                ),
                {"external_id": external_id},
            )
        return external_id

    # --- Goals ---

    async def save_goal(self, user_id: str, goal: GoalState) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO goals (
                        user_id, topic_id, title, target_amount,
                        current_amount, phase, is_main, plan, status
                    )
                    VALUES (
                        {_USER_ID_SUB}, :topic_id, :title, :target_amount,
                        :current_amount, :phase, :is_main, :plan, 'active'
                    )
                    ON CONFLICT(user_id, topic_id) DO UPDATE SET
                        title = excluded.title,
                        target_amount = excluded.target_amount,
                        current_amount = excluded.current_amount,
                        phase = excluded.phase,
                        is_main = excluded.is_main,
                        plan = excluded.plan,
                        status = 'active'
                """
                ),
                {
                    "user_id": user_id,
                    "topic_id": goal.goal_id,
                    "title": goal.title,
                    "target_amount": goal.target_amount,
                    "current_amount": goal.current_amount,
                    "phase": goal.phase,
                    "is_main": 1 if goal.is_main else 0,
                    "plan": _json_or_none(goal.plan),
                },
            )

    async def get_active_goal(self, user_id: str, topic_id: str) -> GoalState | None:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT topic_id, title, target_amount, current_amount, phase, plan, is_main
                    FROM goals
                    WHERE user_id = {_USER_ID_SUB}
                      AND topic_id = :topic_id
                      AND status = 'active'
                    ORDER BY priority DESC, created_at DESC
                    LIMIT 1
                """
                ),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return GoalState(
                goal_id=str(row.topic_id),
                title=str(row.title),
                target_amount=(int(row.target_amount) if row.target_amount is not None else None),
                current_amount=int(row.current_amount or 0),
                phase=str(row.phase or ""),
                plan=_load_json_or_none(row.plan),
                is_main=bool(row.is_main),
            )

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
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO topics (user_id, topic_id, role_id, active_skill_ids, prompt_hash,
                                        delegated_from, delegation_turn_count, pending_delegation, delegation_summary)
                    VALUES ({_USER_ID_SUB}, :topic_id, :role_id, :skill_ids, :prompt_hash,
                            :delegated_from, :delegation_turn_count, :pending_delegation, :delegation_summary)
                    ON CONFLICT (user_id, topic_id)
                    DO UPDATE SET
                        role_id = excluded.role_id,
                        active_skill_ids = excluded.active_skill_ids,
                        prompt_hash = excluded.prompt_hash,
                        delegated_from = excluded.delegated_from,
                        delegation_turn_count = excluded.delegation_turn_count,
                        pending_delegation = excluded.pending_delegation,
                        delegation_summary = excluded.delegation_summary,
                        updated_at = CURRENT_TIMESTAMP
                """
                ),
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
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT role_id, active_skill_ids, title, COALESCE(prompt_hash, '') AS prompt_hash,
                           delegated_from, COALESCE(delegation_turn_count, 0) AS delegation_turn_count,
                           pending_delegation, delegation_summary
                    FROM topics
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                """
                ),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return {
                "role_id": str(row.role_id),
                "active_skill_ids": _load_json_or_empty_list(row.active_skill_ids),
                "title": row.title,
                "prompt_hash": str(row.prompt_hash or ""),
                "delegated_from": row.delegated_from,
                "delegation_turn_count": row.delegation_turn_count or 0,
                "pending_delegation": row.pending_delegation,
                "delegation_summary": row.delegation_summary,
            }

    # --- Profile ---

    async def get_user_profile(self, user_id: str) -> UserProfile:
        facts = await self.get_facts(user_id, topic_id=None)
        return UserProfile(user_id=user_id, facts=facts)

    # --- Phase state ---

    async def save_phase_state(
        self,
        user_id: str,
        phase: str,
        notes: str = "",
    ) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO phase_state (user_id, phase, notes)
                    VALUES ({_USER_ID_SUB}, :phase, :notes)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        phase = excluded.phase,
                        notes = excluded.notes,
                        updated_at = CURRENT_TIMESTAMP
                """
                ),
                {"user_id": user_id, "phase": phase, "notes": notes},
            )

    async def get_phase_state(self, user_id: str) -> PhaseState | None:
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT phase, notes
                    FROM phase_state
                    WHERE user_id = {_USER_ID_SUB}
                """
                ),
                {"user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return PhaseState(
                user_id=user_id,
                phase=str(row.phase or ""),
                notes=str(row.notes or ""),
            )

    # --- Tool events ---

    async def save_tool_event(
        self,
        user_id: str,
        event: ToolEvent,
    ) -> None:
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO tool_events (user_id, topic_id, tool_name, input_json, output_json, latency_ms)
                    VALUES ({_USER_ID_SUB}, :topic_id, :tool_name, :input_json, :output_json, :latency_ms)
                """
                ),
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
    if value is None:
        return None
    return json.dumps(value)


def _load_json_or_none(raw: Any) -> Any | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, dict | list):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return None


def _load_json_or_empty_list(raw: Any) -> list[str]:
    parsed = _load_json_or_none(raw)
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _load_json_value(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, dict | list | int | float | bool):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return raw


def _merge_scoped_sqlite_facts(rows: Sequence[Any]) -> dict[str, Any]:
    """Merge global + topic rows so topic-scoped values override global ones."""
    merged: dict[str, Any] = {}
    global_rows = [row for row in rows if getattr(row, "topic_id", None) is None]
    topic_rows = [row for row in rows if getattr(row, "topic_id", None) is not None]
    for row in global_rows + topic_rows:
        merged[str(row.key)] = _load_json_value(row.value)
    return merged
