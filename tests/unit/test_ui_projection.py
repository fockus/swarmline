"""Unit tests for UI Event Projection (IDEA-023 Phase 8C).

Tests cover:
- UIBlock creation (4 types)
- UIMessage creation
- UIState creation, to_dict, from_dict (snapshot round-trip)
- ChatProjection: assistant_delta accumulates text
- ChatProjection: tool_call_started/finished adds blocks
- ChatProjection: error adds ErrorBlock
- ChatProjection: status updates UIState.status
- ChatProjection: final sets status="done"
- ChatProjection: multiple events build full conversation
- project_stream helper
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent
from swarmline.ui.projection import (
    ChatProjection,
    ErrorBlock,
    EventProjection,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    UIBlock,
    UIMessage,
    UIState,
    project_stream,
)


# -----------------------------------------------------------------------
# UIBlock creation
# -----------------------------------------------------------------------


class TestTextBlock:
    def test_create_text_block_with_content_returns_frozen_dataclass(self) -> None:
        block = TextBlock(text="Hello world")
        assert block.text == "Hello world"

    def test_text_block_is_frozen(self) -> None:
        block = TextBlock(text="x")
        with pytest.raises(AttributeError):
            block.text = "y"  # type: ignore[misc]


class TestToolCallBlock:
    def test_create_tool_call_block_with_args_returns_all_fields(self) -> None:
        block = ToolCallBlock(name="search", args={"q": "test"}, correlation_id="abc")
        assert block.name == "search"
        assert block.args == {"q": "test"}
        assert block.correlation_id == "abc"


class TestToolResultBlock:
    def test_create_tool_result_block_with_ok_true_returns_success(self) -> None:
        block = ToolResultBlock(
            name="search", ok=True, summary="Found 3 results", correlation_id="abc"
        )
        assert block.name == "search"
        assert block.ok is True
        assert block.summary == "Found 3 results"
        assert block.correlation_id == "abc"


class TestErrorBlock:
    def test_create_error_block_with_kind_and_message(self) -> None:
        block = ErrorBlock(kind="runtime_crash", message="boom")
        assert block.kind == "runtime_crash"
        assert block.message == "boom"


# -----------------------------------------------------------------------
# UIMessage
# -----------------------------------------------------------------------


class TestUIMessage:
    def test_create_message_with_blocks_and_role(self) -> None:
        blocks: list[UIBlock] = [TextBlock(text="hi")]
        msg = UIMessage(role="assistant", blocks=blocks, timestamp=1000.0)
        assert msg.role == "assistant"
        assert len(msg.blocks) == 1
        assert msg.timestamp == 1000.0

    def test_create_message_without_timestamp_defaults_none(self) -> None:
        msg = UIMessage(role="user", blocks=[])
        assert msg.timestamp is None


# -----------------------------------------------------------------------
# UIState
# -----------------------------------------------------------------------


class TestUIState:
    def test_create_empty_state_has_idle_status(self) -> None:
        state = UIState(messages=[])
        assert state.status == "idle"
        assert state.messages == []
        assert state.metadata == {}

    def test_to_dict_returns_serializable_dict(self) -> None:
        state = UIState(
            messages=[
                UIMessage(
                    role="assistant",
                    blocks=[TextBlock(text="hello")],
                    timestamp=100.0,
                )
            ],
            status="streaming",
            metadata={"model": "sonnet"},
        )
        d = state.to_dict()
        assert d["status"] == "streaming"
        assert len(d["messages"]) == 1
        assert d["messages"][0]["role"] == "assistant"
        assert d["messages"][0]["blocks"][0] == {"type": "text", "text": "hello"}
        assert d["metadata"] == {"model": "sonnet"}

    def test_from_dict_round_trip_preserves_state(self) -> None:
        state = UIState(
            messages=[
                UIMessage(
                    role="assistant",
                    blocks=[
                        TextBlock(text="hi"),
                        ToolCallBlock(
                            name="search", args={"q": "x"}, correlation_id="c1"
                        ),
                        ToolResultBlock(
                            name="search",
                            ok=True,
                            summary="ok",
                            correlation_id="c1",
                        ),
                        ErrorBlock(kind="runtime_crash", message="oops"),
                    ],
                    timestamp=42.0,
                )
            ],
            status="done",
            metadata={"k": "v"},
        )
        d = state.to_dict()
        restored = UIState.from_dict(d)
        assert restored.to_dict() == d


# -----------------------------------------------------------------------
# ChatProjection: event handling
# -----------------------------------------------------------------------


class TestChatProjection:
    def test_assistant_delta_accumulates_text_in_last_block(self) -> None:
        proj = ChatProjection()
        proj.apply(RuntimeEvent.assistant_delta("Hello"))
        proj.apply(RuntimeEvent.assistant_delta(" world"))
        state = proj.state
        assert len(state.messages) == 1
        assert state.messages[0].role == "assistant"
        blocks = state.messages[0].blocks
        assert len(blocks) == 1
        assert isinstance(blocks[0], TextBlock)
        assert blocks[0].text == "Hello world"

    def test_tool_call_started_adds_tool_call_block(self) -> None:
        proj = ChatProjection()
        proj.apply(
            RuntimeEvent.tool_call_started(
                name="web_search", args={"q": "test"}, correlation_id="t1"
            )
        )
        state = proj.state
        assert len(state.messages) == 1
        blocks = state.messages[0].blocks
        assert len(blocks) == 1
        assert isinstance(blocks[0], ToolCallBlock)
        assert blocks[0].name == "web_search"
        assert blocks[0].correlation_id == "t1"

    def test_tool_call_finished_adds_tool_result_block(self) -> None:
        proj = ChatProjection()
        proj.apply(
            RuntimeEvent.tool_call_started(name="calc", args={}, correlation_id="t2")
        )
        proj.apply(
            RuntimeEvent.tool_call_finished(
                name="calc", correlation_id="t2", ok=True, result_summary="42"
            )
        )
        state = proj.state
        blocks = state.messages[0].blocks
        assert len(blocks) == 2
        result_block = blocks[1]
        assert isinstance(result_block, ToolResultBlock)
        assert result_block.ok is True
        assert result_block.summary == "42"
        assert result_block.correlation_id == "t2"

    def test_error_event_adds_error_block(self) -> None:
        proj = ChatProjection()
        err = RuntimeErrorData(kind="runtime_crash", message="fail")
        proj.apply(RuntimeEvent.error(err))
        state = proj.state
        assert len(state.messages) == 1
        blocks = state.messages[0].blocks
        assert len(blocks) == 1
        assert isinstance(blocks[0], ErrorBlock)
        assert blocks[0].kind == "runtime_crash"
        assert blocks[0].message == "fail"

    def test_status_event_updates_ui_state_status(self) -> None:
        proj = ChatProjection()
        proj.apply(RuntimeEvent.status("Thinking..."))
        assert proj.state.status == "Thinking..."

    def test_final_event_sets_status_done_and_metadata(self) -> None:
        proj = ChatProjection()
        proj.apply(RuntimeEvent.assistant_delta("Answer"))
        proj.apply(
            RuntimeEvent.final(
                text="Answer",
                session_id="s1",
                total_cost_usd=0.01,
            )
        )
        state = proj.state
        assert state.status == "done"
        assert state.metadata.get("session_id") == "s1"
        assert state.metadata.get("total_cost_usd") == 0.01

    def test_multiple_events_build_full_conversation(self) -> None:
        """Simulate a realistic event sequence and verify final state."""
        proj = ChatProjection()

        # Text streaming
        proj.apply(RuntimeEvent.assistant_delta("Let me "))
        proj.apply(RuntimeEvent.assistant_delta("search."))

        # Tool call
        proj.apply(
            RuntimeEvent.tool_call_started(
                name="web", args={"q": "AI"}, correlation_id="c1"
            )
        )
        proj.apply(
            RuntimeEvent.tool_call_finished(
                name="web", correlation_id="c1", ok=True, result_summary="result"
            )
        )

        # More text
        proj.apply(RuntimeEvent.assistant_delta("Done."))

        # Final
        proj.apply(RuntimeEvent.final(text="Let me search.Done."))

        state = proj.state
        assert state.status == "done"
        # Should have assistant message(s) with text and tool blocks
        all_blocks = []
        for msg in state.messages:
            all_blocks.extend(msg.blocks)
        text_blocks = [b for b in all_blocks if isinstance(b, TextBlock)]
        tool_call_blocks = [b for b in all_blocks if isinstance(b, ToolCallBlock)]
        tool_result_blocks = [b for b in all_blocks if isinstance(b, ToolResultBlock)]
        assert len(text_blocks) >= 1
        assert len(tool_call_blocks) == 1
        assert len(tool_result_blocks) == 1


# -----------------------------------------------------------------------
# EventProjection Protocol conformance
# -----------------------------------------------------------------------


class TestEventProjectionProtocol:
    def test_chat_projection_implements_event_projection_protocol(self) -> None:
        proj = ChatProjection()
        assert isinstance(proj, EventProjection)


# -----------------------------------------------------------------------
# project_stream helper
# -----------------------------------------------------------------------


class TestProjectStream:
    async def test_project_stream_yields_state_for_each_event(self) -> None:
        events = [
            RuntimeEvent.assistant_delta("Hi"),
            RuntimeEvent.assistant_delta(" there"),
            RuntimeEvent.final(text="Hi there"),
        ]

        async def event_iter() -> AsyncIterator[RuntimeEvent]:
            for e in events:
                yield e

        proj = ChatProjection()
        states: list[UIState] = []
        async for state in project_stream(event_iter(), proj):
            states.append(state)

        assert len(states) == 3
        # Final accumulated state: text="Hi there", status="done"
        final_state = states[-1]
        final_blocks = final_state.messages[0].blocks
        assert isinstance(final_blocks[0], TextBlock)
        assert final_blocks[0].text == "Hi there"
        assert final_state.status == "done"
