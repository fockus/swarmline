"""PostgresMemoryProvider - MemoryProvider implementation on asyncpg + SQLAlchemy."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from swarmline.memory._shared import (
    build_goal_state,
    build_phase_state,
    build_session_state,
    json_dumps_or_none,
    json_load_or_none,
    json_load_value,
    merge_scoped_facts,
)
from swarmline.memory.types import GoalState, MemoryMessage, PhaseState, ToolEvent, UserProfile

# Subquery for resolving the internal user id by external_id (DRY)
_USER_ID_SUB = "(SELECT id FROM users WHERE external_id = :user_id)"
_POSTGRES_EXISTING_SOURCE_PRIORITY = (
    "CASE facts.source "
    "WHEN 'user' THEN 3 "
    "WHEN 'ai_inferred' THEN 2 "
    "WHEN 'mcp' THEN 1 "
    "ELSE 0 END"
)
_POSTGRES_INCOMING_SOURCE_PRIORITY = (
    "CASE EXCLUDED.source "
    "WHEN 'user' THEN 3 "
    "WHEN 'ai_inferred' THEN 2 "
    "WHEN 'mcp' THEN 1 "
    "ELSE 0 END"
)


class PostgresMemoryProvider:
    """Memory provider backed by Postgres (SQLAlchemy async).

    Implements the protocols: MessageStore, FactStore, SummaryStore,
    GoalStore, SessionStateStore, UserStore.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # --- Utilities (DRY) ---

    @asynccontextmanager
    async def _session(self, *, commit: bool = False) -> AsyncIterator[AsyncSession]:
        """Context manager for a DB session - removes async with duplication."""
        async with self._sf() as session:
            yield session
            if commit:
                await session.commit()

    # --- Messages (MessageStore) ---

    async def save_message(
        self,
        user_id: str,
        topic_id: str,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Save a message to the topic history."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO messages (user_id, topic_id, role, content, tool_calls)
                    VALUES ({_USER_ID_SUB}, :topic_id, :role, :content, CAST(:tool_calls AS jsonb))
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
        self, user_id: str, topic_id: str, limit: int = 10
    ) -> list[MemoryMessage]:
        """Get the last N topic messages (ASC by time)."""
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT role, content, tool_calls
                    FROM messages
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """
                ),
                {"user_id": user_id, "topic_id": topic_id, "limit": limit},
            )
            rows = result.fetchall()
        # Reverse - from oldest to newest
        return [
            MemoryMessage(
                role=str(r.role),
                content=str(r.content),
                tool_calls=_load_json_or_none(r.tool_calls),
            )
            for r in reversed(rows)
        ]

    async def count_messages(self, user_id: str, topic_id: str) -> int:
        """Number of messages in the topic."""
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT COUNT(*) as cnt FROM messages
                    WHERE user_id = {_USER_ID_SUB} AND topic_id = :topic_id
                """
                ),
                {"user_id": user_id, "topic_id": topic_id},
            )
            row = result.fetchone()
            return int(row.cnt) if row else 0

    async def delete_messages_before(self, user_id: str, topic_id: str, keep_last: int = 10) -> int:
        """Delete old messages, keeping the last keep_last."""
        async with self._session(commit=True) as session:
            result = await session.execute(
                text(
                    f"""
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
                """
                ),
                {"user_id": user_id, "topic_id": topic_id, "keep_last": keep_last},
            )
            return int(result.rowcount)  # type: ignore[attr-defined]

    # --- Facts (FactStore) ---

    async def upsert_fact(
        self,
        user_id: str,
        key: str,
        value: Any,
        topic_id: str | None = None,
        source: str = "user",
    ) -> None:
        """Save/update a fact. Priority: user > ai_inferred > mcp.

        Uses partial unique indexes (migration 005):
        - topic_id IS NOT NULL -> ON CONFLICT on uq_facts_user_topic_key
        - topic_id IS NULL -> ON CONFLICT on uq_facts_user_global_key
        """
        json_value = _json_or_none(value)
        async with self._session(commit=True) as session:
            if topic_id is not None:
                # Topic-scoped fact
                await session.execute(
                    text(
                        f"""
                        INSERT INTO facts (user_id, topic_id, key, value, source)
                        VALUES ({_USER_ID_SUB}, :topic_id, :key, CAST(:value AS jsonb), :source)
                        ON CONFLICT (user_id, topic_id, key)
                            WHERE topic_id IS NOT NULL
                        DO UPDATE SET
                            value = EXCLUDED.value,
                            source = EXCLUDED.source,
                            updated_at = now()
                        WHERE {_POSTGRES_EXISTING_SOURCE_PRIORITY}
                              <= {_POSTGRES_INCOMING_SOURCE_PRIORITY}
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
                # Global fact (topic_id IS NULL)
                await session.execute(
                    text(
                        f"""
                        INSERT INTO facts (user_id, topic_id, key, value, source)
                        VALUES ({_USER_ID_SUB}, NULL, :key, CAST(:value AS jsonb), :source)
                        ON CONFLICT (user_id, key)
                            WHERE topic_id IS NULL
                        DO UPDATE SET
                            value = EXCLUDED.value,
                            source = EXCLUDED.source,
                            updated_at = now()
                        WHERE {_POSTGRES_EXISTING_SOURCE_PRIORITY}
                              <= {_POSTGRES_INCOMING_SOURCE_PRIORITY}
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
        """Get facts: global + topic-scoped (if provided)."""
        async with self._session() as session:
            if topic_id:
                result = await session.execute(
                    text(
                        f"""
                        SELECT key, value, topic_id FROM facts
                        WHERE user_id = {_USER_ID_SUB}
                          AND (topic_id IS NULL OR topic_id = :topic_id)
                        ORDER BY updated_at DESC
                    """
                    ),
                    {"user_id": user_id, "topic_id": topic_id},
                )
            else:
                result = await session.execute(
                    text(
                        f"""
                        SELECT key, value FROM facts
                        WHERE user_id = {_USER_ID_SUB} AND topic_id IS NULL
                        ORDER BY updated_at DESC
                    """
                    ),
                    {"user_id": user_id},
                )
            rows = result.fetchall()
        if not topic_id:
            return {str(r.key): _load_json_value(r.value) for r in rows}
        return _merge_scoped_postgres_facts(rows)

    # --- Summaries (SummaryStore) ---

    async def save_summary(
        self,
        user_id: str,
        topic_id: str,
        summary: str,
        messages_covered: int,
    ) -> None:
        """Save/update a rolling summary with versioning."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO summaries (user_id, topic_id, summary, messages_covered, version)
                    VALUES ({_USER_ID_SUB}, :topic_id, :summary, :messages_covered, 1)
                    ON CONFLICT (user_id, topic_id)
                    DO UPDATE SET
                        summary = EXCLUDED.summary,
                        messages_covered = EXCLUDED.messages_covered,
                        version = summaries.version + 1,
                        updated_at = now()
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
        """Get the topic summary."""
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
            return row.summary if row else None

    # --- Users (UserStore) ---

    async def ensure_user(self, external_id: str) -> str:
        """Create the user if needed and return external_id."""
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

    # --- Goals (GoalStore) ---

    async def save_goal(self, user_id: str, goal: GoalState) -> None:
        """Save or update a goal."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO goals (user_id, topic_id, title, target_amount, current_amount,
                                       phase, is_main, plan, status)
                    VALUES (
                        {_USER_ID_SUB},
                        :topic_id, :title, :target_amount, :current_amount,
                        :phase, :is_main, CAST(:plan AS jsonb), 'active'
                    )
                    ON CONFLICT (user_id, topic_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        target_amount = EXCLUDED.target_amount,
                        current_amount = EXCLUDED.current_amount,
                        phase = EXCLUDED.phase,
                        is_main = EXCLUDED.is_main,
                        plan = EXCLUDED.plan,
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
                    "is_main": goal.is_main,
                    "plan": _json_or_none(goal.plan),
                },
            )

    async def get_active_goal(self, user_id: str, topic_id: str) -> GoalState | None:
        """Get the active goal for the topic."""
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
            return build_goal_state(
                goal_id=row.topic_id,
                title=row.title,
                target_amount=row.target_amount,
                current_amount=row.current_amount,
                phase=row.phase,
                plan=row.plan,
                is_main=row.is_main,
            )

    # --- Session state (SessionStateStore - topics table) ---

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
        """Save session state for rehydration (topics table, §8.4)."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
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
                """
                ),
                {
                    "user_id": user_id,
                    "topic_id": topic_id,
                    "role_id": role_id,
                    "skill_ids": _json_or_none(active_skill_ids),
                    "prompt_hash": prompt_hash,
                    "delegated_from": delegated_from,
                    "delegation_turn_count": delegation_turn_count,
                    "pending_delegation": pending_delegation,
                    "delegation_summary": delegation_summary,
                },
            )

    async def get_session_state(self, user_id: str, topic_id: str) -> dict[str, Any] | None:
        """Get session state (from the topics table)."""
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT role_id, active_skill_ids, title, COALESCE(prompt_hash, '') as prompt_hash,
                           delegated_from, COALESCE(delegation_turn_count, 0) as delegation_turn_count,
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
            return build_session_state(
                role_id=row.role_id,
                active_skill_ids=row.active_skill_ids,
                title=row.title,
                prompt_hash=row.prompt_hash,
                delegated_from=row.delegated_from,
                delegation_turn_count=row.delegation_turn_count,
                pending_delegation=row.pending_delegation,
                delegation_summary=row.delegation_summary,
            )

    # --- Profile (UserStore) ---

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """Get the profile with global facts."""
        facts = await self.get_facts(user_id, topic_id=None)
        return UserProfile(user_id=user_id, facts=facts)

    # --- Phase state ---

    async def save_phase_state(
        self,
        user_id: str,
        phase: str,
        notes: str = "",
    ) -> None:
        """Save or update the user's current phase."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO phase_state (user_id, phase, notes)
                    VALUES ({_USER_ID_SUB}, :phase, :notes)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        phase = EXCLUDED.phase,
                        notes = EXCLUDED.notes,
                        updated_at = now()
                """
                ),
                {"user_id": user_id, "phase": phase, "notes": notes},
            )

    async def get_phase_state(self, user_id: str) -> PhaseState | None:
        """Get the user's current phase."""
        async with self._session() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT phase, notes FROM phase_state
                    WHERE user_id = {_USER_ID_SUB}
                """
                ),
                {"user_id": user_id},
            )
            row = result.fetchone()
            if not row:
                return None
            return build_phase_state(user_id=user_id, phase=row.phase, notes=row.notes)

    # --- Tool events (§9.1) ---

    async def save_tool_event(
        self,
        user_id: str,
        event: ToolEvent,
    ) -> None:
        """Save a tool invocation event."""
        async with self._session(commit=True) as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO tool_events (user_id, topic_id, tool_name,
                                             input_json, output_json, latency_ms)
                    VALUES ({_USER_ID_SUB}, :topic_id, :tool_name,
                            CAST(:input_json AS jsonb), CAST(:output_json AS jsonb), :latency_ms)
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
    return json_dumps_or_none(value)


def _load_json_or_none(raw: Any) -> Any | None:
    return json_load_or_none(raw)


def _load_json_value(raw: Any) -> Any:
    return json_load_value(raw)


def _merge_scoped_postgres_facts(rows: Sequence[Any]) -> dict[str, Any]:
    return merge_scoped_facts(rows)
