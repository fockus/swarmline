"""Tests for Conversation session resume, auto-persist, and auto-compact (Phase 14, Task 2).

TDD Red phase — tests written BEFORE implementation.
Covers: resume(), auto-persist in say(), auto-compact on resume, backward compat.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from swarmline.compaction import CompactionConfig
from swarmline.domain_types import ImageBlock, Message, TextBlock
from swarmline.memory.types import MemoryMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory_messages(count: int) -> list[MemoryMessage]:
    """Create a list of MemoryMessage objects for testing."""
    msgs: list[MemoryMessage] = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append(MemoryMessage(role=role, content=f"message-{i}"))
    return msgs


def _make_agent_stub(system_prompt: str = "test") -> SimpleNamespace:
    """Create a minimal Agent-like stub for Conversation init."""
    config = SimpleNamespace(
        system_prompt=system_prompt,
        runtime="thin",
        middleware=(),
        hooks=None,
    )
    return SimpleNamespace(config=config, runtime_factory=None)


def _done_event(text: str) -> SimpleNamespace:
    """Create a done/final event for mocking _execute."""
    return SimpleNamespace(
        type="done",
        text=text,
        session_id=None,
        total_cost_usd=None,
        usage=None,
        structured_output=None,
        native_metadata=None,
        new_messages=None,
        data={},
    )


# ---------------------------------------------------------------------------
# Resume: load history from message_store
# ---------------------------------------------------------------------------


class TestConversationResume:
    @pytest.mark.asyncio
    async def test_conversation_resume_loads_history(self) -> None:
        """resume() loads messages from store and populates _history."""
        from swarmline.agent.conversation import Conversation

        store = AsyncMock()
        store.get_messages = AsyncMock(
            return_value=[
                MemoryMessage(role="user", content="hello"),
                MemoryMessage(role="assistant", content="hi there"),
            ]
        )

        conv = Conversation(
            agent=_make_agent_stub(),
            message_store=store,
            user_id="u1",
        )
        await conv.resume("sess-abc")

        store.get_messages.assert_awaited_once_with("u1", "sess-abc", limit=2**31 - 1)
        assert len(conv.history) == 2
        assert conv.history[0].role == "user"
        assert conv.history[0].content == "hello"
        assert conv.history[1].role == "assistant"
        assert conv.history[1].content == "hi there"
        assert all(isinstance(m, Message) for m in conv.history)

    @pytest.mark.asyncio
    async def test_conversation_resume_empty_session(self) -> None:
        """resume() with no stored messages results in empty history."""
        from swarmline.agent.conversation import Conversation

        store = AsyncMock()
        store.get_messages = AsyncMock(return_value=[])

        conv = Conversation(
            agent=_make_agent_stub(),
            message_store=store,
            user_id="u1",
        )
        await conv.resume("empty-sess")

        store.get_messages.assert_awaited_once()
        assert conv.history == []

    @pytest.mark.asyncio
    async def test_conversation_resume_nonexistent_session(self) -> None:
        """resume() with nonexistent session returns empty, no error."""
        from swarmline.agent.conversation import Conversation

        store = AsyncMock()
        store.get_messages = AsyncMock(return_value=[])

        conv = Conversation(
            agent=_make_agent_stub(),
            message_store=store,
            user_id="u1",
        )
        await conv.resume("nonexistent-session-id")

        assert conv.history == []

    @pytest.mark.asyncio
    async def test_conversation_resume_updates_session_id(self) -> None:
        """resume() updates _session_id to the resumed session."""
        from swarmline.agent.conversation import Conversation

        store = AsyncMock()
        store.get_messages = AsyncMock(return_value=[])

        conv = Conversation(
            agent=_make_agent_stub(),
            session_id="original",
            message_store=store,
            user_id="u1",
        )
        await conv.resume("new-session")

        assert conv.session_id == "new-session"


# ---------------------------------------------------------------------------
# Auto-persist: save messages after say()
# ---------------------------------------------------------------------------


class TestConversationAutoPersist:
    @pytest.mark.asyncio
    async def test_conversation_auto_persist_saves_after_say(self) -> None:
        """say() saves both user message and assistant response to store."""
        from swarmline.agent.conversation import Conversation

        store = AsyncMock()
        store.save_message = AsyncMock()
        store.get_messages = AsyncMock(return_value=[])

        conv = Conversation(
            agent=_make_agent_stub(),
            session_id="s1",
            message_store=store,
            user_id="u1",
        )

        async def _fake_execute(prompt: str):
            yield _done_event("response text")

        with patch.object(conv, "_execute", side_effect=_fake_execute):
            await conv.say("hello agent")

        # Should have saved user message + assistant response
        assert store.save_message.await_count == 2

        # First call: user message
        user_call = store.save_message.await_args_list[0]
        assert user_call.args == ("u1", "s1", "user", "hello agent", None)
        assert user_call.kwargs == {
            "name": None,
            "metadata": None,
            "content_blocks": None,
        }

        # Second call: assistant response
        assistant_call = store.save_message.await_args_list[1]
        assert assistant_call.args == ("u1", "s1", "assistant", "response text", None)
        assert assistant_call.kwargs == {
            "name": None,
            "metadata": None,
            "content_blocks": None,
        }

    @pytest.mark.asyncio
    async def test_conversation_no_store_no_persist(self) -> None:
        """Without message_store, say() works normally without persistence."""
        from swarmline.agent.conversation import Conversation

        conv = Conversation(
            agent=_make_agent_stub(),
            session_id="s1",
        )
        # No message_store — should not crash

        async def _fake_execute(prompt: str):
            yield _done_event("ok")

        with patch.object(conv, "_execute", side_effect=_fake_execute):
            result = await conv.say("test")

        assert result.text == "ok"
        assert len(conv.history) == 2  # user + assistant


# ---------------------------------------------------------------------------
# Auto-compact on resume
# ---------------------------------------------------------------------------


class TestConversationAutoCompact:
    @pytest.mark.asyncio
    async def test_conversation_auto_compact_on_resume(self) -> None:
        """Large history triggers compaction during resume()."""
        from swarmline.agent.conversation import Conversation

        # Create enough messages to exceed a low threshold
        stored = _make_memory_messages(40)
        store = AsyncMock()
        store.get_messages = AsyncMock(return_value=stored)

        # Very low threshold so compaction fires
        compaction_cfg = CompactionConfig(
            threshold_tokens=50,
            preserve_recent_pairs=1,
        )

        conv = Conversation(
            agent=_make_agent_stub(),
            message_store=store,
            user_id="u1",
            compaction_config=compaction_cfg,
        )
        await conv.resume("sess-big")

        # After compaction, history should be shorter than raw 40 messages
        assert len(conv.history) < 40
        assert len(conv.history) > 0

    @pytest.mark.asyncio
    async def test_conversation_auto_compact_skipped_under_threshold(self) -> None:
        """Small history does not trigger compaction."""
        from swarmline.agent.conversation import Conversation

        stored = [
            MemoryMessage(role="user", content="hi"),
            MemoryMessage(role="assistant", content="hello"),
        ]
        store = AsyncMock()
        store.get_messages = AsyncMock(return_value=stored)

        # High threshold — no compaction needed
        compaction_cfg = CompactionConfig(threshold_tokens=100_000)

        conv = Conversation(
            agent=_make_agent_stub(),
            message_store=store,
            user_id="u1",
            compaction_config=compaction_cfg,
        )
        await conv.resume("sess-small")

        # History should remain unchanged (2 messages, no compaction)
        assert len(conv.history) == 2
        assert conv.history[0].content == "hi"
        assert conv.history[1].content == "hello"


# ---------------------------------------------------------------------------
# Resume then say: continuity
# ---------------------------------------------------------------------------


class TestConversationResumeThenSay:
    @pytest.mark.asyncio
    async def test_conversation_resume_then_say_continues(self) -> None:
        """resume() + say() = history includes resumed + new messages."""
        from swarmline.agent.conversation import Conversation

        store = AsyncMock()
        store.get_messages = AsyncMock(
            return_value=[
                MemoryMessage(role="user", content="old-q"),
                MemoryMessage(role="assistant", content="old-a"),
            ]
        )
        store.save_message = AsyncMock()

        conv = Conversation(
            agent=_make_agent_stub(),
            session_id="s1",
            message_store=store,
            user_id="u1",
        )
        await conv.resume("s1")

        async def _fake_execute(prompt: str):
            yield _done_event("new-answer")

        with patch.object(conv, "_execute", side_effect=_fake_execute):
            await conv.say("new-question")

        # 2 resumed + 1 user + 1 assistant = 4
        assert len(conv.history) == 4
        assert conv.history[0].content == "old-q"
        assert conv.history[1].content == "old-a"
        assert conv.history[2].content == "new-question"
        assert conv.history[3].content == "new-answer"

    @pytest.mark.asyncio
    async def test_resume_preserves_metadata_and_content_blocks(self) -> None:
        """resume() restores name/metadata/content_blocks from MemoryMessage."""
        from swarmline.agent.conversation import Conversation

        store = AsyncMock()
        store.get_messages = AsyncMock(
            return_value=[
                MemoryMessage(
                    role="user",
                    content="Analyze image",
                    name="alice",
                    metadata={"non_compactable": True},
                    content_blocks=[
                        {"type": "text", "text": "Analyze image"},
                        {"type": "image", "data": "aW1hZw==", "media_type": "image/png"},
                    ],
                ),
            ]
        )

        conv = Conversation(
            agent=_make_agent_stub(),
            session_id="s1",
            message_store=store,
            user_id="u1",
        )
        await conv.resume("s1")

        assert len(conv.history) == 1
        restored = conv.history[0]
        assert restored.name == "alice"
        assert restored.metadata == {"non_compactable": True}
        assert restored.content_blocks is not None
        assert restored.content_blocks == [
            TextBlock(text="Analyze image"),
            ImageBlock(data="aW1hZw==", media_type="image/png"),
        ]


# ---------------------------------------------------------------------------
# No message_store: resume raises
# ---------------------------------------------------------------------------


class TestConversationResumeWithoutStore:
    @pytest.mark.asyncio
    async def test_conversation_resume_without_store_raises(self) -> None:
        """resume() without message_store raises RuntimeError."""
        from swarmline.agent.conversation import Conversation

        conv = Conversation(agent=_make_agent_stub())
        with pytest.raises(RuntimeError, match="message_store"):
            await conv.resume("any-session")


class TestConversationJsonlRoundtrip:
    @pytest.mark.asyncio
    async def test_jsonl_resume_roundtrip_preserves_extended_fields(
        self, tmp_path: Path
    ) -> None:
        """Jsonl store keeps name/metadata/content_blocks through resume()."""
        from swarmline.agent.conversation import Conversation
        from swarmline.session.jsonl_store import JsonlMessageStore

        store = JsonlMessageStore(base_dir=tmp_path)
        await store.save_message(
            "u1",
            "sess-rich",
            "user",
            "Analyze this image",
            name="alice",
            metadata={"non_compactable": True, "source": "test"},
            content_blocks=[
                {"type": "text", "text": "Analyze this image"},
                {"type": "image", "data": "aW1hZw==", "media_type": "image/png"},
            ],
        )

        conv = Conversation(
            agent=_make_agent_stub(),
            message_store=store,
            user_id="u1",
        )
        await conv.resume("sess-rich")

        assert len(conv.history) == 1
        restored = conv.history[0]
        assert restored.name == "alice"
        assert restored.metadata == {"non_compactable": True, "source": "test"}
        assert restored.content_blocks == [
            TextBlock(text="Analyze this image"),
            ImageBlock(data="aW1hZw==", media_type="image/png"),
        ]
