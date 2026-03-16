"""TDD Red Phase: Token-Level Streaming для ThinRuntime (Этап 1.2).

Тесты проверяют:
- stream mode → получаем N assistant_delta events (N > 1)
- tool_call_started/finished events при streaming
- JSON envelope парсится из token stream
- Planner: per-step streaming
- Fallback на full response при ошибке парсинга

Contract: ThinRuntime._stream_llm_call(), stream_parser.py
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Mock streaming LLM
# ---------------------------------------------------------------------------


class MockStreamingLLM:
    """Mock LLM с поддержкой streaming (возвращает токены по одному).

    При stream=True возвращает AsyncIterator[str] (токены).
    При stream=False возвращает полный ответ.
    """

    def __init__(self, token_chunks: list[list[str]], full_responses: list[str] | None = None):
        """
        Args:
            token_chunks: Для каждого вызова — список token chunks.
            full_responses: Fallback полные ответы (для non-stream mode).
        """
        self._token_chunks = list(token_chunks)
        self._full_responses = list(full_responses or [])
        self._call_count = 0

    async def __call__(
        self,
        messages: list[dict],
        system_prompt: str,
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        idx = self._call_count
        self._call_count += 1

        if stream and idx < len(self._token_chunks):
            return self._make_stream(self._token_chunks[idx])

        if idx < len(self._full_responses):
            return self._full_responses[idx]

        return json.dumps({"type": "final", "final_message": "fallback"})

    @staticmethod
    async def _make_stream(chunks: list[str]) -> AsyncIterator[str]:
        for chunk in chunks:
            yield chunk


def _make_final_json(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


def _make_tool_call_json(name: str, args: dict | None = None) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": name, "args": args or {}, "correlation_id": "c1"},
            "assistant_message": "",
        }
    )


async def collect_events(
    runtime: ThinRuntime,
    text: str = "test",
    tools: list[ToolSpec] | None = None,
    mode_hint: str | None = None,
    config: RuntimeConfig | None = None,
) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="Test system prompt",
        active_tools=tools or [],
        mode_hint=mode_hint,
        config=config,
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Stream Parser tests
# ---------------------------------------------------------------------------


class TestIncrementalEnvelopeParser:
    """Incremental JSON envelope parsing из token stream (low-level)."""

    def test_thin_stream_json_envelope_parsed_incrementally(self) -> None:
        """JSON envelope собирается из отдельных token chunks."""
        from cognitia.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()

        # Подаём JSON по частям
        chunks = ['{"type":', '"final",', '"final_message":', '"Hello world"}']

        for chunk in chunks[:-1]:
            result = parser.feed(chunk)
            assert result is None, f"Не должно быть результата на промежуточном chunk: {chunk}"

        result = parser.feed(chunks[-1])
        assert result is not None
        assert result["type"] == "final"
        assert result["final_message"] == "Hello world"

    def test_thin_stream_parser_handles_nested_json(self) -> None:
        """Parser обрабатывает вложенные JSON объекты."""
        from cognitia.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()

        # tool_call с вложенным args
        envelope = {
            "type": "tool_call",
            "tool": {"name": "read_file", "args": {"path": "/tmp/test.txt"}},
        }
        full_json = json.dumps(envelope)

        # Подаём по 10 символов
        for i in range(0, len(full_json), 10):
            chunk = full_json[i : i + 10]
            result = parser.feed(chunk)
            if i + 10 < len(full_json):
                assert result is None

        # Последний feed должен вернуть результат
        if result is None:
            result = parser.feed("")
        assert result is not None
        assert result["type"] == "tool_call"

    def test_thin_stream_parser_fallback_on_invalid_json(self) -> None:
        """При невалидном JSON → parser возвращает None, не crash."""
        from cognitia.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        result = parser.feed("this is not json at all")
        # Не crash, возвращает None (пока нет полного JSON)
        assert result is None

        # Финализация
        final = parser.finalize()
        assert final is None


class TestStreamParser:
    """High-level StreamParser — возвращает ActionEnvelope."""

    def test_stream_json_envelope_parsed_incrementally(self) -> None:
        """StreamParser собирает JSON и возвращает ActionEnvelope."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        envelope_json = '{"type": "final", "final_message": "Hello world"}'
        # Feed char by char
        for ch in envelope_json:
            done = parser.feed(ch)
            if done:
                break
        assert parser.has_result
        assert parser.result is not None
        assert parser.result.type == "final"
        assert parser.result.final_message == "Hello world"

    def test_stream_partial_json_not_complete(self) -> None:
        """Неполный JSON — парсер ещё не завершён."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        result = parser.feed('{"type": "final", "final_')
        assert not result
        assert not parser.has_result

    def test_stream_invalid_envelope_sets_error(self) -> None:
        """Валидный JSON но невалидный ActionEnvelope — error set."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        # type must match ^(tool_call|final|clarify)$
        done = parser.feed('{"type": "unknown_type_xxx", "bad_field": 123}')
        assert done
        assert parser.has_result
        assert parser.error is not None
        assert parser.result is None

    def test_stream_reset_clears_state(self) -> None:
        """reset() сбрасывает все внутренние состояния."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        parser.feed('{"type": "final", "final_message": "Hi"}')
        assert parser.has_result
        parser.reset()
        assert not parser.has_result
        assert parser.buffer == ""
        assert parser.result is None
        assert parser.error is None

    def test_stream_markdown_fences_stripped(self) -> None:
        """JSON обёрнутый в markdown fences парсится корректно."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        fenced = '```json\n{"type": "final", "final_message": "fenced"}\n```'
        done = parser.feed(fenced)
        assert done
        assert parser.result is not None
        assert parser.result.final_message == "fenced"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestIncrementalEnvelopeParserEdgeCases:
    """Edge cases для IncrementalEnvelopeParser."""

    def test_thin_stream_parser_text_before_json_skipped(self) -> None:
        """Текст перед JSON объектом пропускается."""
        from cognitia.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        result = parser.feed('Some prefix text {"type": "final", "final_message": "ok"}')
        assert result is not None
        assert result["type"] == "final"

    def test_thin_stream_parser_finalize_incomplete(self) -> None:
        """finalize() на неполном JSON → None."""
        from cognitia.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        parser.feed('{"type": "final"')
        result = parser.finalize()
        assert result is None

    def test_thin_stream_parser_get_buffered_text(self) -> None:
        """get_buffered_text() возвращает накопленный текст."""
        from cognitia.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        parser.feed('{"partial":')
        text = parser.get_buffered_text()
        assert '{"partial":' in text

    def test_thin_stream_parser_escaped_quotes_in_string(self) -> None:
        r"""Escaped quotes (\") внутри JSON строки обрабатываются."""
        from cognitia.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        result = parser.feed('{"type": "final", "final_message": "say \\"hello\\""}')
        assert result is not None
        assert result["final_message"] == 'say "hello"'


class TestStreamParserEdgeCases:
    """Edge cases для StreamParser."""

    def test_stream_parser_json_with_escaped_strings(self) -> None:
        r"""JSON с escaped строками парсится корректно."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed('{"type": "final", "final_message": "path: C:\\\\Users"}')
        assert done
        assert parser.result is not None

    def test_stream_parser_empty_fenced_block(self) -> None:
        """Пустой fenced block → не завершён."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed("```json\n```")
        assert not done

    def test_stream_parser_no_json_object(self) -> None:
        """Текст без JSON объекта → не завершён."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed("just plain text without braces")
        assert not done

    def test_stream_parser_invalid_json_structure(self) -> None:
        """Скобки балансируются но содержимое — не JSON."""
        from cognitia.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed("{not valid json content}")
        # Скобки сбалансированы, но json.loads fail → не complete
        assert not done or (done and parser.error is not None)


# ---------------------------------------------------------------------------
# Streaming mode tests
# ---------------------------------------------------------------------------


class TestThinRuntimeStreaming:
    """Token-level streaming через ThinRuntime."""

    @pytest.mark.asyncio
    async def test_thin_stream_emits_token_deltas(self) -> None:
        """Stream mode → получаем N assistant_delta events (N > 1)."""
        # Разбиваем final response на token chunks
        final_json = _make_final_json("Привет! Как дела? Всё хорошо.")
        chunks = [final_json[i : i + 15] for i in range(0, len(final_json), 15)]

        llm = MockStreamingLLM(
            token_chunks=[chunks],
            full_responses=[_make_final_json("Привет! Как дела? Всё хорошо.")],
        )

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(llm_call=llm, config=config)

        events = await collect_events(
            runtime, "Привет", mode_hint="conversational", config=config
        )

        deltas = [e for e in events if e.type == "assistant_delta"]
        # В streaming mode должно быть больше 1 delta event
        assert len(deltas) > 1, f"Ожидается >1 assistant_delta, получено {len(deltas)}"

        # Финальный event тоже должен быть
        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1

    @pytest.mark.asyncio
    async def test_thin_stream_react_tool_call_preserved(self) -> None:
        """tool_call_started/finished events сохраняются при streaming."""

        def calc(args: dict) -> dict:
            return {"result": 42}

        tool_call_json = _make_tool_call_json("calc", {"x": 1})
        final_json = _make_final_json("Результат: 42")

        llm = MockStreamingLLM(
            token_chunks=[
                list(tool_call_json),  # по символу
                list(final_json),
            ],
            full_responses=[tool_call_json, final_json],
        )

        runtime = ThinRuntime(llm_call=llm, local_tools={"calc": calc})

        events = await collect_events(runtime, "Посчитай", mode_hint="react")
        types = [e.type for e in events]

        assert "tool_call_started" in types
        assert "tool_call_finished" in types
        assert "final" in types

    @pytest.mark.asyncio
    async def test_thin_stream_planner_per_step_streaming(self) -> None:
        """Planner mode: каждый step стримит отдельно."""
        plan_json = json.dumps(
            {
                "goal": "Test plan",
                "steps": [
                    {
                        "id": "s1",
                        "title": "Step 1",
                        "mode": "conversational",
                        "max_iterations": 1,
                    },
                    {
                        "id": "s2",
                        "title": "Step 2",
                        "mode": "conversational",
                        "max_iterations": 1,
                    },
                ],
                "final_format": "text",
            }
        )

        step1_final = _make_final_json("Result of step 1")
        step2_final = _make_final_json("Result of step 2")
        assembly_final = _make_final_json("Final assembled result")

        # token_chunks indexed by global call count:
        # call 0 = plan gen (non-stream), call 1 = step1 (stream), call 2 = step2 (stream)
        llm = MockStreamingLLM(
            token_chunks=[
                [],  # idx 0: plan generation (non-streaming, won't be used)
                [step1_final[i : i + 20] for i in range(0, len(step1_final), 20)],
                [step2_final[i : i + 20] for i in range(0, len(step2_final), 20)],
            ],
            full_responses=[plan_json, step1_final, step2_final, assembly_final],
        )

        runtime = ThinRuntime(llm_call=llm)
        events = await collect_events(runtime, "Сложная задача", mode_hint="planner")

        # Должны быть delta events от streaming отдельных шагов
        deltas = [e for e in events if e.type == "assistant_delta"]
        assert len(deltas) >= 2, "Каждый step плана должен стримить отдельно"

    @pytest.mark.asyncio
    async def test_thin_stream_fallback_on_parse_error(self) -> None:
        """При ошибке парсинга streaming → fallback на full response."""
        # Невалидные chunks (corrupted stream)
        bad_chunks = ["corrupt", "ed str", "eam da", "ta!!!"]

        llm = MockStreamingLLM(
            token_chunks=[bad_chunks],
            full_responses=[_make_final_json("Fallback ответ")],
        )

        runtime = ThinRuntime(llm_call=llm)
        events = await collect_events(runtime, "test", mode_hint="conversational")

        # Должен сработать fallback — финальный ответ получен
        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        # Не должно быть error (fallback, не crash)
        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 0
