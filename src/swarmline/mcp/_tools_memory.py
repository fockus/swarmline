"""Memory tools for Swarmline MCP server."""

from __future__ import annotations

from typing import Any

import structlog

from swarmline.mcp._session import StatefulSession

logger = structlog.get_logger(__name__)


async def memory_upsert_fact(
    session: StatefulSession,
    user_id: str,
    key: str,
    value: str,
    topic_id: str | None = None,
) -> dict[str, Any]:
    """Store or update a fact in agent memory."""
    try:
        await session.memory.upsert_fact(user_id, key, value, topic_id=topic_id)
        return {"ok": True, "data": {"key": key, "action": "upserted"}}
    except Exception as exc:
        logger.warning("memory_upsert_fact_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def memory_get_facts(
    session: StatefulSession,
    user_id: str,
    topic_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve all facts for a user, optionally scoped by topic."""
    try:
        facts = await session.memory.get_facts(user_id, topic_id=topic_id)
        return {"ok": True, "data": facts}
    except Exception as exc:
        logger.warning("memory_get_facts_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def memory_save_message(
    session: StatefulSession,
    user_id: str,
    topic_id: str,
    role: str,
    content: str,
) -> dict[str, Any]:
    """Save a chat message to conversation history."""
    try:
        await session.memory.save_message(user_id, topic_id, role, content)
        return {"ok": True, "data": {"action": "saved"}}
    except Exception as exc:
        logger.warning("memory_save_message_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def memory_get_messages(
    session: StatefulSession,
    user_id: str,
    topic_id: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Retrieve recent messages from conversation history."""
    try:
        messages = await session.memory.get_messages(user_id, topic_id, limit=limit)
        serialized = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
        return {"ok": True, "data": serialized}
    except Exception as exc:
        logger.warning("memory_get_messages_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def memory_save_summary(
    session: StatefulSession,
    user_id: str,
    topic_id: str,
    summary: str,
    messages_covered: int = 0,
) -> dict[str, Any]:
    """Save a conversation summary."""
    try:
        await session.memory.save_summary(user_id, topic_id, summary, messages_covered)
        return {"ok": True, "data": {"action": "saved"}}
    except Exception as exc:
        logger.warning("memory_save_summary_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


async def memory_get_summary(
    session: StatefulSession,
    user_id: str,
    topic_id: str,
) -> dict[str, Any]:
    """Retrieve the conversation summary for a user/topic pair."""
    try:
        summary = await session.memory.get_summary(user_id, topic_id)
        return {"ok": True, "data": {"summary": summary}}
    except Exception as exc:
        logger.warning("memory_get_summary_failed", error=str(exc))
        return {"ok": False, "error": str(exc)}
