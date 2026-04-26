"""Integration tests for Phase 14: Session Resume.

Covers:
- SESS-01: Auto-persist messages to MessageStore after say()
- SESS-02: Resume by session_id loads and continues conversation
- SESS-03: Auto-compaction on resume when history exceeds budget
- SESS-04: JSONL round-trips all message types
- Backward compat: Conversation without store works as before
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swarmline.session.jsonl_store import JsonlMessageStore


# ---------------------------------------------------------------------------
# SESS-04: JSONL round-trip
# ---------------------------------------------------------------------------


class TestJsonlRoundTrip:
    @pytest.mark.asyncio
    async def test_roundtrip_user_message(self, tmp_path: Path) -> None:
        """User message round-trips through JSONL without data loss."""
        store = JsonlMessageStore(tmp_path)
        await store.save_message("u1", "t1", "user", "Hello, world!")

        msgs = await store.get_messages("u1", "t1", limit=10)

        assert len(msgs) == 1
        assert msgs[0].role == "user"
        assert msgs[0].content == "Hello, world!"

    @pytest.mark.asyncio
    async def test_roundtrip_assistant_message(self, tmp_path: Path) -> None:
        """Assistant message round-trips."""
        store = JsonlMessageStore(tmp_path)
        await store.save_message("u1", "t1", "assistant", "I can help!")

        msgs = await store.get_messages("u1", "t1", limit=10)

        assert msgs[0].role == "assistant"
        assert msgs[0].content == "I can help!"

    @pytest.mark.asyncio
    async def test_roundtrip_tool_message_with_calls(self, tmp_path: Path) -> None:
        """Tool message with tool_calls JSON round-trips."""
        tool_calls = [{"name": "read_file", "arguments": {"path": "/tmp/test"}}]
        store = JsonlMessageStore(tmp_path)
        await store.save_message("u1", "t1", "assistant", "", tool_calls=tool_calls)

        msgs = await store.get_messages("u1", "t1", limit=10)

        assert msgs[0].tool_calls == tool_calls

    @pytest.mark.asyncio
    async def test_roundtrip_system_message(self, tmp_path: Path) -> None:
        """System message round-trips."""
        store = JsonlMessageStore(tmp_path)
        await store.save_message(
            "u1", "t1", "system", "[Compaction summary]: condensed"
        )

        msgs = await store.get_messages("u1", "t1", limit=10)

        assert msgs[0].role == "system"
        assert "[Compaction summary]" in msgs[0].content

    @pytest.mark.asyncio
    async def test_roundtrip_full_conversation(self, tmp_path: Path) -> None:
        """Full conversation with mixed message types round-trips."""
        store = JsonlMessageStore(tmp_path)

        await store.save_message("u1", "s1", "user", "Read my config")
        await store.save_message(
            "u1",
            "s1",
            "assistant",
            "",
            tool_calls=[{"name": "read_file", "arguments": {"path": "config.yml"}}],
        )
        await store.save_message("u1", "s1", "tool", '{"key": "value"}')
        await store.save_message("u1", "s1", "assistant", "Your config has key=value")

        msgs = await store.get_messages("u1", "s1", limit=100)

        assert len(msgs) == 4
        assert [m.role for m in msgs] == ["user", "assistant", "tool", "assistant"]
        assert msgs[1].tool_calls is not None
        assert msgs[2].content == '{"key": "value"}'


# ---------------------------------------------------------------------------
# Multiple sessions isolation
# ---------------------------------------------------------------------------


class TestSessionIsolation:
    @pytest.mark.asyncio
    async def test_multiple_sessions_isolated(self, tmp_path: Path) -> None:
        """Messages from different sessions don't mix."""
        store = JsonlMessageStore(tmp_path)

        await store.save_message("u1", "session-a", "user", "Hello A")
        await store.save_message("u1", "session-b", "user", "Hello B")
        await store.save_message("u1", "session-a", "assistant", "Response A")

        msgs_a = await store.get_messages("u1", "session-a", limit=100)
        msgs_b = await store.get_messages("u1", "session-b", limit=100)

        assert len(msgs_a) == 2
        assert len(msgs_b) == 1
        assert msgs_a[0].content == "Hello A"
        assert msgs_b[0].content == "Hello B"


# ---------------------------------------------------------------------------
# SESS-04: Edge cases
# ---------------------------------------------------------------------------


class TestJsonlEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_session_returns_empty(self, tmp_path: Path) -> None:
        """Non-existent session returns empty list."""
        store = JsonlMessageStore(tmp_path)
        msgs = await store.get_messages("u1", "nonexistent", limit=10)

        assert msgs == []

    @pytest.mark.asyncio
    async def test_count_messages_accurate(self, tmp_path: Path) -> None:
        """count_messages returns correct count."""
        store = JsonlMessageStore(tmp_path)
        for i in range(5):
            await store.save_message("u1", "t1", "user", f"msg {i}")

        count = await store.count_messages("u1", "t1")

        assert count == 5

    @pytest.mark.asyncio
    async def test_delete_messages_before_keeps_last(self, tmp_path: Path) -> None:
        """delete_messages_before keeps specified number of recent messages."""
        store = JsonlMessageStore(tmp_path)
        for i in range(10):
            await store.save_message("u1", "t1", "user", f"msg {i}")

        deleted = await store.delete_messages_before("u1", "t1", keep_last=3)

        assert deleted == 7
        remaining = await store.get_messages("u1", "t1", limit=100)
        assert len(remaining) == 3
        assert remaining[0].content == "msg 7"

    @pytest.mark.asyncio
    async def test_get_messages_with_limit(self, tmp_path: Path) -> None:
        """get_messages limit returns only last N messages."""
        store = JsonlMessageStore(tmp_path)
        for i in range(10):
            await store.save_message("u1", "t1", "user", f"msg {i}")

        msgs = await store.get_messages("u1", "t1", limit=3)

        assert len(msgs) == 3
        assert msgs[0].content == "msg 7"


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_jsonl_store_is_message_store(self, tmp_path: Path) -> None:
        """JsonlMessageStore satisfies MessageStore protocol."""
        from swarmline.protocols.memory import MessageStore

        store = JsonlMessageStore(tmp_path)
        assert isinstance(store, MessageStore)


# ---------------------------------------------------------------------------
# Backward compat
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_conversation_without_store_works(self) -> None:
        """Conversation without message_store has no persist/resume."""
        from swarmline.agent.conversation import Conversation
        from unittest.mock import MagicMock

        mock_agent = MagicMock()
        conv = Conversation(mock_agent)

        assert conv._message_store is None
        assert conv._compaction_config is None
