"""UC7: Learning Agent -- Store code-review patterns as facts, recall them,
update with improved versions, and document application history via messages.

Headless E2E test: validates pattern storage, overwrite semantics,
and learning history via messages without any LLM calls.
"""

from __future__ import annotations

import pytest

from swarmline.mcp._session import StatefulSession
from swarmline.mcp._tools_memory import (
    memory_get_facts,
    memory_get_messages,
    memory_save_message,
    memory_upsert_fact,
)

AGENT_NS = "learning-agent"
TOPIC = "pattern-history"


@pytest.fixture
async def session():
    s = StatefulSession(mode="headless")
    yield s
    await s.cleanup()


async def test_store_and_recall_patterns(session: StatefulSession):
    """Patterns stored as facts are retrievable."""
    await memory_upsert_fact(
        session,
        user_id=AGENT_NS,
        key="error-handling",
        value="Always use try/except with specific exceptions",
    )
    await memory_upsert_fact(
        session,
        user_id=AGENT_NS,
        key="naming",
        value="Use snake_case for functions, PascalCase for classes",
    )

    facts = await memory_get_facts(session, user_id=AGENT_NS)
    assert facts["ok"] is True
    assert len(facts["data"]) == 2

    assert "error-handling" in facts["data"]
    assert "naming" in facts["data"]
    assert "specific exceptions" in facts["data"]["error-handling"]
    assert "snake_case" in facts["data"]["naming"]


async def test_update_pattern_overwrites(session: StatefulSession):
    """Updating an existing pattern key replaces the value."""
    original = "Always use try/except with specific exceptions"
    updated = "Use try/except with specific exceptions + log with structlog"

    await memory_upsert_fact(
        session,
        user_id=AGENT_NS,
        key="error-handling",
        value=original,
    )
    await memory_upsert_fact(
        session,
        user_id=AGENT_NS,
        key="error-handling",
        value=updated,
    )

    facts = await memory_get_facts(session, user_id=AGENT_NS)
    assert facts["ok"] is True
    assert "structlog" in facts["data"]["error-handling"]


async def test_learning_history_via_messages(session: StatefulSession):
    """Messages document when and how patterns were applied."""
    await memory_save_message(
        session,
        user_id=AGENT_NS,
        topic_id=TOPIC,
        role="system",
        content="Pattern 'error-handling' applied in auth_service.py:45",
    )
    await memory_save_message(
        session,
        user_id=AGENT_NS,
        topic_id=TOPIC,
        role="system",
        content="Pattern 'naming' applied in user_repository.py:12",
    )
    await memory_save_message(
        session,
        user_id=AGENT_NS,
        topic_id=TOPIC,
        role="system",
        content="Pattern 'error-handling' updated: added structlog requirement",
    )

    msgs = await memory_get_messages(
        session, user_id=AGENT_NS, topic_id=TOPIC, limit=10
    )
    assert msgs["ok"] is True
    assert len(msgs["data"]) == 3

    contents = [m["content"] for m in msgs["data"]]
    assert any("auth_service" in c for c in contents)
    assert any("updated" in c for c in contents)


async def test_full_learning_cycle(session: StatefulSession):
    """Full cycle: store patterns, apply them, update, verify final state."""
    # 1. Store initial patterns
    patterns = {
        "error-handling": "Always use try/except with specific exceptions",
        "naming": "Use snake_case for functions, PascalCase for classes",
        "logging": "Use structlog with bound context",
    }
    for key, value in patterns.items():
        res = await memory_upsert_fact(session, user_id=AGENT_NS, key=key, value=value)
        assert res["ok"] is True

    # 2. Document application of patterns
    await memory_save_message(
        session,
        user_id=AGENT_NS,
        topic_id=TOPIC,
        role="assistant",
        content="Applied 'error-handling' to payment_service.py",
    )
    await memory_save_message(
        session,
        user_id=AGENT_NS,
        topic_id=TOPIC,
        role="assistant",
        content="Applied 'naming' to models/user.py",
    )

    # 3. Update a pattern based on learning
    await memory_upsert_fact(
        session,
        user_id=AGENT_NS,
        key="error-handling",
        value="Use try/except with specific exceptions + log with structlog + add correlation_id",
    )

    # 4. Verify final state
    facts = await memory_get_facts(session, user_id=AGENT_NS)
    assert facts["ok"] is True
    assert len(facts["data"]) == 3

    assert "correlation_id" in facts["data"]["error-handling"]

    msgs = await memory_get_messages(
        session, user_id=AGENT_NS, topic_id=TOPIC, limit=10
    )
    assert msgs["ok"] is True
    assert len(msgs["data"]) == 2
