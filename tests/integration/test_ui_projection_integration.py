"""Integration tests for UI Event Projection (IDEA-023 Phase 8C).

Tests cover:
- ChatProjection with realistic ThinRuntime event sequence
- project_stream with simulated event stream
- Snapshot round-trip: to_dict -> from_dict preserves full state
- Full conversation replay from serialized events
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent, TurnMetrics
from swarmline.ui.projection import (
    ChatProjection,
    ToolCallBlock,
    ToolResultBlock,
    UIState,
    project_stream,
)


def _build_thin_runtime_event_sequence() -> list[RuntimeEvent]:
    """Build a realistic sequence of events mimicking ThinRuntime."""
    return [
        RuntimeEvent.status("Thinking..."),
        RuntimeEvent.assistant_delta("I'll help you "),
        RuntimeEvent.assistant_delta("with that."),
        RuntimeEvent.tool_call_started(
            name="web_search", args={"query": "python async"}, correlation_id="tc-001"
        ),
        RuntimeEvent.status("Running web_search..."),
        RuntimeEvent.tool_call_finished(
            name="web_search",
            correlation_id="tc-001",
            ok=True,
            result_summary="Found 5 results about Python async",
        ),
        RuntimeEvent.assistant_delta(" Here are the results."),
        RuntimeEvent.tool_call_started(
            name="read_file",
            args={"path": "/tmp/test.py"},
            correlation_id="tc-002",
        ),
        RuntimeEvent.tool_call_finished(
            name="read_file",
            correlation_id="tc-002",
            ok=False,
            result_summary="File not found",
        ),
        RuntimeEvent.assistant_delta(" Sorry, couldn't read that file."),
        RuntimeEvent.final(
            text="I'll help you with that. Here are the results. Sorry, couldn't read that file.",
            metrics=TurnMetrics(
                latency_ms=1200,
                iterations=3,
                tool_calls_count=2,
                tokens_in=500,
                tokens_out=150,
                model="claude-sonnet-4-20250514",
            ),
            session_id="sess-123",
            total_cost_usd=0.005,
        ),
    ]


class TestChatProjectionWithThinRuntimeSequence:
    def test_full_thin_runtime_sequence_builds_correct_state(self) -> None:
        """Process a complete ThinRuntime event sequence and verify final UI state."""
        proj = ChatProjection()
        events = _build_thin_runtime_event_sequence()

        for event in events:
            proj.apply(event)

        state = proj.state
        assert state.status == "done"
        assert state.metadata.get("session_id") == "sess-123"

        # Collect all blocks across messages
        all_blocks = []
        for msg in state.messages:
            all_blocks.extend(msg.blocks)

        # Verify block types present
        tool_call_blocks = [b for b in all_blocks if isinstance(b, ToolCallBlock)]
        tool_result_blocks = [b for b in all_blocks if isinstance(b, ToolResultBlock)]

        assert len(tool_call_blocks) == 2
        assert len(tool_result_blocks) == 2

        # Verify tool result success/failure
        ok_results = [b for b in tool_result_blocks if b.ok]
        fail_results = [b for b in tool_result_blocks if not b.ok]
        assert len(ok_results) == 1
        assert len(fail_results) == 1

        # Verify correlation IDs match
        assert tool_call_blocks[0].correlation_id == "tc-001"
        assert tool_result_blocks[0].correlation_id == "tc-001"
        assert tool_call_blocks[1].correlation_id == "tc-002"
        assert tool_result_blocks[1].correlation_id == "tc-002"


class TestProjectStreamIntegration:
    async def test_project_stream_with_simulated_event_stream(self) -> None:
        """Verify project_stream processes async event stream correctly."""
        events = _build_thin_runtime_event_sequence()

        async def make_iter() -> AsyncIterator[RuntimeEvent]:
            for e in events:
                yield e

        # Capture status progression by snapshotting via to_dict at each step
        proj = ChatProjection()
        snapshots: list[dict[str, Any]] = []

        async for state in project_stream(make_iter(), proj):
            snapshots.append(state.to_dict())

        assert len(snapshots) == len(events)
        assert snapshots[0]["status"] == "Thinking..."
        assert snapshots[-1]["status"] == "done"

        # Each snapshot should be independently deserializable
        for snap in snapshots:
            assert isinstance(snap, dict)
            assert "messages" in snap


class TestSnapshotRoundTrip:
    def test_complex_state_survives_to_dict_from_dict_round_trip(self) -> None:
        """Build a complex state and verify serialization round-trip."""
        proj = ChatProjection()
        events = _build_thin_runtime_event_sequence()
        for event in events:
            proj.apply(event)

        original = proj.state
        serialized = original.to_dict()
        restored = UIState.from_dict(serialized)
        reserialized = restored.to_dict()

        assert serialized == reserialized

    def test_error_block_survives_round_trip(self) -> None:
        """Verify error blocks serialize/deserialize correctly."""
        proj = ChatProjection()
        proj.apply(RuntimeEvent.assistant_delta("Before error"))
        proj.apply(
            RuntimeEvent.error(
                RuntimeErrorData(kind="budget_exceeded", message="Max tokens reached")
            )
        )
        proj.apply(RuntimeEvent.final(text="Before error"))

        original = proj.state
        restored = UIState.from_dict(original.to_dict())
        assert restored.to_dict() == original.to_dict()


class TestFullConversationReplay:
    def test_replaying_events_produces_same_state(self) -> None:
        """Two independent projections processing same events produce identical state."""
        events = _build_thin_runtime_event_sequence()

        proj1 = ChatProjection()
        proj2 = ChatProjection()

        for event in events:
            proj1.apply(event)

        for event in events:
            proj2.apply(event)

        d1 = proj1.state.to_dict()
        d2 = proj2.state.to_dict()
        # Strip timestamps (differ due to time.time() calls)
        for msg in d1["messages"]:
            msg.pop("timestamp", None)
        for msg in d2["messages"]:
            msg.pop("timestamp", None)
        assert d1 == d2

    def test_empty_conversation_produces_empty_state(self) -> None:
        """No events -> empty state."""
        proj = ChatProjection()
        state = proj.state
        assert state.messages == []
        assert state.status == "idle"
        assert state.metadata == {}
