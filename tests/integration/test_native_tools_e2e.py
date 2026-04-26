"""End-to-end integration tests for native tool calling.

Tests that verify ThinRuntime correctly integrates with native tool calling
through the full runtime path (runtime.run -> react -> native adapter).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockNativeAdapter:
    """Mock LLM adapter that supports both call() and call_with_tools()."""

    def __init__(
        self,
        native_results: list[NativeToolCallResult],
        text_results: list[str] | None = None,
    ) -> None:
        self._native_results = list(native_results)
        self._text_results = list(text_results or [])
        self._native_count = 0
        self._text_count = 0

    async def call(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ) -> str:
        if self._text_count < len(self._text_results):
            resp = self._text_results[self._text_count]
            self._text_count += 1
            return resp
        return json.dumps({"type": "final", "final_message": "text fallback"})

    async def stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        **kwargs: Any,
    ):
        text = await self.call(messages, system_prompt, **kwargs)
        yield text

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> NativeToolCallResult:
        if self._native_count < len(self._native_results):
            result = self._native_results[self._native_count]
            self._native_count += 1
            return result
        return NativeToolCallResult(text="done", stop_reason="end_turn")


def _make_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="calculator",
            description="Calculate",
            parameters={"type": "object", "properties": {"expr": {"type": "string"}}},
        ),
    ]


async def _collect(
    runtime: ThinRuntime,
    text: str = "test",
    tools: list[ToolSpec] | None = None,
    mode_hint: str | None = None,
) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="Test system prompt",
        active_tools=tools or [],
        mode_hint=mode_hint,
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestThinRuntimeNativeToolsE2E:
    """End-to-end tests for native tool calling through ThinRuntime."""

    @pytest.mark.asyncio
    async def test_thin_runtime_native_tools_end_to_end(self) -> None:
        """Full pipeline: ThinRuntime(use_native_tools=True) + adapter => tool executed."""
        adapter = MockNativeAdapter(
            native_results=[
                NativeToolCallResult(
                    text="Calculating",
                    tool_calls=(
                        NativeToolCall(
                            id="tc1", name="calculator", args={"expr": "2+2"}
                        ),
                    ),
                    stop_reason="tool_use",
                ),
                NativeToolCallResult(
                    text="The answer is 4",
                    tool_calls=(),
                    stop_reason="end_turn",
                ),
            ],
        )

        async def calculator(expr: str) -> str:
            return "4"

        config = RuntimeConfig(
            runtime_name="thin",
            use_native_tools=True,
            max_iterations=10,
        )

        # We need to pass adapter through llm_call wrapper so the runtime can find it
        async def llm_call_wrapper(messages, system_prompt, **kwargs):
            return await adapter.call(messages, system_prompt, **kwargs)

        runtime = ThinRuntime(
            config=config,
            llm_call=llm_call_wrapper,
            local_tools={"calculator": calculator},
        )
        # Inject native adapter directly
        runtime._native_adapter = adapter

        events = await _collect(runtime, "calc 2+2", _make_tools(), mode_hint="react")

        tool_started = [e for e in events if e.type == "tool_call_started"]
        finals = [e for e in events if e.type == "final"]

        assert len(tool_started) >= 1
        assert len(finals) == 1

    @pytest.mark.asyncio
    async def test_thin_runtime_native_tools_backward_compat(self) -> None:
        """use_native_tools=False => behaves exactly like before (no regression)."""
        config = RuntimeConfig(
            runtime_name="thin",
            use_native_tools=False,
        )

        async def mock_llm(messages, system_prompt, **kwargs):
            return json.dumps({"type": "final", "final_message": "Hello from JSON"})

        runtime = ThinRuntime(config=config, llm_call=mock_llm)

        events = await _collect(runtime, "hello")

        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert finals[0].data["text"] == "Hello from JSON"

    def test_runtime_config_use_native_tools_field(self) -> None:
        """RuntimeConfig has use_native_tools field with default False."""
        config = RuntimeConfig(runtime_name="thin")
        assert config.use_native_tools is False

        config_enabled = RuntimeConfig(runtime_name="thin", use_native_tools=True)
        assert config_enabled.use_native_tools is True
