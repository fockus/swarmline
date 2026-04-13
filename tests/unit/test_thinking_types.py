"""Unit tests: Thinking Events — domain types, config, adapter.

Phase 15 — ThinkingConfig, RuntimeEvent.thinking_delta, LlmCallResult,
BufferedLlmAttempt.thinking, RuntimeEventAdapter thinking_delta handling.
"""

from __future__ import annotations

import dataclasses

import pytest

from swarmline.agent.runtime_dispatch import RuntimeEventAdapter
from swarmline.domain_types import RUNTIME_EVENT_TYPES, RuntimeEvent, ThinkingConfig
from swarmline.runtime.thin.llm_client import BufferedLlmAttempt, LlmCallResult
from swarmline.runtime.types import RuntimeConfig

# ---------------------------------------------------------------------------
# ThinkingConfig
# ---------------------------------------------------------------------------


class TestThinkingConfig:
    """ThinkingConfig frozen dataclass with budget_tokens."""

    def test_default_budget_tokens(self) -> None:
        cfg = ThinkingConfig()
        assert cfg.budget_tokens == 10_000

    def test_custom_budget_tokens(self) -> None:
        cfg = ThinkingConfig(budget_tokens=5_000)
        assert cfg.budget_tokens == 5_000

    def test_frozen(self) -> None:
        cfg = ThinkingConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.budget_tokens = 999  # type: ignore[misc]

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(ThinkingConfig)


# ---------------------------------------------------------------------------
# RuntimeEvent.thinking_delta
# ---------------------------------------------------------------------------


class TestRuntimeEventThinkingDelta:
    """RuntimeEvent.thinking_delta static factory."""

    def test_type_is_thinking_delta(self) -> None:
        event = RuntimeEvent.thinking_delta("reasoning step")
        assert event.type == "thinking_delta"

    def test_data_has_text(self) -> None:
        event = RuntimeEvent.thinking_delta("reasoning step")
        assert event.data == {"text": "reasoning step"}

    def test_text_accessor(self) -> None:
        event = RuntimeEvent.thinking_delta("some thought")
        assert event.text == "some thought"

    def test_empty_text(self) -> None:
        event = RuntimeEvent.thinking_delta("")
        assert event.data == {"text": ""}

    def test_thinking_delta_in_event_types(self) -> None:
        assert "thinking_delta" in RUNTIME_EVENT_TYPES


# ---------------------------------------------------------------------------
# RuntimeConfig.thinking
# ---------------------------------------------------------------------------


class TestRuntimeConfigThinking:
    """RuntimeConfig.thinking optional field."""

    def test_default_is_none(self) -> None:
        cfg = RuntimeConfig(runtime_name="thin")
        assert cfg.thinking is None

    def test_accepts_thinking_config(self) -> None:
        tc = ThinkingConfig(budget_tokens=8_000)
        cfg = RuntimeConfig(runtime_name="thin", thinking=tc)
        assert cfg.thinking is tc
        assert cfg.thinking.budget_tokens == 8_000

    def test_backward_compat_without_thinking(self) -> None:
        cfg = RuntimeConfig(runtime_name="thin")
        assert cfg.thinking is None
        assert cfg.max_iterations == 6  # existing default preserved


# ---------------------------------------------------------------------------
# LlmCallResult
# ---------------------------------------------------------------------------


class TestLlmCallResult:
    """LlmCallResult frozen dataclass."""

    def test_text_only(self) -> None:
        result = LlmCallResult(text="hello")
        assert result.text == "hello"
        assert result.thinking is None

    def test_with_thinking(self) -> None:
        result = LlmCallResult(text="answer", thinking="reasoning")
        assert result.text == "answer"
        assert result.thinking == "reasoning"

    def test_frozen(self) -> None:
        result = LlmCallResult(text="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.text = "y"  # type: ignore[misc]

    def test_is_dataclass(self) -> None:
        assert dataclasses.is_dataclass(LlmCallResult)


# ---------------------------------------------------------------------------
# BufferedLlmAttempt.thinking
# ---------------------------------------------------------------------------


class TestBufferedLlmAttemptThinking:
    """BufferedLlmAttempt with optional thinking field."""

    def test_default_thinking_is_none(self) -> None:
        attempt = BufferedLlmAttempt(raw="text", chunks=[], used_stream=False)
        assert attempt.thinking is None

    def test_with_thinking(self) -> None:
        attempt = BufferedLlmAttempt(
            raw="answer", chunks=["answer"], used_stream=True, thinking="thought"
        )
        assert attempt.thinking == "thought"
        assert attempt.raw == "answer"

    def test_backward_compat_without_thinking(self) -> None:
        attempt = BufferedLlmAttempt(raw="a", chunks=["a"], used_stream=True)
        assert attempt.raw == "a"
        assert attempt.thinking is None


# ---------------------------------------------------------------------------
# RuntimeEventAdapter — thinking_delta
# ---------------------------------------------------------------------------


class TestRuntimeEventAdapterThinkingDelta:
    """RuntimeEventAdapter handles thinking_delta events."""

    def test_thinking_delta_type_mapping(self) -> None:
        event = RuntimeEvent.thinking_delta("step 1")
        adapted = RuntimeEventAdapter(event)
        assert adapted.type == "thinking_delta"

    def test_thinking_delta_text(self) -> None:
        event = RuntimeEvent.thinking_delta("reasoning text")
        adapted = RuntimeEventAdapter(event)
        assert adapted.text == "reasoning text"

    def test_thinking_delta_not_final(self) -> None:
        event = RuntimeEvent.thinking_delta("step")
        adapted = RuntimeEventAdapter(event)
        assert adapted.is_final is False
