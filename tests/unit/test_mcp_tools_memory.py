"""Tests for MCP memory tools."""

from __future__ import annotations

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_memory import (
    memory_get_facts,
    memory_get_messages,
    memory_get_summary,
    memory_save_message,
    memory_save_summary,
    memory_upsert_fact,
)


@pytest.fixture
def session() -> StatefulSession:
    return StatefulSession(mode="headless")


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


class TestMemoryUpsertFact:
    async def test_upsert_fact_returns_ok(self, session: StatefulSession) -> None:
        result = await memory_upsert_fact(session, "user1", "db", "PostgreSQL")
        assert result["ok"] is True
        assert result["data"]["key"] == "db"
        assert result["data"]["action"] == "upserted"

    async def test_upsert_and_get_roundtrip(self, session: StatefulSession) -> None:
        await memory_upsert_fact(session, "user1", "db", "PostgreSQL")
        facts = await memory_get_facts(session, "user1")
        assert facts["ok"] is True
        assert facts["data"]["db"] == "PostgreSQL"

    async def test_upsert_overwrites_existing_value(
        self, session: StatefulSession
    ) -> None:
        await memory_upsert_fact(session, "user1", "db", "MySQL")
        await memory_upsert_fact(session, "user1", "db", "PostgreSQL")
        facts = await memory_get_facts(session, "user1")
        assert facts["data"]["db"] == "PostgreSQL"

    async def test_facts_isolated_by_user(self, session: StatefulSession) -> None:
        await memory_upsert_fact(session, "user1", "k", "v1")
        await memory_upsert_fact(session, "user2", "k", "v2")
        f1 = await memory_get_facts(session, "user1")
        f2 = await memory_get_facts(session, "user2")
        assert f1["data"]["k"] == "v1"
        assert f2["data"]["k"] == "v2"

    async def test_upsert_with_topic_id_scoped(self, session: StatefulSession) -> None:
        await memory_upsert_fact(session, "user1", "lang", "Python", topic_id="proj-a")
        # Global facts should not contain topic-scoped fact
        global_facts = await memory_get_facts(session, "user1")
        assert "lang" not in global_facts["data"]
        # Topic-scoped query should include it
        scoped = await memory_get_facts(session, "user1", topic_id="proj-a")
        assert scoped["data"]["lang"] == "Python"


class TestMemoryGetFacts:
    async def test_get_facts_empty_returns_empty_dict(
        self, session: StatefulSession
    ) -> None:
        facts = await memory_get_facts(session, "nobody")
        assert facts["ok"] is True
        assert facts["data"] == {}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class TestMemorySaveMessage:
    async def test_save_message_returns_ok(self, session: StatefulSession) -> None:
        result = await memory_save_message(session, "u1", "topic1", "user", "hello")
        assert result["ok"] is True
        assert result["data"]["action"] == "saved"

    async def test_save_and_get_messages_roundtrip(
        self, session: StatefulSession
    ) -> None:
        await memory_save_message(session, "u1", "t1", "user", "hello")
        await memory_save_message(session, "u1", "t1", "assistant", "hi there")
        msgs = await memory_get_messages(session, "u1", "t1")
        assert msgs["ok"] is True
        assert len(msgs["data"]) == 2
        assert msgs["data"][0]["role"] == "user"
        assert msgs["data"][0]["content"] == "hello"
        assert msgs["data"][1]["role"] == "assistant"
        assert msgs["data"][1]["content"] == "hi there"

    async def test_get_messages_respects_limit(self, session: StatefulSession) -> None:
        for i in range(5):
            await memory_save_message(session, "u1", "t1", "user", f"msg-{i}")
        msgs = await memory_get_messages(session, "u1", "t1", limit=2)
        assert len(msgs["data"]) == 2
        # Should return the last 2 messages
        assert msgs["data"][0]["content"] == "msg-3"
        assert msgs["data"][1]["content"] == "msg-4"


class TestMemoryGetMessages:
    async def test_get_messages_empty_returns_empty_list(
        self, session: StatefulSession
    ) -> None:
        msgs = await memory_get_messages(session, "nobody", "no-topic")
        assert msgs["ok"] is True
        assert msgs["data"] == []


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


class TestMemorySaveSummary:
    async def test_save_summary_returns_ok(self, session: StatefulSession) -> None:
        result = await memory_save_summary(
            session, "u1", "t1", "conversation about X", 5
        )
        assert result["ok"] is True
        assert result["data"]["action"] == "saved"

    async def test_save_and_get_summary_roundtrip(
        self, session: StatefulSession
    ) -> None:
        await memory_save_summary(session, "u1", "t1", "summary text here", 10)
        result = await memory_get_summary(session, "u1", "t1")
        assert result["ok"] is True
        assert result["data"]["summary"] == "summary text here"

    async def test_save_summary_overwrites(self, session: StatefulSession) -> None:
        await memory_save_summary(session, "u1", "t1", "old summary", 5)
        await memory_save_summary(session, "u1", "t1", "new summary", 10)
        result = await memory_get_summary(session, "u1", "t1")
        assert result["data"]["summary"] == "new summary"


class TestMemoryGetSummary:
    async def test_get_summary_missing_returns_none(
        self, session: StatefulSession
    ) -> None:
        result = await memory_get_summary(session, "nobody", "no-topic")
        assert result["ok"] is True
        assert result["data"]["summary"] is None
