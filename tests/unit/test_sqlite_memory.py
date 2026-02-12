"""Интеграционные unit-тесты для SQLiteMemoryProvider (parity с Postgres)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cognitia.memory.sqlite import SQLiteMemoryProvider
from cognitia.memory.types import GoalState, ToolEvent


async def _init_schema(session_factory: async_sessionmaker) -> None:
    """Создать минимальную схему для memory provider."""
    async with session_factory() as session:
        # Users
        await session.execute(
            text("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_id TEXT NOT NULL UNIQUE
                )
            """)
        )

        # Messages
        await session.execute(
            text("""
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )

        # Facts
        await session.execute(
            text("""
                CREATE TABLE facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic_id TEXT,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )
        await session.execute(
            text("""
                CREATE UNIQUE INDEX uq_facts_user_topic_key
                ON facts(user_id, topic_id, key)
                WHERE topic_id IS NOT NULL
            """)
        )
        await session.execute(
            text("""
                CREATE UNIQUE INDEX uq_facts_user_global_key
                ON facts(user_id, key)
                WHERE topic_id IS NULL
            """)
        )

        # Summaries
        await session.execute(
            text("""
                CREATE TABLE summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    messages_covered INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, topic_id)
                )
            """)
        )

        # Goals
        await session.execute(
            text("""
                CREATE TABLE goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    target_amount INTEGER,
                    current_amount INTEGER NOT NULL DEFAULT 0,
                    phase TEXT NOT NULL DEFAULT '',
                    is_main INTEGER NOT NULL DEFAULT 0,
                    plan TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, topic_id)
                )
            """)
        )

        # Topics
        await session.execute(
            text("""
                CREATE TABLE topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic_id TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    active_skill_ids TEXT,
                    title TEXT,
                    prompt_hash TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, topic_id)
                )
            """)
        )

        # Phase state
        await session.execute(
            text("""
                CREATE TABLE phase_state (
                    user_id INTEGER PRIMARY KEY,
                    phase TEXT NOT NULL,
                    notes TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )

        # Tool events
        await session.execute(
            text("""
                CREATE TABLE tool_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    input_json TEXT,
                    output_json TEXT,
                    latency_ms INTEGER NOT NULL DEFAULT 0
                )
            """)
        )
        await session.commit()


@pytest.fixture()
async def provider(tmp_path: Path) -> SQLiteMemoryProvider:
    db_path = tmp_path / "memory.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    await _init_schema(sf)
    p = SQLiteMemoryProvider(sf)
    await p.ensure_user("u1")
    yield p
    await engine.dispose()


class TestSQLiteMessages:
    @pytest.mark.asyncio
    async def test_save_get_count_and_trim(self, provider: SQLiteMemoryProvider) -> None:
        await provider.save_message("u1", "t1", "user", "m1")
        await provider.save_message("u1", "t1", "assistant", "m2")
        await provider.save_message("u1", "t1", "assistant", "m3")

        messages = await provider.get_messages("u1", "t1", limit=2)
        assert [m.content for m in messages] == ["m2", "m3"]
        assert await provider.count_messages("u1", "t1") == 3

        deleted = await provider.delete_messages_before("u1", "t1", keep_last=1)
        assert deleted == 2
        assert await provider.count_messages("u1", "t1") == 1


class TestSQLiteFacts:
    @pytest.mark.asyncio
    async def test_global_and_topic_facts(self, provider: SQLiteMemoryProvider) -> None:
        await provider.upsert_fact("u1", "income", 120000, source="user")
        await provider.upsert_fact("u1", "product", "deposit", topic_id="t1", source="system")

        global_facts = await provider.get_facts("u1")
        topic_facts = await provider.get_facts("u1", topic_id="t1")

        assert global_facts == {"income": 120000}
        assert topic_facts["income"] == 120000
        assert topic_facts["product"] == "deposit"


class TestSQLiteSummaryAndGoal:
    @pytest.mark.asyncio
    async def test_summary_upsert_and_goal(self, provider: SQLiteMemoryProvider) -> None:
        await provider.save_summary("u1", "t1", "summary-1", 3)
        await provider.save_summary("u1", "t1", "summary-2", 5)
        assert await provider.get_summary("u1", "t1") == "summary-2"

        goal = GoalState(
            goal_id="t1",
            title="Подушка",
            target_amount=500000,
            current_amount=100000,
            phase="cushion",
            plan={"steps": ["a", "b"]},
            is_main=True,
        )
        await provider.save_goal("u1", goal)
        loaded = await provider.get_active_goal("u1", "t1")
        assert loaded is not None
        assert loaded.title == "Подушка"
        assert loaded.plan == {"steps": ["a", "b"]}
        assert loaded.is_main is True


class TestSQLiteSessionAndPhase:
    @pytest.mark.asyncio
    async def test_session_state_and_phase(self, provider: SQLiteMemoryProvider) -> None:
        await provider.save_session_state("u1", "t1", "coach", ["finuslugi"], prompt_hash="abc")
        state = await provider.get_session_state("u1", "t1")
        assert state is not None
        assert state["role_id"] == "coach"
        assert state["active_skill_ids"] == ["finuslugi"]
        assert state["prompt_hash"] == "abc"

        await provider.save_phase_state("u1", "debts", "Погашение")
        phase = await provider.get_phase_state("u1")
        assert phase is not None
        assert phase.phase == "debts"
        assert phase.notes == "Погашение"


class TestSQLiteToolEventsAndProfile:
    @pytest.mark.asyncio
    async def test_tool_event_and_profile(self, provider: SQLiteMemoryProvider) -> None:
        await provider.upsert_fact("u1", "age", 30)
        profile = await provider.get_user_profile("u1")
        assert profile.user_id == "u1"
        assert profile.facts["age"] == 30

        event = ToolEvent(
            topic_id="t1",
            tool_name="memory_read",
            input_json={"path": "MEMORY.md"},
            output_json={"status": "ok"},
            latency_ms=42,
        )
        # Должно сохраняться без исключений.
        await provider.save_tool_event("u1", event)
