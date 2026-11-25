"""Tests for real provider usage capture (RUNTIME-PARITY D2, thin runtime).

Adapters must capture real token counts from provider responses (exposed as
``adapter.last_usage`` and recorded into the ContextVar channel in
``thin/usage.py``); finalization must prefer them (``usage_source: "native"``)
and fall back to the ~4 chars/token heuristic (``usage_source: "estimated"``).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from swarmline.runtime.cost import CostBudget
from swarmline.runtime.thin import llm_providers
from swarmline.runtime.thin.finalization import _build_usage
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.thin.usage import (
    consume_native_usage,
    record_native_usage,
    reset_native_usage,
)
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent


@pytest.fixture(autouse=True)
def _clean_usage_channel():
    reset_native_usage()
    yield
    reset_native_usage()


# ---------------------------------------------------------------------------
# usage.py channel + _build_usage
# ---------------------------------------------------------------------------


class TestUsageChannel:
    def test_record_and_consume_roundtrip(self) -> None:
        record_native_usage(100, 7)
        assert consume_native_usage() == {"input_tokens": 100, "output_tokens": 7}
        # one-shot: second consume returns nothing
        assert consume_native_usage() is None

    def test_record_nothing_when_both_counts_missing(self) -> None:
        assert record_native_usage(None, None) is None
        assert consume_native_usage() is None

    def test_partial_counts_default_to_zero(self) -> None:
        record_native_usage(None, 5)
        assert consume_native_usage() == {"input_tokens": 0, "output_tokens": 5}


class TestBuildUsage:
    def test_prefers_native_usage(self) -> None:
        record_native_usage(120, 45)
        usage = _build_usage([{"role": "user", "content": "hi"}], "sys", "answer")
        assert usage == {
            "input_tokens": 120,
            "output_tokens": 45,
            "total_tokens": 165,
            "usage_source": "native",
            "estimated": False,
            "attempts": 1,
        }

    def test_falls_back_to_estimated(self) -> None:
        usage = _build_usage([{"role": "user", "content": "x" * 40}], "sys", "y" * 40)
        assert usage["usage_source"] == "estimated"
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] > 0
        assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]


# ---------------------------------------------------------------------------
# Adapter capture: fake SDK clients carrying usage
# ---------------------------------------------------------------------------


class TestAnthropicAdapterUsage:
    @pytest.mark.asyncio
    async def test_call_captures_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import anthropic

        response = SimpleNamespace(
            content=[SimpleNamespace(text="hello")],
            usage=SimpleNamespace(input_tokens=120, output_tokens=45),
        )

        class _Messages:
            async def create(self, **kwargs: Any) -> Any:
                return response

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.messages = _Messages()

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeClient)
        adapter = llm_providers.AnthropicAdapter(model="claude-test")

        text = await adapter.call([{"role": "user", "content": "hi"}], "sys")

        assert text == "hello"
        assert adapter.last_usage == {"input_tokens": 120, "output_tokens": 45}
        assert consume_native_usage() == {"input_tokens": 120, "output_tokens": 45}

    @pytest.mark.asyncio
    async def test_call_without_usage_leaves_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import anthropic

        response = SimpleNamespace(content=[SimpleNamespace(text="hello")], usage=None)

        class _Messages:
            async def create(self, **kwargs: Any) -> Any:
                return response

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.messages = _Messages()

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeClient)
        adapter = llm_providers.AnthropicAdapter(model="claude-test")

        await adapter.call([{"role": "user", "content": "hi"}], "sys")

        assert adapter.last_usage is None
        assert consume_native_usage() is None

    @pytest.mark.asyncio
    async def test_call_with_tools_captures_usage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import anthropic

        block = SimpleNamespace(text="done")
        response = SimpleNamespace(
            content=[block],
            usage=SimpleNamespace(input_tokens=200, output_tokens=17),
            stop_reason="end_turn",
        )

        class _Messages:
            async def create(self, **kwargs: Any) -> Any:
                return response

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.messages = _Messages()

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeClient)
        adapter = llm_providers.AnthropicAdapter(model="claude-test")

        result = await adapter.call_with_tools(
            [{"role": "user", "content": "hi"}], "sys", tools=[]
        )

        assert result.text == "done"
        assert adapter.last_usage == {"input_tokens": 200, "output_tokens": 17}
        assert consume_native_usage() == {"input_tokens": 200, "output_tokens": 17}

    @pytest.mark.asyncio
    async def test_stream_captures_usage_from_final_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import anthropic

        class _FakeStream:
            def __init__(self) -> None:
                async def _texts():
                    yield "he"
                    yield "llo"

                self.text_stream = _texts()

            async def get_final_message(self) -> Any:
                return SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=11, output_tokens=4)
                )

        class _StreamCtx:
            async def __aenter__(self) -> Any:
                return _FakeStream()

            async def __aexit__(self, *args: Any) -> bool:
                return False

        class _Messages:
            def stream(self, **kwargs: Any) -> Any:
                return _StreamCtx()

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.messages = _Messages()

        monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeClient)
        adapter = llm_providers.AnthropicAdapter(model="claude-test")

        chunks = [
            c async for c in adapter.stream([{"role": "user", "content": "hi"}], "sys")
        ]

        assert "".join(chunks) == "hello"
        assert adapter.last_usage == {"input_tokens": 11, "output_tokens": 4}
        assert consume_native_usage() == {"input_tokens": 11, "output_tokens": 4}


class TestOpenAIAdapterUsage:
    @staticmethod
    def _fake_openai(monkeypatch: pytest.MonkeyPatch, create: Any) -> None:
        import openai

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        monkeypatch.setattr(openai, "AsyncOpenAI", _FakeClient)

    @pytest.mark.asyncio
    async def test_call_captures_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
        )

        async def _create(**kwargs: Any) -> Any:
            return response

        self._fake_openai(monkeypatch, _create)
        adapter = llm_providers.OpenAICompatAdapter(model="gpt-test")

        text = await adapter.call([{"role": "user", "content": "hi"}], "sys")

        assert text == "hi"
        assert adapter.last_usage == {"input_tokens": 10, "output_tokens": 3}
        assert consume_native_usage() == {"input_tokens": 10, "output_tokens": 3}

    @pytest.mark.asyncio
    async def test_stream_requests_and_captures_usage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_kwargs: dict[str, Any] = {}

        async def _create(**kwargs: Any) -> Any:
            captured_kwargs.update(kwargs)

            async def _gen():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="he"))],
                    usage=None,
                )
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="y"))],
                    usage=None,
                )
                # OpenAI protocol: usage arrives on a trailing chunk with no choices
                yield SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(prompt_tokens=9, completion_tokens=2),
                )

            return _gen()

        self._fake_openai(monkeypatch, _create)
        adapter = llm_providers.OpenAICompatAdapter(model="gpt-test")

        chunks = [
            c async for c in adapter.stream([{"role": "user", "content": "hi"}], "sys")
        ]

        assert "".join(chunks) == "hey"
        assert captured_kwargs["stream_options"] == {"include_usage": True}
        assert adapter.last_usage == {"input_tokens": 9, "output_tokens": 2}
        assert consume_native_usage() == {"input_tokens": 9, "output_tokens": 2}

    @pytest.mark.asyncio
    async def test_call_with_tools_captures_usage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="done", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=33, completion_tokens=8),
        )

        async def _create(**kwargs: Any) -> Any:
            return response

        self._fake_openai(monkeypatch, _create)
        adapter = llm_providers.OpenAICompatAdapter(model="gpt-test")

        result = await adapter.call_with_tools(
            [{"role": "user", "content": "hi"}], "sys", tools=[]
        )

        assert result.text == "done"
        assert adapter.last_usage == {"input_tokens": 33, "output_tokens": 8}
        assert consume_native_usage() == {"input_tokens": 33, "output_tokens": 8}


class TestGoogleAdapterUsage:
    @pytest.mark.asyncio
    async def test_call_captures_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import google.genai as genai

        response = SimpleNamespace(
            text="hi",
            usage_metadata=SimpleNamespace(
                prompt_token_count=30, candidates_token_count=5
            ),
        )

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.models = SimpleNamespace(generate_content=lambda **kw: response)

        monkeypatch.setattr(genai, "Client", _FakeClient)
        adapter = llm_providers.GoogleAdapter(model="gemini-test")

        text = await adapter.call([{"role": "user", "content": "hi"}], "sys")

        assert text == "hi"
        assert adapter.last_usage == {"input_tokens": 30, "output_tokens": 5}
        assert consume_native_usage() == {"input_tokens": 30, "output_tokens": 5}

    @pytest.mark.asyncio
    async def test_stream_captures_usage_from_final_chunk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import google.genai as genai

        async def _gen():
            yield SimpleNamespace(text="he", usage_metadata=None)
            yield SimpleNamespace(
                text="y",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=12, candidates_token_count=6
                ),
            )

        class _FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                self.models = SimpleNamespace(
                    generate_content_stream=lambda **kw: _gen()
                )

        monkeypatch.setattr(genai, "Client", _FakeClient)
        adapter = llm_providers.GoogleAdapter(model="gemini-test")

        chunks = [
            c async for c in adapter.stream([{"role": "user", "content": "hi"}], "sys")
        ]

        assert "".join(chunks) == "hey"
        assert adapter.last_usage == {"input_tokens": 12, "output_tokens": 6}
        assert consume_native_usage() == {"input_tokens": 12, "output_tokens": 6}


# ---------------------------------------------------------------------------
# End-to-end: final event usage + CostTracker
# ---------------------------------------------------------------------------


async def _collect(
    runtime: ThinRuntime, config: RuntimeConfig | None = None
) -> list[RuntimeEvent]:
    events: list[RuntimeEvent] = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="hi")],
        system_prompt="sys",
        active_tools=[],
        config=config,
        mode_hint="conversational",
    ):
        events.append(ev)
    return events


def _final(events: list[RuntimeEvent]) -> RuntimeEvent:
    return next(e for e in events if e.type == "final")


class TestFinalEventUsage:
    @pytest.mark.asyncio
    async def test_native_usage_flows_into_final_event(self) -> None:
        async def fake_llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            # Simulates what a real adapter does after a provider response.
            record_native_usage(100, 7)
            return json.dumps({"type": "final", "final_message": "done"})

        runtime = ThinRuntime(llm_call=fake_llm)
        final = _final(await _collect(runtime))

        assert final.data["usage"] == {
            "input_tokens": 100,
            "output_tokens": 7,
            "total_tokens": 107,
            "usage_source": "native",
            "estimated": False,
            "attempts": 1,
        }
        assert final.data["metrics"]["tokens_in"] == 100
        assert final.data["metrics"]["tokens_out"] == 7

    @pytest.mark.asyncio
    async def test_heuristic_fallback_keeps_estimated_source(self) -> None:
        async def fake_llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        runtime = ThinRuntime(llm_call=fake_llm)
        final = _final(await _collect(runtime))

        usage = final.data["usage"]
        assert usage["usage_source"] == "estimated"
        assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]

    @pytest.mark.asyncio
    async def test_cost_tracker_records_native_tokens(self) -> None:
        async def fake_llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            record_native_usage(1000, 500)
            return json.dumps({"type": "final", "final_message": "done"})

        config = RuntimeConfig(
            runtime_name="thin", cost_budget=CostBudget(max_cost_usd=10.0)
        )
        runtime = ThinRuntime(config=config, llm_call=fake_llm)
        final = _final(await _collect(runtime, config))

        assert final.data["usage"]["usage_source"] == "native"
        assert "total_cost_usd" in final.data
        tracker = runtime._cost_tracker
        assert tracker is not None
        assert tracker.total_tokens == 1500

    @pytest.mark.asyncio
    async def test_stale_usage_is_reset_between_runs(self) -> None:
        # Leftover recording from a previous (e.g. failed) run must NOT be
        # attributed to a run whose llm_call reports no native usage.
        record_native_usage(9999, 9999)

        async def fake_llm(messages: Any, system_prompt: str, **kwargs: Any) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        runtime = ThinRuntime(llm_call=fake_llm)
        final = _final(await _collect(runtime))

        assert final.data["usage"]["usage_source"] == "estimated"
