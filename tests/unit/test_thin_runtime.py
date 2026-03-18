"""Tests for ThinRuntime - react loop: tool_call -> final (mock LLM)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from cognitia.retry import ExponentialBackoff
from cognitia.runtime.thin.errors import ThinLlmError
from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
)

# ---------------------------------------------------------------------------
# Mock LLM - returns zaranote zadannye responsey
# ---------------------------------------------------------------------------


class MockLLM:
    """Mock LLM: returns responsey from ocheredi."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    async def __call__(self, messages: list[dict], system_prompt: str) -> str:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return json.dumps({"type": "final", "final_message": "fallback"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def collect(
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


def make_tool_call_response(name: str, args: dict | None = None, cid: str = "c1") -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": args or {}, "correlation_id": cid},
            "assistant_message": "",
        }
    )


def make_final_response(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


def make_clarify_response(questions: list[dict], msg: str = "") -> str:
    return json.dumps(
        {
            "type": "clarify",
            "questions": questions,
            "assistant_message": msg,
        }
    )


# ---------------------------------------------------------------------------
# React mode tests
# ---------------------------------------------------------------------------


class TestThinRuntimeReact:
    """React loop: tool_call → tool_result → final."""

    @pytest.mark.asyncio
    async def test_single_tool_then_final(self) -> None:
        """1 tool_call → tool_result → final."""

        def calc(args):
            return {"result": 42}

        llm = MockLLM(
            [
                make_tool_call_response("calc", {"x": 1}),
                make_final_response("Результат: 42"),
            ]
        )
        runtime = ThinRuntime(llm_call=llm, local_tools={"calc": calc})

        events = await collect(runtime, "Посчитай", mode_hint="react")
        types = [e.type for e in events]

        assert "tool_call_started" in types
        assert "tool_call_finished" in types
        assert "final" in types

        final = next(e for e in events if e.type == "final")
        assert "42" in final.data["text"]

    @pytest.mark.asyncio
    async def test_two_tools_then_final(self) -> None:
        """2 tool_calls → final."""

        def tool_a(args):
            return {"a": 1}

        def tool_b(args):
            return {"b": 2}

        llm = MockLLM(
            [
                make_tool_call_response("tool_a"),
                make_tool_call_response("tool_b"),
                make_final_response("Готово: a=1, b=2"),
            ]
        )
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"tool_a": tool_a, "tool_b": tool_b},
        )

        events = await collect(runtime, "Используй оба", mode_hint="react")

        started = [e for e in events if e.type == "tool_call_started"]
        finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(started) == 2
        assert len(finished) == 2

    @pytest.mark.asyncio
    async def test_direct_final_no_tools(self) -> None:
        """LLM srazu returns final (without tool_call)."""
        llm = MockLLM([make_final_response("Простой ответ")])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "Что такое инфляция?", mode_hint="react")
        types = [e.type for e in events]
        assert "final" in types
        assert "tool_call_started" not in types

    @pytest.mark.asyncio
    async def test_clarify_response(self) -> None:
        """LLM returns clarify -> final with voprosami."""
        llm = MockLLM(
            [
                make_clarify_response(
                    [{"id": "income", "text": "Какой доход?"}],
                    msg="Уточните",
                ),
            ]
        )
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "Посчитай", mode_hint="react")
        final = next(e for e in events if e.type == "final")
        assert "Какой доход?" in final.data["text"]

    @pytest.mark.asyncio
    async def test_tool_execution_error(self) -> None:
        """Tool raises -> tool_call_finished with ok=False, loop prodolzhaetsya."""

        def bad_tool(args):
            raise ValueError("broken")

        llm = MockLLM(
            [
                make_tool_call_response("bad_tool"),
                make_final_response("Не удалось"),
            ]
        )
        runtime = ThinRuntime(llm_call=llm, local_tools={"bad_tool": bad_tool})

        events = await collect(runtime, "test", mode_hint="react")

        finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(finished) == 1
        assert finished[0].data["ok"] is False


# ---------------------------------------------------------------------------
# Conversational mode
# ---------------------------------------------------------------------------


class TestThinRuntimeConversational:
    """Conversational mode: single LLM call → final."""

    @pytest.mark.asyncio
    async def test_conversational_simple(self) -> None:
        llm = MockLLM([make_final_response("Привет! Как дела?")])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "Привет", mode_hint="conversational")
        types = [e.type for e in events]
        assert "final" in types

        final = next(e for e in events if e.type == "final")
        assert final.data["text"] == "Привет! Как дела?"

    @pytest.mark.asyncio
    async def test_conversational_bad_json_retry(self) -> None:
        """Bad JSON -> retry -> success."""
        llm = MockLLM(
            [
                "это не JSON",
                make_final_response("Повторный ответ"),
            ]
        )
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "test", mode_hint="conversational")
        final = [e for e in events if e.type == "final"]
        assert len(final) == 1
        assert final[0].data["text"] == "Повторный ответ"

    @pytest.mark.asyncio
    async def test_retry_policy_does_not_wrap_llm_callable_twice(self) -> None:
        """retry_policy should not add a second wrapper over buffered retry."""
        llm = MockLLM([make_final_response("Повторный ответ")])
        policy = ExponentialBackoff(max_retries=2, base_delay=0.0, jitter=False)
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", retry_policy=policy),
            llm_call=llm,
        )

        assert runtime._llm_call is llm  # noqa: SLF001 - regression guard

        events = await collect(runtime, "test", mode_hint="conversational")
        final = next(e for e in events if e.type == "final")
        assert final.data["text"] == "Повторный ответ"

    @pytest.mark.asyncio
    async def test_conversational_streaming_without_postprocessing_keeps_eager_deltas(self) -> None:
        """Without guardrails/output_type/retry chanki strimyatsya eagerly kak ranshe."""

        async def streaming_llm(
            messages: list[dict[str, str]],
            system_prompt: str,
            **kwargs: Any,
        ) -> Any:
            if kwargs.get("stream"):
                async def _stream():
                    yield '{"type":"final","final_message":"Hel'
                    yield 'lo"}'

                return _stream()
            raise AssertionError("non-stream fallback is not expected")

        runtime = ThinRuntime(llm_call=streaming_llm)

        events = await collect(runtime, "Привет", mode_hint="conversational")
        deltas = [event.data["text"] for event in events if event.type == "assistant_delta"]
        final = next(event for event in events if event.type == "final")

        assert deltas == ['{"type":"final","final_message":"Hel', 'lo"}']
        assert final.data["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_parse_json_inside_wrapped_text(self) -> None:
        """Parser can izvlekat JSON from teksta do/posle bloka."""
        wrapped = (
            "Сейчас отвечу.\n\n"
            '{"type":"final","final_message":"Ок","citations":[],"next_suggestions":[]}\n'
            "\nСпасибо!"
        )
        llm = MockLLM([wrapped])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "test", mode_hint="conversational")
        final = next(e for e in events if e.type == "final")
        assert final.data["text"] == "Ок"

    @pytest.mark.asyncio
    async def test_stream_init_dependency_error_emits_runtime_error(self) -> None:
        """Error initsializatsii stream path not prevrashchaetsya in assistant_delta JSON."""
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", model="google:gemini-2.5-pro")
        )
        thin_error = ThinLlmError(
            RuntimeErrorData(
                kind="dependency_missing",
                message="google-genai SDK не установлен. Установите: pip install cognitia[thin]",
                recoverable=False,
            )
        )
        with patch(
            "cognitia.runtime.thin.llm_client.get_cached_adapter",
            side_effect=thin_error,
        ):
            events = await collect(runtime, "test", mode_hint="conversational")

        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert errors[0].data["kind"] == "dependency_missing"
        assert not [e for e in events if e.type == "assistant_delta"]

    @pytest.mark.asyncio
    async def test_non_stream_dependency_error_emits_runtime_error(self) -> None:
        """Non-stream fallback path takzhe otdaet typed error event."""

        async def failing_llm(messages: list[dict], system_prompt: str) -> str:
            raise ThinLlmError(
                RuntimeErrorData(
                    kind="dependency_missing",
                    message="openai SDK не установлен. Установите: pip install cognitia[thin]",
                    recoverable=False,
                )
            )

        runtime = ThinRuntime(llm_call=failing_llm)
        events = await collect(runtime, "test", mode_hint="conversational")

        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert errors[0].data["kind"] == "dependency_missing"
        assert not [e for e in events if e.type == "assistant_delta"]


class TestThinRuntimeReactFallback:
    """React mode fallback pri sistematicheski notvalidnom JSON."""

    @pytest.mark.asyncio
    async def test_react_fallback_on_non_json_after_retries(self) -> None:
        """Posle limita retry runtime otdaet tekstovyy fallback vmesto error."""
        llm = MockLLM(
            [
                "Я думаю, вам подойдет вклад с капитализацией.",
                "Попробуйте вклад на 3 месяца без снятия.",
                "Итог: лучше рассмотреть 2-3 предложения банков.",
            ]
        )
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "подбери вклад", mode_hint="react")
        types = [e.type for e in events]
        assert "final" in types
        assert "error" not in types

        final = next(e for e in events if e.type == "final")
        assert "Итог" in final.data["text"] or "вклад" in final.data["text"]
