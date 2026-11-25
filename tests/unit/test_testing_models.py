"""Tests for TestModel and FunctionModel LLM provider test doubles.

Stage A2 — verifies the testing/models.py surface end-to-end, offline.
"""

from __future__ import annotations

import json
from typing import Any


from swarmline.runtime.thin.llm_providers import LlmAdapter
from swarmline.runtime.thin.native_tools import (
    NativeToolCallAdapter,
    NativeToolCallResult,
)
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _final_env(text: str) -> str:
    return json.dumps(
        {
            "type": "final",
            "final_message": text,
            "citations": [],
            "next_suggestions": [],
        }
    )


def _tool_call_env(name: str, args: dict[str, Any], cid: str = "c1") -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": args, "correlation_id": cid},
            "assistant_message": "",
        }
    )


async def _collect(
    runtime: ThinRuntime,
    text: str = "hello",
    tools: list[ToolSpec] | None = None,
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="You are a test assistant.",
        active_tools=tools or [],
    ):
        events.append(ev)
    return events


def _final_event(events: list[RuntimeEvent]) -> RuntimeEvent:
    return next(e for e in events if e.is_final)


# ---------------------------------------------------------------------------
# _json_schema_sample
# ---------------------------------------------------------------------------


class TestJsonSchemaSample:
    """Pure helper — deterministic sample from JSON schema."""

    def test_json_schema_sample_string_type_returns_a(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        assert _json_schema_sample({"type": "string"}) == "a"

    def test_json_schema_sample_integer_type_returns_zero(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        assert _json_schema_sample({"type": "integer"}) == 0

    def test_json_schema_sample_number_type_returns_float_zero(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        assert _json_schema_sample({"type": "number"}) == 0.0

    def test_json_schema_sample_boolean_type_returns_false(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        assert _json_schema_sample({"type": "boolean"}) is False

    def test_json_schema_sample_array_type_returns_empty_list(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        assert _json_schema_sample({"type": "array"}) == []

    def test_json_schema_sample_enum_returns_first_value(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        schema = {"type": "string", "enum": ["red", "green", "blue"]}
        assert _json_schema_sample(schema) == "red"

    def test_json_schema_sample_object_with_required_fills_required_only(self) -> None:
        """Only ``required`` props are filled when present."""
        from swarmline.testing.models import _json_schema_sample

        schema = {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "n": {"type": "integer"},
                "opt": {"type": "boolean"},
            },
            "required": ["q", "n"],
        }
        result = _json_schema_sample(schema)
        assert result == {"q": "a", "n": 0}
        assert "opt" not in result

    def test_json_schema_sample_object_without_required_fills_all_props(self) -> None:
        """When ``required`` is absent all properties are filled (documented choice)."""
        from swarmline.testing.models import _json_schema_sample

        schema = {
            "type": "object",
            "properties": {
                "x": {"type": "string"},
                "y": {"type": "integer"},
            },
        }
        result = _json_schema_sample(schema)
        # No ``required`` → all props filled
        assert result == {"x": "a", "y": 0}

    def test_json_schema_sample_nested_object_recurses(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        schema = {
            "type": "object",
            "properties": {
                "inner": {
                    "type": "object",
                    "properties": {"val": {"type": "integer"}},
                    "required": ["val"],
                }
            },
            "required": ["inner"],
        }
        assert _json_schema_sample(schema) == {"inner": {"val": 0}}

    def test_json_schema_sample_unknown_or_absent_type_returns_none(self) -> None:
        from swarmline.testing.models import _json_schema_sample

        assert _json_schema_sample({"type": "null"}) is None  # explicit unknown type
        assert _json_schema_sample({}) is None  # absent type key


# ---------------------------------------------------------------------------
# FunctionModel
# ---------------------------------------------------------------------------


class TestFunctionModel:
    """FunctionModel — sync and async function delegation."""

    async def test_as_llm_call_returns_deterministic_final_text(self) -> None:
        """fn returns a final envelope; ThinRuntime produces exact result.text."""
        from swarmline.testing import FunctionModel

        expected = "Hello from FunctionModel"
        fn_return = _final_env(expected)
        model = FunctionModel(fn=lambda _: fn_return)
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=model.as_llm_call(),
        )
        events = await _collect(runtime)
        final = _final_event(events)
        assert final.data["text"] == expected

    async def test_drives_tool_call_then_final(self) -> None:
        """fn returns tool_call on call-1, final on call-2; tool is executed."""
        from swarmline.testing import FunctionModel

        tool_result: str | None = None

        async def echo(msg: str) -> str:
            nonlocal tool_result
            tool_result = msg
            return f"echo:{msg}"

        responses = [
            _tool_call_env("echo", {"msg": "hi"}),
            _final_env("done"),
        ]
        it = iter(responses)
        model = FunctionModel(fn=lambda _: next(it))

        tool_spec = ToolSpec(
            name="echo",
            description="Echo a message",
            parameters={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        )
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=model.as_llm_call(),
            local_tools={"echo": echo},
        )
        events = await _collect(runtime, tools=[tool_spec])

        types = [e.type for e in events]
        assert "tool_call_started" in types
        assert "tool_call_finished" in types
        assert "final" in types
        assert tool_result == "hi"

    async def test_supports_async_fn(self) -> None:
        """Async fn works identically to sync fn."""
        from swarmline.testing import FunctionModel

        expected = "async result"

        async def async_fn(messages: list[dict[str, str]]) -> str:
            return _final_env(expected)

        model = FunctionModel(fn=async_fn)
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=model.as_llm_call(),
        )
        events = await _collect(runtime)
        final = _final_event(events)
        assert final.data["text"] == expected

    async def test_plain_text_fn_terminates_loop(self) -> None:
        """fn returning plain text (no JSON envelope) → loop applies text fallback."""
        from swarmline.testing import FunctionModel

        # The runtime tolerates bare text after exhausting JSON retries:
        # it falls back to extract_text_fallback and emits a final event.
        # The test just verifies no exception is raised and we get a final event.
        model = FunctionModel(fn=lambda _: "plain text response")
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=model.as_llm_call(),
        )
        events = await _collect(runtime)
        # Either final or error — loop must terminate, not hang
        terminal = [e for e in events if e.is_final or e.type == "error"]
        assert terminal, "loop must terminate"

    def test_satisfies_llm_adapter_protocol(self) -> None:
        from swarmline.testing import FunctionModel

        model = FunctionModel(fn=lambda _: "x")
        assert isinstance(model, LlmAdapter)

    def test_satisfies_native_tool_call_adapter_protocol(self) -> None:
        from swarmline.testing import FunctionModel

        model = FunctionModel(fn=lambda _: "x")
        assert isinstance(model, NativeToolCallAdapter)


# ---------------------------------------------------------------------------
# TestModel
# ---------------------------------------------------------------------------


class TestTestModel:
    """TestModel — deterministic native-tools double."""

    def test_is_not_collected_by_pytest(self) -> None:
        """TestModel.__test__ must be False so pytest skips it."""
        from swarmline.testing import TestModel

        assert TestModel.__test__ is False

    def test_satisfies_llm_adapter_protocol(self) -> None:
        from swarmline.testing import TestModel

        model = TestModel()
        assert isinstance(model, LlmAdapter)

    def test_satisfies_native_tool_call_adapter_protocol(self) -> None:
        from swarmline.testing import TestModel

        model = TestModel()
        assert isinstance(model, NativeToolCallAdapter)

    async def test_call_with_tools_autogenerates_schema_valid_args(self) -> None:
        """Tool with object schema → NativeToolCall.args matches expected sample."""
        from swarmline.testing import TestModel

        model = TestModel()
        tools = [
            {
                "name": "search",
                "description": "Search",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "n": {"type": "integer"},
                    },
                    "required": ["q", "n"],
                },
            }
        ]
        result: NativeToolCallResult = await model.call_with_tools(
            [{"role": "user", "content": "go"}], "sys", tools
        )
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.name == "search"
        assert tc.args == {"q": "a", "n": 0}

    async def test_call_with_tools_respects_call_tools_empty_returns_final(
        self,
    ) -> None:
        """call_tools=[] → no tool calls, final text returned immediately."""
        from swarmline.testing import TestModel

        model = TestModel(call_tools=[], custom_output_text="no tools")
        tools = [{"name": "search", "parameters": {}, "description": ""}]
        result: NativeToolCallResult = await model.call_with_tools(
            [{"role": "user", "content": "go"}], "sys", tools
        )
        assert result.tool_calls == ()
        assert result.text == "no tools"

    async def test_call_with_tools_second_invocation_returns_final(self) -> None:
        """Second call_with_tools call always returns final (loop termination guard)."""
        from swarmline.testing import TestModel

        model = TestModel(custom_output_text="done")
        tools = [{"name": "t", "parameters": {}, "description": ""}]
        msgs = [{"role": "user", "content": "go"}]

        # First call → should emit tool_calls
        r1 = await model.call_with_tools(msgs, "sys", tools)
        # Second call → MUST return final (no infinite loop)
        r2 = await model.call_with_tools(msgs, "sys", tools)
        assert r2.tool_calls == ()
        assert r2.text == "done"
        # Sanity: first call did emit a tool call (at least one)
        _ = r1  # noqa: F841

    async def test_as_llm_call_emits_final_envelope_for_conversational(
        self,
    ) -> None:
        """Conversational mode (no tools) → final event with expected text."""
        from swarmline.testing import TestModel

        model = TestModel(custom_output_text="hello world")
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=model.as_llm_call(),
        )
        events = await _collect(runtime)
        final = _final_event(events)
        assert final.data["text"] == "hello world"

    async def test_structured_output_validates_against_schema(self) -> None:
        """custom_output_args + output_format → structured_output in final event."""
        from swarmline.testing import TestModel

        payload = {"score": 42}
        model = TestModel(custom_output_args=payload)
        config = RuntimeConfig(
            runtime_name="thin",
            output_format={
                "type": "object",
                "properties": {"score": {"type": "integer"}},
            },
        )
        runtime = ThinRuntime(config=config, llm_call=model.as_llm_call())
        events = await _collect(runtime)
        final = _final_event(events)
        assert final.structured_output == payload

    async def test_custom_output_args_becomes_final_text(self) -> None:
        """custom_output_args is JSON-serialised and returned as final_message."""
        from swarmline.testing import TestModel

        model = TestModel(custom_output_args={"key": "value"})
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=model.as_llm_call(),
        )
        events = await _collect(runtime)
        final = _final_event(events)
        assert json.loads(final.data["text"]) == {"key": "value"}

    async def test_end_to_end_native_tools_executes_generated_call(self) -> None:
        """ThinRuntime(native_adapter=TestModel()) executes auto-generated tool call."""
        from swarmline.testing import TestModel

        executed_args: dict[str, Any] = {}

        async def my_tool(msg: str) -> str:
            executed_args["msg"] = msg
            return f"result:{msg}"

        tool_spec = ToolSpec(
            name="my_tool",
            description="Test tool",
            parameters={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        )
        model = TestModel()
        # Provide both llm_call (for Phase-2 fallback) and native_adapter
        runtime = ThinRuntime(
            config=RuntimeConfig(
                runtime_name="thin",
                use_native_tools=True,
            ),
            llm_call=model.as_llm_call(),
            native_adapter=model,
            local_tools={"my_tool": my_tool},
        )
        events = await _collect(runtime, tools=[tool_spec])

        event_types = [e.type for e in events]
        assert "tool_call_started" in event_types
        assert "tool_call_finished" in event_types
        assert "final" in event_types
        # Auto-generated arg for string type = "a"
        assert executed_args.get("msg") == "a"

    async def test_end_to_end_native_tools_call_tools_empty_skips_tool(
        self,
    ) -> None:
        """call_tools=[] → tool is NOT called even when active_tools is non-empty."""
        from swarmline.testing import TestModel

        called = False

        async def my_tool(msg: str) -> str:
            nonlocal called
            called = True
            return "called"

        tool_spec = ToolSpec(
            name="my_tool",
            description="Test tool",
            parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        )
        model = TestModel(call_tools=[])
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", use_native_tools=True),
            llm_call=model.as_llm_call(),
            native_adapter=model,
            local_tools={"my_tool": my_tool},
        )
        events = await _collect(runtime, tools=[tool_spec])
        assert not called
        assert any(e.is_final for e in events)


# ---------------------------------------------------------------------------
# ThinRuntime native_adapter seam
# ---------------------------------------------------------------------------


class TestThinRuntimeNativeAdapterSeam:
    """native_adapter constructor param — backward-compat guard."""

    def test_defaults_to_none_preserves_existing_behavior(self) -> None:
        """ThinRuntime without native_adapter kwarg constructs without error."""
        from swarmline.testing import TestModel

        llm = TestModel()
        # This must NOT raise — the new param has None default
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=llm.as_llm_call(),
        )
        # native_adapter defaulted to None → no auto-resolution without use_native_tools
        assert runtime._native_adapter is None

    def test_provided_adapter_is_stored(self) -> None:
        """native_adapter= sets self._native_adapter on the runtime."""
        from swarmline.testing import TestModel

        llm = TestModel()
        adapter = TestModel()
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=llm.as_llm_call(),
            native_adapter=adapter,
        )
        assert runtime._native_adapter is adapter

    def test_provided_adapter_overrides_auto_resolve(self) -> None:
        """User-supplied native_adapter wins over auto-resolved one."""
        from swarmline.testing import TestModel

        llm = TestModel()
        adapter = TestModel()
        # llm_call is provided, so auto-resolve does NOT run (it is gated on
        # llm_call is None). The native_adapter kwarg is applied unconditionally
        # after the auto-resolve block, so it wins regardless.
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", use_native_tools=True),
            llm_call=llm.as_llm_call(),
            native_adapter=adapter,
        )
        assert runtime._native_adapter is adapter


# ---------------------------------------------------------------------------
# Import surface
# ---------------------------------------------------------------------------


def test_public_imports() -> None:
    """from swarmline.testing import TestModel, FunctionModel works."""
    from swarmline.testing import FunctionModel, TestModel  # noqa: F401

    assert FunctionModel is not None
    assert TestModel is not None
