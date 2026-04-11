"""UC2: Persistent Brain -- Facts persist within session, support overwrite,
isolate by user_id. Messages and summaries round-trip correctly.

Headless E2E test: validates memory isolation, overwrite semantics,
and message/summary storage without any LLM calls.
"""

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
async def session():
    s = StatefulSession(mode="headless")
    yield s
    await s.cleanup()


async def test_fact_isolation_between_users(session: StatefulSession):
    """Facts stored for user_A are invisible to user_B."""
    await memory_upsert_fact(session, user_id="user-a", key="lang", value="Python")
    await memory_upsert_fact(session, user_id="user-b", key="lang", value="Rust")

    facts_a = await memory_get_facts(session, user_id="user-a")
    facts_b = await memory_get_facts(session, user_id="user-b")

    assert facts_a["ok"] is True
    assert facts_b["ok"] is True

    # get_facts returns dict[str, Any] — key-value mapping
    assert facts_a["data"]["lang"] == "Python"
    assert facts_b["data"]["lang"] == "Rust"
    assert "Rust" not in str(facts_a["data"].values())
    assert "Python" not in str(facts_b["data"].values())


async def test_fact_overwrite_same_key(session: StatefulSession):
    """Upserting the same key replaces the value."""
    await memory_upsert_fact(session, user_id="dev", key="editor", value="vim")
    await memory_upsert_fact(session, user_id="dev", key="editor", value="neovim")

    facts = await memory_get_facts(session, user_id="dev")
    assert facts["ok"] is True

    # The latest value should be present (upsert overwrites)
    assert facts["data"]["editor"] == "neovim"


async def test_messages_round_trip(session: StatefulSession):
    """Messages are saved and retrieved in order."""
    uid, tid = "user-msg", "topic-1"

    await memory_save_message(session, user_id=uid, topic_id=tid, role="user", content="Hello")
    await memory_save_message(session, user_id=uid, topic_id=tid, role="assistant", content="Hi!")
    await memory_save_message(session, user_id=uid, topic_id=tid, role="user", content="How?")

    msgs = await memory_get_messages(session, user_id=uid, topic_id=tid, limit=10)
    assert msgs["ok"] is True
    assert len(msgs["data"]) == 3

    roles = [m["role"] for m in msgs["data"]]
    assert roles == ["user", "assistant", "user"]


async def test_summary_round_trip(session: StatefulSession):
    """Summary is saved and retrieved for a user/topic pair."""
    uid, tid = "user-sum", "topic-recap"
    text = "Discussion covered Python async patterns and error handling."

    res = await memory_save_summary(
        session, user_id=uid, topic_id=tid, summary=text, messages_covered=5,
    )
    assert res["ok"] is True

    got = await memory_get_summary(session, user_id=uid, topic_id=tid)
    assert got["ok"] is True
    assert text in str(got["data"])


async def test_multiple_facts_per_user(session: StatefulSession):
    """A user can store multiple distinct facts."""
    uid = "multi-fact-user"
    await memory_upsert_fact(session, user_id=uid, key="preference", value="dark-mode")
    await memory_upsert_fact(session, user_id=uid, key="timezone", value="UTC+3")
    await memory_upsert_fact(session, user_id=uid, key="language", value="en")

    facts = await memory_get_facts(session, user_id=uid)
    assert facts["ok"] is True
    # get_facts returns dict[str, Any] — 3 keys
    assert len(facts["data"]) == 3
    assert facts["data"]["preference"] == "dark-mode"
    assert facts["data"]["timezone"] == "UTC+3"
    assert facts["data"]["language"] == "en"
