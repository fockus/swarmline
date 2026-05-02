"""Tests for native tool calling integration with react strategy.

Tests that use_native_tools=True routes through native adapter,
use_native_tools=False uses JSON-in-text, and fallback works.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.react_strategy import run_react
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeEvent,
    ToolSpec,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_SAFE_CALC = {"2+2": "4", "3+3": "6", "5+5": "10"}


class MockNativeAdapter:
    """Mock adapter supporting native tool calling."""

    def __init__(self, results: list[NativeToolCallResult]) -> None:
        self._results = list(results)
        self._call_count = 0
        self.call_log: list[dict[str, Any]] = []

    async def call_with_tools(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> NativeToolCallResult:
        self.call_log.append(
            {
                "messages": messages,
                "system_prompt": system_prompt,
                "tools": tools,
            }
        )
        if self._call_count < len(self._results):
            result = self._results[self._call_count]
            self._call_count += 1
            return result
        return NativeToolCallResult(text="done", stop_reason="end_turn")


class MockLLM:
    """Mock LLM that returns predefined JSON responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def __call__(
        self, messages: list[dict], system_prompt: str, **kwargs: Any
    ) -> str:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return json.dumps({"type": "final", "final_message": "fallback"})


class ErrorNativeAdapter:
    """Mock adapter that raises an error on call_with_tools."""

    def __init__(self, message: str = "Native API unavailable") -> None:
        self._message = message

    async def call_with_tools(self, *args: Any, **kwargs: Any) -> NativeToolCallResult:
        raise RuntimeError(self._message)


def _make_config(use_native_tools: bool = False) -> RuntimeConfig:
    return RuntimeConfig(
        runtime_name="thin",
        use_native_tools=use_native_tools,
        max_iterations=10,
        max_tool_calls=10,
    )


def _make_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="calculator",
            description="Calculate",
            parameters={"type": "object", "properties": {"expr": {"type": "string"}}},
        ),
    ]


def _make_messages(text: str = "calc 2+2") -> list[Message]:
    return [Message(role="user", content=text)]


def _make_executor() -> ToolExecutor:
    """Create a ToolExecutor with a safe calculator tool."""

    async def calculator(expr: str) -> str:
        return _SAFE_CALC.get(expr, "unknown")

    return ToolExecutor(local_tools={"calculator": calculator})


async def _collect_events(strategy) -> list[RuntimeEvent]:
    events = []
    async for ev in strategy:
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNativeToolsReactIntegration:
    """Integration tests for native tool calling in react strategy."""

    @pytest.mark.asyncio
    async def test_native_tools_enabled_executes_tool(self) -> None:
        """use_native_tools=True + mock adapter => tool executed via native path."""
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="Let me calculate",
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
            ]
        )

        config = _make_config(use_native_tools=True)
        executor = _make_executor()
        tools = _make_tools()

        # LLM call should NOT be called when native adapter handles everything
        llm_call = MockLLM([])

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=adapter,
        )
        events = await _collect_events(strategy)

        # Verify tool call events were emitted
        tool_started = [e for e in events if e.type == "tool_call_started"]
        tool_finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(tool_started) == 1
        assert tool_started[0].data["name"] == "calculator"
        assert len(tool_finished) == 1
        assert tool_finished[0].data["name"] == "calculator"

        # Verify final event
        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert "4" in finals[0].data.get("text", "")

    @pytest.mark.asyncio
    async def test_native_tools_disabled_uses_json_in_text(self) -> None:
        """use_native_tools=False => JSON-in-text path regardless of adapter."""
        adapter = MockNativeAdapter([])  # Should NOT be called

        config = _make_config(use_native_tools=False)
        executor = _make_executor()
        tools = _make_tools()

        llm_call = MockLLM(
            [
                json.dumps(
                    {"type": "final", "final_message": "Hello from JSON-in-text"}
                ),
            ]
        )

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages("hello"),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=adapter,
        )
        events = await _collect_events(strategy)

        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert finals[0].data["text"] == "Hello from JSON-in-text"

        # Adapter should NOT have been called
        assert len(adapter.call_log) == 0

    @pytest.mark.asyncio
    async def test_native_tools_parallel_execution(self) -> None:
        """Multiple tool calls in single response => all executed (parallel)."""
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="",
                    tool_calls=(
                        NativeToolCall(
                            id="tc1", name="calculator", args={"expr": "2+2"}
                        ),
                        NativeToolCall(
                            id="tc2", name="calculator", args={"expr": "3+3"}
                        ),
                    ),
                    stop_reason="tool_use",
                ),
                NativeToolCallResult(
                    text="Results: 4 and 6",
                    tool_calls=(),
                    stop_reason="end_turn",
                ),
            ]
        )

        config = _make_config(use_native_tools=True)
        executor = _make_executor()
        tools = _make_tools()
        llm_call = MockLLM([])

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=adapter,
        )
        events = await _collect_events(strategy)

        tool_started = [e for e in events if e.type == "tool_call_started"]
        tool_finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(tool_started) == 2
        assert len(tool_finished) == 2

    @pytest.mark.asyncio
    async def test_native_tool_started_event_precedes_execution(self) -> None:
        """Tracing sees tool start before the native tool body runs."""
        order: list[str] = []
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="",
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
            ]
        )

        async def calculator(expr: str) -> str:
            order.append("executed")
            return _SAFE_CALC[expr]

        config = _make_config(use_native_tools=True)
        executor = ToolExecutor(local_tools={"calculator": calculator})
        llm_call = MockLLM([])

        import time

        async for event in run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            _make_tools(),
            config,
            time.monotonic(),
            native_adapter=adapter,
        ):
            if event.type == "tool_call_started":
                order.append("started")
            elif event.type == "tool_call_finished":
                order.append("finished")

        assert order[:3] == ["started", "executed", "finished"]

    @pytest.mark.asyncio
    async def test_native_parallel_starts_all_tools_before_execution(self) -> None:
        """Parallel native calls emit all start events before any tool finishes."""
        order: list[str] = []
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="",
                    tool_calls=(
                        NativeToolCall(
                            id="tc1", name="calculator", args={"expr": "2+2"}
                        ),
                        NativeToolCall(
                            id="tc2", name="calculator", args={"expr": "3+3"}
                        ),
                    ),
                    stop_reason="tool_use",
                ),
                NativeToolCallResult(
                    text="Results: 4 and 6",
                    tool_calls=(),
                    stop_reason="end_turn",
                ),
            ]
        )

        async def calculator(expr: str) -> str:
            order.append(f"executed:{expr}")
            return _SAFE_CALC[expr]

        config = _make_config(use_native_tools=True)
        executor = ToolExecutor(local_tools={"calculator": calculator})
        llm_call = MockLLM([])

        import time

        async for event in run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            _make_tools(),
            config,
            time.monotonic(),
            native_adapter=adapter,
        ):
            if event.type == "tool_call_started":
                order.append(f"started:{event.data['correlation_id']}")
            elif event.type == "tool_call_finished":
                order.append(f"finished:{event.data['correlation_id']}")

        assert order.index("started:tc1") < order.index("executed:2+2")
        assert order.index("started:tc2") < order.index("executed:2+2")
        assert order.index("started:tc1") < order.index("executed:3+3")
        assert order.index("started:tc2") < order.index("executed:3+3")

    @pytest.mark.asyncio
    async def test_native_tool_results_are_preserved_in_final_history(self) -> None:
        """Native tool turns persist assistant tool_calls and tool result messages."""
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="Let me calculate",
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
            ]
        )
        config = _make_config(use_native_tools=True)
        executor = _make_executor()
        llm_call = MockLLM([])

        import time

        events = await _collect_events(
            run_react(
                llm_call,
                executor,
                _make_messages(),
                "system prompt",
                _make_tools(),
                config,
                time.monotonic(),
                native_adapter=adapter,
            )
        )
        final = next(e for e in events if e.type == "final")
        new_messages = final.data["new_messages"]

        tool_call_message = next(m for m in new_messages if m.get("tool_calls"))
        assert tool_call_message["role"] == "assistant"
        assert tool_call_message["tool_calls"] == [
            {"id": "tc1", "name": "calculator", "args": {"expr": "2+2"}}
        ]

        tool_message = next(m for m in new_messages if m["role"] == "tool")
        assert tool_message["name"] == "calculator"
        assert "4" in tool_message["content"]

    @pytest.mark.asyncio
    async def test_native_tools_fallback_on_error(self) -> None:
        """call_with_tools raises => fall through to JSON-in-text path."""
        adapter = ErrorNativeAdapter()

        config = _make_config(use_native_tools=True)
        executor = _make_executor()
        tools = _make_tools()

        llm_call = MockLLM(
            [
                json.dumps({"type": "final", "final_message": "Fallback response"}),
            ]
        )

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=adapter,
        )
        events = await _collect_events(strategy)

        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert finals[0].data["text"] == "Fallback response"

    @pytest.mark.asyncio
    async def test_native_tools_fallback_log_redacts_provider_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Native tool provider fallback must not log raw provider secrets."""
        secret = "sk-proj-native-call-secret-1234567890abcdef"
        adapter = ErrorNativeAdapter(f"Native API unavailable: {secret}")
        caplog.set_level(
            logging.WARNING, logger="swarmline.runtime.thin.react_strategy"
        )

        config = _make_config(use_native_tools=True)
        executor = _make_executor()
        llm_call = MockLLM(
            [
                json.dumps({"type": "final", "final_message": "Fallback response"}),
            ]
        )

        import time

        events = await _collect_events(
            run_react(
                llm_call,
                executor,
                _make_messages(),
                "system prompt",
                _make_tools(),
                config,
                time.monotonic(),
                native_adapter=adapter,
            )
        )

        assert next(e for e in events if e.type == "final").data["text"] == (
            "Fallback response"
        )
        assert secret not in caplog.text
        assert "RuntimeError" in caplog.text

    @pytest.mark.asyncio
    async def test_native_tools_single_tool_call(self) -> None:
        """Single tool call => sequential execution (no gather)."""
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="",
                    tool_calls=(
                        NativeToolCall(
                            id="tc1", name="calculator", args={"expr": "5+5"}
                        ),
                    ),
                    stop_reason="tool_use",
                ),
                NativeToolCallResult(
                    text="10",
                    tool_calls=(),
                    stop_reason="end_turn",
                ),
            ]
        )

        config = _make_config(use_native_tools=True)
        executor = _make_executor()
        tools = _make_tools()
        llm_call = MockLLM([])

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=adapter,
        )
        events = await _collect_events(strategy)

        tool_finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(tool_finished) == 1
        assert tool_finished[0].data["name"] == "calculator"

    @pytest.mark.asyncio
    async def test_native_tools_text_only_response(self) -> None:
        """No tool_calls in result => finalize as text response."""
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="Just a text answer",
                    tool_calls=(),
                    stop_reason="end_turn",
                ),
            ]
        )

        config = _make_config(use_native_tools=True)
        executor = _make_executor()
        tools = _make_tools()
        llm_call = MockLLM([])

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=adapter,
        )
        events = await _collect_events(strategy)

        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert finals[0].data["text"] == "Just a text answer"

    @pytest.mark.asyncio
    async def test_native_tools_budget_exceeded_returns_error(self) -> None:
        """Tool calls exceeding max_tool_calls returns budget_exceeded error."""
        adapter = MockNativeAdapter(
            [
                NativeToolCallResult(
                    text="",
                    tool_calls=(
                        NativeToolCall(
                            id="tc1", name="calculator", args={"expr": "2+2"}
                        ),
                        NativeToolCall(
                            id="tc2", name="calculator", args={"expr": "3+3"}
                        ),
                    ),
                    stop_reason="tool_use",
                ),
            ]
        )

        # max_tool_calls=1 but adapter returns 2 tool calls
        config = RuntimeConfig(
            runtime_name="thin",
            use_native_tools=True,
            max_iterations=10,
            max_tool_calls=1,
        )
        executor = _make_executor()
        tools = _make_tools()
        llm_call = MockLLM([])

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages(),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=adapter,
        )
        events = await _collect_events(strategy)

        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert "budget_exceeded" in str(errors[0].data)

    @pytest.mark.asyncio
    async def test_native_tools_adapter_none_uses_json_in_text(self) -> None:
        """native_adapter=None => JSON-in-text path (backward compat)."""
        config = _make_config(use_native_tools=True)  # Even if flag is True
        executor = _make_executor()
        tools = _make_tools()

        llm_call = MockLLM(
            [
                json.dumps({"type": "final", "final_message": "JSON path"}),
            ]
        )

        import time

        strategy = run_react(
            llm_call,
            executor,
            _make_messages("hello"),
            "system prompt",
            tools,
            config,
            time.monotonic(),
            native_adapter=None,
        )
        events = await _collect_events(strategy)

        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert finals[0].data["text"] == "JSON path"
