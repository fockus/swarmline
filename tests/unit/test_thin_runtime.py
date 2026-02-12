"""Тесты для ThinRuntime — react loop: tool_call → final (mock LLM)."""

from __future__ import annotations

import json

import pytest

from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import Message, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Mock LLM — возвращает заранее заданные ответы
# ---------------------------------------------------------------------------

class MockLLM:
    """Mock LLM: возвращает ответы из очереди."""

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
# Хелперы
# ---------------------------------------------------------------------------

async def collect(runtime: ThinRuntime, text: str = "test", tools: list[ToolSpec] | None = None,
                  mode_hint: str | None = None) -> list[RuntimeEvent]:
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
    return json.dumps({
        "type": "tool_call",
        "tool": {"name": name, "args": args or {}, "correlation_id": cid},
        "assistant_message": "",
    })


def make_final_response(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


def make_clarify_response(questions: list[dict], msg: str = "") -> str:
    return json.dumps({
        "type": "clarify",
        "questions": questions,
        "assistant_message": msg,
    })


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

        llm = MockLLM([
            make_tool_call_response("calc", {"x": 1}),
            make_final_response("Результат: 42"),
        ])
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

        llm = MockLLM([
            make_tool_call_response("tool_a"),
            make_tool_call_response("tool_b"),
            make_final_response("Готово: a=1, b=2"),
        ])
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
        """LLM сразу возвращает final (без tool_call)."""
        llm = MockLLM([make_final_response("Простой ответ")])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "Что такое инфляция?", mode_hint="react")
        types = [e.type for e in events]
        assert "final" in types
        assert "tool_call_started" not in types

    @pytest.mark.asyncio
    async def test_clarify_response(self) -> None:
        """LLM возвращает clarify → final с вопросами."""
        llm = MockLLM([
            make_clarify_response(
                [{"id": "income", "text": "Какой доход?"}],
                msg="Уточните",
            ),
        ])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "Посчитай", mode_hint="react")
        final = next(e for e in events if e.type == "final")
        assert "Какой доход?" in final.data["text"]

    @pytest.mark.asyncio
    async def test_tool_execution_error(self) -> None:
        """Tool raises → tool_call_finished с ok=False, loop продолжается."""
        def bad_tool(args):
            raise ValueError("broken")

        llm = MockLLM([
            make_tool_call_response("bad_tool"),
            make_final_response("Не удалось"),
        ])
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
        """Плохой JSON → retry → успех."""
        llm = MockLLM([
            "это не JSON",
            make_final_response("Повторный ответ"),
        ])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "test", mode_hint="conversational")
        final = [e for e in events if e.type == "final"]
        assert len(final) == 1
        assert final[0].data["text"] == "Повторный ответ"

    @pytest.mark.asyncio
    async def test_parse_json_inside_wrapped_text(self) -> None:
        """Парсер умеет извлекать JSON из текста до/после блока."""
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


class TestThinRuntimeReactFallback:
    """React mode fallback при систематически невалидном JSON."""

    @pytest.mark.asyncio
    async def test_react_fallback_on_non_json_after_retries(self) -> None:
        """После лимита retry runtime отдает текстовый fallback вместо error."""
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
