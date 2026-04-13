"""Integration tests: Thinking Events end-to-end (Phase 15).

Tests thinking event flow through the pipeline:
- Thinking events in conversational strategy stream
- Non-Anthropic warning via ThinRuntime
- Compaction preserves non_compactable messages
- RuntimeConfig.thinking propagation
- Event ordering (thinking_delta before assistant_delta/final)
- Backward compat (no thinking config = no thinking events)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.domain_types import Message, RuntimeEvent, ThinkingConfig
from swarmline.runtime.thin.llm_client import LlmCallResult
from swarmline.runtime.types import RuntimeConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content: str, metadata: dict | None = None) -> Message:
    return Message(role=role, content=content, metadata=metadata)


def _envelope(final_message: str) -> str:
    return json.dumps({"type": "final", "final_message": final_message})


# ---------------------------------------------------------------------------
# Thinking events in conversational strategy (mock adapter)
# ---------------------------------------------------------------------------


class TestThinkingEventsConversationalIntegration:
    """End-to-end: conversational strategy emits thinking_delta for Anthropic."""

    @pytest.mark.asyncio
    async def test_thinking_delta_emitted_for_anthropic(self) -> None:
        """Full pipeline: thinking config → buffered call → thinking_delta event."""
        from swarmline.runtime.thin.conversational import run_conversational

        llm_result = LlmCallResult(
            text=_envelope("The answer."),
            thinking="Step 1: analyze. Step 2: conclude.",
        )
        mock_llm = AsyncMock(return_value=llm_result)

        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            thinking=ThinkingConfig(budget_tokens=8_000),
        )

        events: list[RuntimeEvent] = []
        async for event in run_conversational(mock_llm, [], "sys", config, 0.0):
            events.append(event)

        thinking = [e for e in events if e.type == "thinking_delta"]
        assert len(thinking) == 1
        assert thinking[0].text == "Step 1: analyze. Step 2: conclude."

    @pytest.mark.asyncio
    async def test_thinking_delta_before_final_in_stream(self) -> None:
        """thinking_delta must appear before final event in event stream."""
        from swarmline.runtime.thin.conversational import run_conversational

        llm_result = LlmCallResult(
            text=_envelope("Result."),
            thinking="Reasoning here.",
        )
        mock_llm = AsyncMock(return_value=llm_result)

        config = RuntimeConfig(
            runtime_name="thin",
            model="claude-sonnet-4-20250514",
            thinking=ThinkingConfig(budget_tokens=5_000),
        )

        types: list[str] = []
        async for event in run_conversational(mock_llm, [], "sys", config, 0.0):
            types.append(event.type)

        assert "thinking_delta" in types
        assert "final" in types
        thinking_idx = types.index("thinking_delta")
        final_idx = types.index("final")
        assert thinking_idx < final_idx


# ---------------------------------------------------------------------------
# Non-Anthropic warning via ThinRuntime
# ---------------------------------------------------------------------------


class TestNonAnthropicWarningIntegration:
    """ThinRuntime emits status warning for thinking + non-Anthropic model."""

    @pytest.mark.asyncio
    async def test_non_anthropic_warning_emitted(self) -> None:
        from swarmline.runtime.thin.runtime import ThinRuntime

        async def mock_llm(*args, **kwargs):
            return _envelope("Answer.")

        config = RuntimeConfig(
            runtime_name="thin",
            model="openai:gpt-4o",
            thinking=ThinkingConfig(budget_tokens=5_000),
        )
        rt = ThinRuntime(config=config, llm_call=mock_llm)

        events: list[RuntimeEvent] = []
        async for event in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        warnings = [
            e for e in events
            if e.type == "status" and "thinking" in e.text.lower()
        ]
        assert len(warnings) >= 1
        assert "anthropic" in warnings[0].text.lower()


# ---------------------------------------------------------------------------
# Backward compat — no thinking config = no thinking events
# ---------------------------------------------------------------------------


class TestBackwardCompatIntegration:
    """Without thinking config, no thinking_delta events emitted."""

    @pytest.mark.asyncio
    async def test_no_thinking_config_no_events(self) -> None:
        from swarmline.runtime.thin.conversational import run_conversational

        mock_llm = AsyncMock(return_value=_envelope("Simple."))
        config = RuntimeConfig(runtime_name="thin", model="claude-sonnet-4-20250514")

        events: list[RuntimeEvent] = []
        async for event in run_conversational(mock_llm, [], "sys", config, 0.0):
            events.append(event)

        thinking = [e for e in events if e.type == "thinking_delta"]
        assert len(thinking) == 0

    @pytest.mark.asyncio
    async def test_no_thinking_config_no_warning(self) -> None:
        from swarmline.runtime.thin.runtime import ThinRuntime

        async def mock_llm(*args, **kwargs):
            return _envelope("Answer.")

        config = RuntimeConfig(runtime_name="thin", model="openai:gpt-4o")
        rt = ThinRuntime(config=config, llm_call=mock_llm)

        events: list[RuntimeEvent] = []
        async for event in rt.run(
            messages=[Message(role="user", content="hi")],
            system_prompt="test",
            active_tools=[],
        ):
            events.append(event)

        warnings = [
            e for e in events
            if e.type == "status" and "thinking" in e.text.lower()
        ]
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# RuntimeConfig.thinking propagation
# ---------------------------------------------------------------------------


class TestRuntimeConfigThinkingPropagation:
    """RuntimeConfig.thinking propagates through the pipeline."""

    def test_thinking_config_accessible(self) -> None:
        tc = ThinkingConfig(budget_tokens=12_000)
        config = RuntimeConfig(runtime_name="thin", thinking=tc)
        assert config.thinking is tc
        assert config.thinking.budget_tokens == 12_000

    def test_thinking_config_default_none(self) -> None:
        config = RuntimeConfig(runtime_name="thin")
        assert config.thinking is None

    def test_thinking_triggers_buffered_postprocessing(self) -> None:
        from swarmline.runtime.thin.helpers import _should_buffer_postprocessing

        config_with = RuntimeConfig(
            runtime_name="thin",
            thinking=ThinkingConfig(budget_tokens=5_000),
        )
        config_without = RuntimeConfig(runtime_name="thin")

        assert _should_buffer_postprocessing(config_with) is True
        assert _should_buffer_postprocessing(config_without) is False


# ---------------------------------------------------------------------------
# Compaction preserves non_compactable messages
# ---------------------------------------------------------------------------


class TestCompactionNonCompactableIntegration:
    """End-to-end: compaction preserves non_compactable thinking messages."""

    @pytest.mark.asyncio
    async def test_compaction_preserves_thinking_messages(self) -> None:
        """Non-compactable thinking messages survive full compaction pipeline."""
        msgs: list[Message] = []
        # Old messages that should be compacted
        for i in range(5):
            msgs.append(_msg("user", f"question {i} " * 100))
            msgs.append(_msg("assistant", f"answer {i} " * 100))

        # A thinking message that must survive
        msgs.append(_msg(
            "assistant",
            "Important reasoning that must be preserved",
            metadata={"non_compactable": True},
        ))

        # More old messages
        for i in range(3):
            msgs.append(_msg("user", f"followup {i} " * 100))
            msgs.append(_msg("assistant", f"reply {i} " * 100))

        msgs.append(_msg("user", "final question"))

        async def mock_llm(prompt: str, text: str) -> str:
            return "Summary of old conversation."

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(
                threshold_tokens=200,
                preserve_recent_pairs=1,
            ),
            llm_call=mock_llm,
        )
        result_msgs, _ = await compaction.filter(msgs, "system")

        # Result should be shorter
        assert len(result_msgs) < len(msgs)
        # Last message preserved
        assert result_msgs[-1].content == "final question"
        # Non-compactable message must survive
        nc = [m for m in result_msgs if m.metadata and m.metadata.get("non_compactable")]
        assert len(nc) == 1
        assert nc[0].content == "Important reasoning that must be preserved"

    @pytest.mark.asyncio
    async def test_compaction_truncation_keeps_thinking(self) -> None:
        """Tier 3 emergency truncation preserves non_compactable messages."""
        msgs = [
            _msg("user", "old " * 200),
            _msg("assistant", "thinking chain", metadata={"non_compactable": True}),
            _msg("assistant", "old " * 200),
            _msg("user", "old " * 200),
            _msg("user", "final"),
        ]

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(
                threshold_tokens=30,
                tier_1_enabled=False,
                tier_2_enabled=False,
            ),
        )
        result_msgs, _ = await compaction.filter(msgs, "sys")

        # non_compactable survives
        nc = [m for m in result_msgs if m.metadata and m.metadata.get("non_compactable")]
        assert len(nc) == 1
        assert nc[0].content == "thinking chain"
        # last message survives
        assert result_msgs[-1].content == "final"
        # normal old messages dropped
        assert len(result_msgs) < len(msgs)

    @pytest.mark.asyncio
    async def test_compaction_without_non_compactable_backward_compat(self) -> None:
        """Without non_compactable messages, compaction behaves as before."""
        msgs = [
            _msg("user", "msg " * 200),
            _msg("assistant", "reply " * 200),
            _msg("user", "last"),
        ]

        compaction = ConversationCompactionFilter(
            config=CompactionConfig(
                threshold_tokens=30,
                tier_1_enabled=False,
                tier_2_enabled=False,
            ),
        )
        result_msgs, _ = await compaction.filter(msgs, "sys")
        assert result_msgs[-1].content == "last"
        assert len(result_msgs) < len(msgs)
