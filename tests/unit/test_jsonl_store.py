"""Tests for JsonlMessageStore — JSONL file-based MessageStore implementation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarmline.memory.types import MemoryMessage
from swarmline.session.jsonl_store import JsonlMessageStore


@pytest.fixture
def store(tmp_path: Path) -> JsonlMessageStore:
    return JsonlMessageStore(base_dir=tmp_path)


@pytest.fixture
def session_path(tmp_path: Path, store: JsonlMessageStore) -> Path:
    return store._session_path("alice", "chat1")


# --- save_message ---


async def test_save_message_creates_jsonl_file(
    store: JsonlMessageStore, session_path: Path
) -> None:
    """First save_message creates the JSONL file on disk."""
    await store.save_message("alice", "chat1", "user", "hello")

    assert session_path.exists()
    lines = session_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["role"] == "user"
    assert record["content"] == "hello"
    assert "ts" in record


async def test_save_message_appends_to_existing(
    store: JsonlMessageStore, session_path: Path
) -> None:
    """Subsequent save_message calls append lines, not overwrite."""
    await store.save_message("alice", "chat1", "user", "first")
    await store.save_message("alice", "chat1", "assistant", "second")

    lines = session_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["content"] == "first"
    assert json.loads(lines[1])["content"] == "second"


# --- get_messages ---


async def test_get_messages_returns_saved(store: JsonlMessageStore) -> None:
    """get_messages returns all saved messages when count <= limit."""
    await store.save_message("alice", "chat1", "user", "hi")
    await store.save_message("alice", "chat1", "assistant", "hey")

    msgs = await store.get_messages("alice", "chat1", limit=10)

    assert len(msgs) == 2
    assert all(isinstance(m, MemoryMessage) for m in msgs)
    assert msgs[0].role == "user"
    assert msgs[0].content == "hi"
    assert msgs[1].role == "assistant"
    assert msgs[1].content == "hey"


async def test_get_messages_with_limit(store: JsonlMessageStore) -> None:
    """get_messages respects the limit parameter, returning last N."""
    for i in range(5):
        await store.save_message("alice", "chat1", "user", f"msg-{i}")

    msgs = await store.get_messages("alice", "chat1", limit=2)

    assert len(msgs) == 2
    assert msgs[0].content == "msg-3"
    assert msgs[1].content == "msg-4"


async def test_get_messages_empty_returns_empty(store: JsonlMessageStore) -> None:
    """get_messages on a session with no messages returns empty list."""
    # File exists but is empty
    store._session_path("alice", "chat1").touch()

    msgs = await store.get_messages("alice", "chat1")

    assert msgs == []


async def test_get_messages_nonexistent_returns_empty(store: JsonlMessageStore) -> None:
    """get_messages on a nonexistent session file returns empty list."""
    msgs = await store.get_messages("alice", "no-such-topic")

    assert msgs == []


# --- count_messages ---


async def test_count_messages_accurate(store: JsonlMessageStore) -> None:
    """count_messages returns exact number of saved messages."""
    assert await store.count_messages("alice", "chat1") == 0

    await store.save_message("alice", "chat1", "user", "one")
    assert await store.count_messages("alice", "chat1") == 1

    await store.save_message("alice", "chat1", "assistant", "two")
    assert await store.count_messages("alice", "chat1") == 2


# --- delete_messages_before ---


async def test_delete_messages_before_keeps_last_n(store: JsonlMessageStore) -> None:
    """delete_messages_before rewrites file keeping only last keep_last lines."""
    for i in range(10):
        await store.save_message("alice", "chat1", "user", f"msg-{i}")

    deleted = await store.delete_messages_before("alice", "chat1", keep_last=3)

    assert deleted == 7
    msgs = await store.get_messages("alice", "chat1", limit=100)
    assert len(msgs) == 3
    assert msgs[0].content == "msg-7"
    assert msgs[1].content == "msg-8"
    assert msgs[2].content == "msg-9"


# --- Roundtrip tests ---


async def test_roundtrip_user_message(store: JsonlMessageStore) -> None:
    """User message roundtrips correctly through save/get."""
    await store.save_message("bob", "t1", "user", "What is 2+2?")

    msgs = await store.get_messages("bob", "t1")

    assert len(msgs) == 1
    assert msgs[0] == MemoryMessage(role="user", content="What is 2+2?")


async def test_roundtrip_assistant_message(store: JsonlMessageStore) -> None:
    """Assistant message roundtrips correctly through save/get."""
    await store.save_message("bob", "t1", "assistant", "The answer is 4.")

    msgs = await store.get_messages("bob", "t1")

    assert len(msgs) == 1
    assert msgs[0] == MemoryMessage(role="assistant", content="The answer is 4.")


async def test_roundtrip_tool_message_with_name(store: JsonlMessageStore) -> None:
    """Tool message with tool_calls=None roundtrips via role field."""
    await store.save_message("bob", "t1", "tool", "result: 42")

    msgs = await store.get_messages("bob", "t1")

    assert len(msgs) == 1
    assert msgs[0].role == "tool"
    assert msgs[0].content == "result: 42"
    assert msgs[0].tool_calls is None


async def test_roundtrip_tool_calls_json(store: JsonlMessageStore) -> None:
    """Messages with tool_calls serialize/deserialize correctly."""
    calls = [{"id": "tc1", "name": "calculator", "arguments": {"expr": "2+2"}}]
    await store.save_message(
        "bob", "t1", "assistant", "Let me calculate.", tool_calls=calls
    )

    msgs = await store.get_messages("bob", "t1")

    assert len(msgs) == 1
    assert msgs[0].tool_calls == calls
    assert msgs[0].content == "Let me calculate."


async def test_roundtrip_extended_message_fields(store: JsonlMessageStore) -> None:
    """name/metadata/content_blocks survive JSONL save/get roundtrip."""
    blocks = [
        {"type": "text", "text": "Check this"},
        {"type": "image", "data": "aW1hZw==", "media_type": "image/png"},
    ]
    metadata = {"non_compactable": True, "source": "test"}

    await store.save_message(
        "bob",
        "t1",
        "user",
        "Check this",
        name="tester",
        metadata=metadata,
        content_blocks=blocks,
    )

    msgs = await store.get_messages("bob", "t1")
    assert len(msgs) == 1
    assert msgs[0].name == "tester"
    assert msgs[0].metadata == metadata
    assert msgs[0].content_blocks == blocks


# --- Isolation ---


async def test_file_per_session_isolated(store: JsonlMessageStore) -> None:
    """Different (user_id, topic_id) pairs use separate files."""
    await store.save_message("alice", "chat1", "user", "alice-msg")
    await store.save_message("bob", "chat2", "user", "bob-msg")

    alice_msgs = await store.get_messages("alice", "chat1")
    bob_msgs = await store.get_messages("bob", "chat2")

    assert len(alice_msgs) == 1
    assert alice_msgs[0].content == "alice-msg"
    assert len(bob_msgs) == 1
    assert bob_msgs[0].content == "bob-msg"


# --- Edge cases with parametrize ---


@pytest.mark.parametrize(
    ("role", "content", "tool_calls"),
    [
        ("user", "", None),
        ("assistant", "multiline\ncontent\nhere", None),
        ("user", 'content with "quotes" and \\backslashes', None),
        ("assistant", "", [{"id": "t1", "name": "noop", "arguments": {}}]),
        ("system", "system prompt", None),
    ],
    ids=[
        "empty_content",
        "multiline_content",
        "special_chars",
        "empty_content_with_tool_calls",
        "system_role",
    ],
)
async def test_roundtrip_edge_cases(
    store: JsonlMessageStore,
    role: str,
    content: str,
    tool_calls: list[dict] | None,
) -> None:
    """Various edge-case messages roundtrip correctly."""
    await store.save_message("edge", "cases", role, content, tool_calls=tool_calls)

    msgs = await store.get_messages("edge", "cases")

    assert len(msgs) == 1
    assert msgs[0].role == role
    assert msgs[0].content == content
    assert msgs[0].tool_calls == tool_calls
