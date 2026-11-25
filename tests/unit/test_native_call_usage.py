"""Sprint 1ce Stage 3, slice 3.0 (ref: hermes 2026-09-27): usage of EVERY call.

``NativeToolCallResult`` carries the provider's usage for that one call, and
the ReAct loop sums it across the run into ``provider_usage`` of the final
event — closing BL-89 (react never passed provider_usage) and BL-98 (cache
counters described only the last call). No network: fake SDK clients.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from swarmline.runtime.thin import llm_providers
from swarmline.runtime.thin.executor import ToolExecutor
from swarmline.runtime.thin.native_tools import NativeToolCall, NativeToolCallResult
from swarmline.runtime.thin.strategies import run_react
from swarmline.runtime.thin.usage import (
    add_call_usage,
    record_native_usage,
    reset_native_usage,
)
from swarmline.runtime.types import RuntimeConfig, ToolSpec


@pytest.fixture(autouse=True)
def _clean_usage_channel():
    reset_native_usage()
    yield
    reset_native_usage()


def _anthropic(monkeypatch: pytest.MonkeyPatch, with_usage: bool = True):
    import anthropic

    response = SimpleNamespace(
        content=[SimpleNamespace(text="done")],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=10,
            cache_read_input_tokens=50,
            cache_creation_input_tokens=20,
        )
        if with_usage
        else None,
        stop_reason="end_turn",
    )

    class _Messages:
        async def create(self, **kwargs: Any) -> Any:
            return response

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.messages = _Messages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Client)
    return llm_providers.AnthropicAdapter(model="claude-test"), {
        "input_tokens": 100,
        "output_tokens": 10,
        "total_tokens": 110,
        "cache_read_tokens": 50,
        "cache_write_tokens": 20,
        # Anthropic's input_tokens excludes cached tokens: the prompt is the sum.
        "prompt_tokens": 170,
    }


def _openai(monkeypatch: pytest.MonkeyPatch, with_usage: bool = True):
    import openai

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="done", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=300,
            completion_tokens=12,
            prompt_tokens_details=SimpleNamespace(cached_tokens=200),
        )
        if with_usage
        else None,
    )

    async def _create(**kwargs: Any) -> Any:
        return response

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    monkeypatch.setattr(openai, "AsyncOpenAI", _Client)
    return llm_providers.OpenAICompatAdapter(model="gpt-test"), {
        "input_tokens": 300,
        "output_tokens": 12,
        "total_tokens": 312,
        "cache_read_tokens": 200,
        "prompt_tokens": 300,
    }


def _google(monkeypatch: pytest.MonkeyPatch, with_usage: bool = True):
    import google.genai as genai

    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text="ok")]))
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=80,
            candidates_token_count=5,
            cached_content_token_count=40,
        )
        if with_usage
        else None,
    )

    async def _generate_content(**kwargs: Any) -> Any:
        return response

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.aio = SimpleNamespace(
                models=SimpleNamespace(generate_content=_generate_content)
            )

    monkeypatch.setattr(genai, "Client", _Client)
    return llm_providers.GoogleAdapter(model="gemini-test"), {
        "input_tokens": 80,
        "output_tokens": 5,
        "total_tokens": 85,
        "cache_read_tokens": 40,
        "prompt_tokens": 80,
    }


@pytest.mark.parametrize("make", [_anthropic, _openai, _google])
async def test_each_provider_returns_usage_on_native_tool_call(
    make, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, expected = make(monkeypatch)

    result = await adapter.call_with_tools(
        [{"role": "user", "content": "hi"}], "sys", tools=[]
    )

    assert result.usage == expected


@pytest.mark.parametrize("make", [_anthropic, _openai, _google])
async def test_provider_without_usage_returns_none_usage(
    make, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _ = make(monkeypatch, with_usage=False)

    result = await adapter.call_with_tools(
        [{"role": "user", "content": "hi"}], "sys", tools=[]
    )

    assert result.usage is None


def test_add_call_usage_sums_present_counters_only() -> None:
    total = add_call_usage(None, None)
    assert total is None
    total = add_call_usage(total, {"input_tokens": 10, "output_tokens": 2})
    total = add_call_usage(
        total, {"input_tokens": 5, "output_tokens": 1, "cache_read_tokens": 3}
    )
    total = add_call_usage(total, {"cache_read_tokens": "bogus", "input_tokens": 1})
    # A call whose usage carries no summable counter leaves the total as is.
    assert add_call_usage(None, {"prompt_tokens": 5}) is None

    assert total == {
        "input_tokens": 16,
        "output_tokens": 3,
        "total_tokens": 19,
        "cache_read_tokens": 3,
    }


class _ScriptedNative:
    def __init__(self, results: list[NativeToolCallResult]) -> None:
        self._results = list(results)

    async def call_with_tools(self, messages, system_prompt, tools, **kwargs):
        return self._results.pop(0)


def _call(i: int, usage: dict[str, int]) -> NativeToolCallResult:
    return NativeToolCallResult(
        text=f"step {i}",
        tool_calls=(NativeToolCall(id=f"c{i}", name="probe", args={}),),
        stop_reason="tool_use",
        usage=usage,
    )


async def _final_usage(results: list[NativeToolCallResult]) -> dict[str, Any]:
    async def _probe(args: dict[str, Any]) -> str:
        return "ok"

    events = [
        ev
        async for ev in run_react(
            _unused_llm_call,
            ToolExecutor(local_tools={"probe": _probe}),
            [],
            "sys",
            [ToolSpec(name="probe", description="d", parameters={"type": "object"})],
            RuntimeConfig(runtime_name="thin", use_native_tools=True),
            time.monotonic(),
            native_adapter=_ScriptedNative(results),
        )
    ]
    finals = [ev for ev in events if ev.type == "final"]
    assert len(finals) == 1, [ev.type for ev in events]
    return finals[0].data["usage"]


async def _unused_llm_call(messages, prompt, **kwargs):
    raise AssertionError("the native loop must not fall back to llm_call")


async def test_react_run_usage_sums_cache_counters_across_calls() -> None:
    usage = await _final_usage(
        [
            _call(1, {"input_tokens": 100, "output_tokens": 5, "cache_read_tokens": 0}),
            _call(
                2, {"input_tokens": 200, "output_tokens": 5, "cache_read_tokens": 500}
            ),
            NativeToolCallResult(
                text="all done",
                usage={
                    "input_tokens": 300,
                    "output_tokens": 7,
                    "cache_read_tokens": 700,
                },
            ),
        ]
    )

    assert usage["cache_read_tokens"] == 1_200


async def test_react_passes_provider_usage_to_finalize() -> None:
    usage = await _final_usage(
        [
            _call(1, {"input_tokens": 100, "output_tokens": 5}),
            NativeToolCallResult(
                text="done", usage={"input_tokens": 200, "output_tokens": 9}
            ),
        ]
    )

    assert usage["usage_source"] == "native"
    assert usage["estimated"] is False
    assert usage["input_tokens"] == 300
    assert usage["output_tokens"] == 14


async def test_react_without_call_usage_keeps_estimated_usage() -> None:
    usage = await _final_usage(
        [_call(1, None), NativeToolCallResult(text="done")]  # type: ignore[arg-type]
    )

    assert usage["usage_source"] == "estimated"
    assert "cache_read_tokens" not in usage


async def test_custom_native_usage_survives_builtin_structured_repair() -> None:
    class _Answer(BaseModel):
        answer: str

    async def repair(messages, prompt, **kwargs):
        record_native_usage(42, 7)
        return '{"answer": "repaired"}'

    adapter = _ScriptedNative(
        [
            NativeToolCallResult(
                text="not structured",
                usage={"input_tokens": 10_000, "output_tokens": 1_000},
            )
        ]
    )
    events = [
        event
        async for event in run_react(
            repair,
            ToolExecutor(local_tools={}),
            [],
            "sys",
            [ToolSpec(name="probe", description="d", parameters={"type": "object"})],
            RuntimeConfig(
                runtime_name="thin",
                use_native_tools=True,
                output_type=_Answer,
                output_format=_Answer.model_json_schema(),
                native_config={"loop_guards_enabled": True, "run_budget_seconds": 60},
            ),
            time.monotonic(),
            native_adapter=adapter,
        )
    ]

    final = next(event for event in events if event.is_final)
    assert final.data["usage"]["input_tokens"] == 10_042
    assert final.data["usage"]["output_tokens"] == 1_007
    assert final.data["usage"]["total_tokens"] == 11_049
