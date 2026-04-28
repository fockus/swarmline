"""Integration tests for InputFilter with ThinRuntime."""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.input_filters import MaxTokensFilter, SystemPromptInjector
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent

pytestmark = pytest.mark.integration


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)


def _make_llm_call(capture: dict[str, Any]):
    """Create a fake llm_call that captures what it receives and returns valid JSON."""

    async def llm_call(
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        capture["messages"] = messages
        capture["system_prompt"] = system_prompt
        return '{"type": "final", "final_message": "ok"}'

    return llm_call


async def _collect_events(runtime: ThinRuntime, **kwargs: Any) -> list[RuntimeEvent]:
    events = []
    async for event in runtime.run(**kwargs):
        events.append(event)
    return events


class TestThinRuntimeWithMaxTokensFilter:
    @pytest.mark.asyncio
    async def test_messages_trimmed_before_llm_call(self) -> None:
        """MaxTokensFilter trims messages before they reach the LLM."""
        captured: dict[str, Any] = {}
        # 3 messages, each ~100 tokens. Budget = 60 tokens.
        msgs = [
            _msg("user", "a" * 400),
            _msg("assistant", "b" * 400),
            _msg("user", "c" * 400),
        ]
        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[MaxTokensFilter(max_tokens=120, chars_per_token=4.0)],
        )
        runtime = ThinRuntime(
            config=config,
            llm_call=_make_llm_call(captured),
        )
        events = await _collect_events(
            runtime,
            messages=msgs,
            system_prompt="sys",
            active_tools=[],
        )
        # LLM should have received fewer messages than original
        assert len(captured["messages"]) < len(msgs)
        # Should have a final event
        assert any(e.is_final for e in events)


class TestThinRuntimeWithSystemPromptInjector:
    @pytest.mark.asyncio
    async def test_system_prompt_modified_before_llm_call(self) -> None:
        """SystemPromptInjector modifies system_prompt before LLM call."""
        captured: dict[str, Any] = {}
        config = RuntimeConfig(
            runtime_name="thin",
            input_filters=[SystemPromptInjector(extra_text="INJECTED_TEXT")],
        )
        runtime = ThinRuntime(
            config=config,
            llm_call=_make_llm_call(captured),
        )
        events = await _collect_events(
            runtime,
            messages=[_msg("user", "hello")],
            system_prompt="base prompt",
            active_tools=[],
        )
        assert "INJECTED_TEXT" in captured["system_prompt"]
        assert any(e.is_final for e in events)


class TestThinRuntimeWithoutFilters:
    @pytest.mark.asyncio
    async def test_backward_compat_no_filters(self) -> None:
        """Without filters, ThinRuntime works normally."""
        captured: dict[str, Any] = {}
        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(
            config=config,
            llm_call=_make_llm_call(captured),
        )
        msgs = [_msg("user", "hello")]
        events = await _collect_events(
            runtime,
            messages=msgs,
            system_prompt="sys",
            active_tools=[],
        )
        # Messages passed through unmodified
        assert len(captured["messages"]) == 1
        # Strategy wraps system_prompt, but original text is preserved
        assert captured["system_prompt"].startswith("sys")
        assert any(e.is_final for e in events)
