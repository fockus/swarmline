"""TDD Red Phase: Token-Level Streaming for ThinRuntime (Etap 1.2). Tests verify:
- stream mode -> poluchaem N assistant_delta events (N > 1)
- tool_call_started/finished events pri streaming
- JSON envelope parsitsya from token stream
- Planner: per-step streaming
- Fallback on full response pri oshibke parsinga Contract: ThinRuntime._stream_llm_call(), stream_parser.py
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Mock streaming LLM
# ---------------------------------------------------------------------------


class MockStreamingLLM:
    """Mock LLM with podderzhkoy streaming (returns tokeny by odnomu). Pri stream=True returns AsyncIterator[str] (tokeny). Pri stream=False returns full response."""

    def __init__(
        self, token_chunks: list[list[str]], full_responses: list[str] | None = None
    ):
        """Args: token_chunks: Dlya kazhdogo vyzova - list token chunks. full_responses: Fallback full responsey (for non-stream mode)."""
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


class TestMessagesToLmToolTranscript:
    def test_messages_to_lm_preserves_persisted_native_tool_transcript(self) -> None:
        """Persisted assistant tool_calls + tool result become LLM-visible text."""
        from swarmline.runtime.thin.helpers import _messages_to_lm

        result = _messages_to_lm(
            [
                Message(role="user", content="calculate"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[{"id": "call-1", "name": "calc", "args": {"x": 2}}],
                ),
                Message(
                    role="tool",
                    content='{"value": 3}',
                    name="calc",
                    metadata={"correlation_id": "call-1"},
                ),
            ]
        )

        assert [message["role"] for message in result] == [
            "user",
            "assistant",
            "user",
        ]
        joined = "\n".join(message["content"] for message in result)
        assert "calc" in joined
        assert "call-1" in joined
        assert '{"value": 3}' in joined

    def test_messages_to_lm_preserves_json_tool_call_metadata(self) -> None:
        """JSON-in-text tool call metadata is not dropped after resume."""
        from swarmline.runtime.thin.helpers import _messages_to_lm

        result = _messages_to_lm(
            [
                Message(
                    role="assistant",
                    content="Вызываю lookup",
                    metadata={"tool_call": "lookup"},
                ),
                Message(role="tool", content="found", name="lookup"),
            ]
        )

        joined = "\n".join(message["content"] for message in result)
        assert "lookup" in joined
        assert "found" in joined


class TestIncrementalEnvelopeParser:
    """Incremental JSON envelope parsing from token stream (low-level)."""

    def test_thin_stream_json_envelope_parsed_incrementally(self) -> None:
        """JSON envelope collects from otdelnyh token chunks."""
        from swarmline.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()

        # Podaem JSON by chastyam
        chunks = ['{"type":', '"final",', '"final_message":', '"Hello world"}']

        for chunk in chunks[:-1]:
            result = parser.feed(chunk)
            assert result is None, (
                f"Не должно быть результата на промежуточном chunk: {chunk}"
            )

        result = parser.feed(chunks[-1])
        assert result is not None
        assert result["type"] == "final"
        assert result["final_message"] == "Hello world"

    def test_thin_stream_parser_handles_nested_json(self) -> None:
        """Parser obrabatyvaet vlozhennye JSON obekty."""
        from swarmline.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()

        # tool_call with vlozhennym args
        envelope = {
            "type": "tool_call",
            "tool": {"name": "read_file", "args": {"path": "/tmp/test.txt"}},
        }
        full_json = json.dumps(envelope)

        # Podaem by 10 simvolov
        for i in range(0, len(full_json), 10):
            chunk = full_json[i : i + 10]
            result = parser.feed(chunk)
            if i + 10 < len(full_json):
                assert result is None

        # Posledniy feed should vernut result
        if result is None:
            result = parser.feed("")
        assert result is not None
        assert result["type"] == "tool_call"

    def test_thin_stream_parser_fallback_on_invalid_json(self) -> None:
        """Pri notvalidnom JSON -> parser returns None, not crash."""
        from swarmline.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        result = parser.feed("this is not json at all")
        # Not crash, returns None (poka nott polnogo JSON)
        assert result is None

        # Finalizatsiya
        final = parser.finalize()
        assert final is None


class TestStreamParser:
    """High-level StreamParser - returns ActionEnvelope."""

    def test_stream_json_envelope_parsed_incrementally(self) -> None:
        """StreamParser sobiraet JSON and returns ActionEnvelope."""
        from swarmline.runtime.thin.stream_parser import StreamParser

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
        """Notfull JSON - parser eshche not zavershen."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        result = parser.feed('{"type": "final", "final_')
        assert not result
        assert not parser.has_result

    def test_stream_invalid_envelope_sets_error(self) -> None:
        """Validnyy JSON no invalid ActionEnvelope - error set."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        # type must match ^(tool_call|final|clarify)$
        done = parser.feed('{"type": "unknown_type_xxx", "bad_field": 123}')
        assert done
        assert parser.has_result
        assert parser.error is not None
        assert parser.result is None

    def test_stream_reset_clears_state(self) -> None:
        """reset() sbrasyvaet vse vnutrennie sostoyaniya."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        parser.feed('{"type": "final", "final_message": "Hi"}')
        assert parser.has_result
        parser.reset()
        assert not parser.has_result
        assert parser.buffer == ""
        assert parser.result is None
        assert parser.error is None

    def test_stream_markdown_fences_stripped(self) -> None:
        """JSON obernutyy in markdown fences parsitsya correctly."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        fenced = '```json\n{"type": "final", "final_message": "fenced"}\n```'
        done = parser.feed(fenced)
        assert done
        assert parser.result is not None
        assert parser.result.final_message == "fenced"


class TestSemanticStreamingDeltas:
    @pytest.mark.asyncio
    async def test_nested_final_message_in_tool_args_not_emitted_as_delta(self) -> None:
        """Only top-level final envelopes may emit final_message text deltas."""
        from swarmline.runtime.thin.llm_client import (
            StreamingLlmAttempt,
            stream_llm_call,
        )

        raw = json.dumps(
            {
                "type": "tool_call",
                "tool": {
                    "name": "capture",
                    "args": {"final_message": "leak"},
                    "correlation_id": "c1",
                },
            }
        )

        async def llm_call(
            messages: list[dict],
            system_prompt: str,
            *,
            stream: bool = False,
        ) -> AsyncIterator[str]:
            assert stream is True

            async def _stream() -> AsyncIterator[str]:
                for idx in range(0, len(raw), 7):
                    yield raw[idx : idx + 7]

            return _stream()

        deltas: list[str] = []
        attempt: StreamingLlmAttempt | None = None
        async for item in stream_llm_call(llm_call, [], "system"):
            if isinstance(item, RuntimeEvent):
                deltas.append(str(item.data["text"]))
            else:
                attempt = item

        assert deltas == []
        assert attempt is not None
        assert attempt.raw == raw


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestIncrementalEnvelopeParserEdgeCases:
    """Edge cases for IncrementalEnvelopeParser."""

    def test_thin_stream_parser_text_before_json_skipped(self) -> None:
        """Tekst pered JSON obektom is skipped."""
        from swarmline.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        result = parser.feed(
            'Some prefix text {"type": "final", "final_message": "ok"}'
        )
        assert result is not None
        assert result["type"] == "final"

    def test_thin_stream_parser_finalize_incomplete(self) -> None:
        """finalize() on notpolnom JSON -> None."""
        from swarmline.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        parser.feed('{"type": "final"')
        result = parser.finalize()
        assert result is None

    def test_thin_stream_parser_get_buffered_text(self) -> None:
        """get_buffered_text() returns nakoplennyy tekst."""
        from swarmline.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        parser.feed('{"partial":')
        text = parser.get_buffered_text()
        assert '{"partial":' in text

    def test_thin_stream_parser_escaped_quotes_in_string(self) -> None:
        r"""Escaped quotes (\") vnutri JSON strings obrabatyvayutsya."""
        from swarmline.runtime.thin.stream_parser import IncrementalEnvelopeParser

        parser = IncrementalEnvelopeParser()
        result = parser.feed('{"type": "final", "final_message": "say \\"hello\\""}')
        assert result is not None
        assert result["final_message"] == 'say "hello"'


class TestStreamParserEdgeCases:
    """Edge cases for StreamParser."""

    def test_stream_parser_json_with_escaped_strings(self) -> None:
        r"""JSON with escaped stringmi parsitsya correctly."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed('{"type": "final", "final_message": "path: C:\\\\Users"}')
        assert done
        assert parser.result is not None

    def test_stream_parser_empty_fenced_block(self) -> None:
        """Empty fenced block -> not zavershen."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed("```json\n```")
        assert not done

    def test_stream_parser_no_json_object(self) -> None:
        """Tekst without JSON obekta -> not zavershen."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed("just plain text without braces")
        assert not done

    def test_stream_parser_invalid_json_structure(self) -> None:
        """Skobki balansiruyutsya no content - not JSON."""
        from swarmline.runtime.thin.stream_parser import StreamParser

        parser = StreamParser()
        done = parser.feed("{not valid json content}")
        # Skobki sbalansirovany, no json.loads fail -> not complete
        assert not done or (done and parser.error is not None)


# ---------------------------------------------------------------------------
# Streaming mode tests
# ---------------------------------------------------------------------------


class TestThinRuntimeStreaming:
    """Token-level streaming cherez ThinRuntime."""

    @pytest.mark.asyncio
    async def test_thin_stream_emits_token_deltas(self) -> None:
        """Stream mode -> poluchaem N assistant_delta events (N > 1)."""
        final_text = "Привет! Как дела? Всё хорошо."
        # Razbivaem final response on token chunks
        final_json = _make_final_json(final_text)
        chunks = [final_json[i : i + 15] for i in range(0, len(final_json), 15)]

        llm = MockStreamingLLM(
            token_chunks=[chunks],
            full_responses=[_make_final_json(final_text)],
        )

        config = RuntimeConfig(runtime_name="thin")
        runtime = ThinRuntime(llm_call=llm, config=config)

        events = await collect_events(
            runtime, "Привет", mode_hint="conversational", config=config
        )

        deltas = [e for e in events if e.type == "assistant_delta"]
        # V streaming mode should byt bolshe 1 delta event
        assert len(deltas) > 1, f"Ожидается >1 assistant_delta, получено {len(deltas)}"
        assert "".join(str(e.data["text"]) for e in deltas) == final_text
        assert all("final_message" not in str(e.data["text"]) for e in deltas)
        assert all("{" not in str(e.data["text"]) for e in deltas)

        # Finalnyy event tozhe should byt
        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1

    @pytest.mark.asyncio
    async def test_thin_stream_react_tool_call_preserved(self) -> None:
        """tool_call_started/finished events are preserved pri streaming."""

        def calc(args: dict) -> dict:
            return {"result": 42}

        tool_call_json = _make_tool_call_json("calc", {"x": 1})
        final_json = _make_final_json("Результат: 42")

        llm = MockStreamingLLM(
            token_chunks=[
                list(tool_call_json),  # by simvolu
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
        """Planner mode: kazhdyy step strimit otdelno."""
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

        # Should byt delta events ot streaming otdelnyh stepov
        deltas = [e for e in events if e.type == "assistant_delta"]
        assert len(deltas) >= 2, "Каждый step плана должен стримить отдельно"

    @pytest.mark.asyncio
    async def test_thin_stream_react_emits_multiple_deltas_for_final(self) -> None:
        """React mode: final response strimitsya token-by-token (>1 delta)."""
        final_text = "Ответ из react mode: 42 + extras"
        final_json = _make_final_json(final_text)
        chunks = [final_json[i : i + 12] for i in range(0, len(final_json), 12)]

        llm = MockStreamingLLM(
            token_chunks=[chunks],
            full_responses=[final_json],
        )

        runtime = ThinRuntime(llm_call=llm)
        events = await collect_events(runtime, "Прямой ответ", mode_hint="react")

        deltas = [e for e in events if e.type == "assistant_delta"]
        assert len(deltas) > 1, (
            f"React mode должен стримить final response по chunk'ам, "
            f"получено {len(deltas)} delta events"
        )
        assert "".join(str(e.data["text"]) for e in deltas) == final_text
        assert all("final_message" not in str(e.data["text"]) for e in deltas)

        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert "42" in finals[0].data["text"]

    @pytest.mark.asyncio
    async def test_thin_stream_react_tool_then_streamed_final(self) -> None:
        """React mode: tool_call (non-stream) -> final (stream) -> multiple deltas."""

        def calc(args: dict) -> dict:
            return {"result": 99}

        tool_call_json = _make_tool_call_json("calc", {"x": 5})
        final_json = _make_final_json("Результат вычисления: 99")
        final_chunks = [final_json[i : i + 10] for i in range(0, len(final_json), 10)]

        llm = MockStreamingLLM(
            token_chunks=[
                list(tool_call_json),  # call 0: tool_call (stream chunks)
                final_chunks,  # call 1: final (stream chunks)
            ],
            full_responses=[tool_call_json, final_json],
        )

        runtime = ThinRuntime(llm_call=llm, local_tools={"calc": calc})
        events = await collect_events(runtime, "Посчитай 5", mode_hint="react")
        types = [e.type for e in events]

        # Tool events preserved
        assert "tool_call_started" in types
        assert "tool_call_finished" in types

        # Final response was streamed with multiple deltas
        final_idx = next(i for i, e in enumerate(events) if e.type == "final")
        deltas_before_final = [
            e for e in events[:final_idx] if e.type == "assistant_delta"
        ]
        assert len(deltas_before_final) > 1, (
            f"Final response в react mode должен стримиться после tool call, "
            f"получено {len(deltas_before_final)} delta events перед final"
        )

    @pytest.mark.asyncio
    async def test_thin_stream_react_fallback_on_stream_failure(self) -> None:
        """React mode: if streaming not supportssya -> fallback on non-streaming."""

        class NonStreamLLM:
            """LLM without podderzhki stream kwarg (TypeError pri stream=True)."""

            def __init__(self, responses: list[str]) -> None:
                self._responses = list(responses)
                self._idx = 0

            async def __call__(self, messages: list[dict], system_prompt: str) -> str:
                if self._idx < len(self._responses):
                    r = self._responses[self._idx]
                    self._idx += 1
                    return r
                return _make_final_json("fallback")

        llm = NonStreamLLM([_make_final_json("Non-stream react ответ")])
        runtime = ThinRuntime(llm_call=llm)
        events = await collect_events(runtime, "test", mode_hint="react")

        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert finals[0].data["text"] == "Non-stream react ответ"

        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_thin_stream_fallback_on_parse_error(self) -> None:
        """Pri oshibke parsinga streaming -> fallback on full response."""
        # Invalid chunks (corrupted stream)
        bad_chunks = ["corrupt", "ed str", "eam da", "ta!!!"]

        llm = MockStreamingLLM(
            token_chunks=[bad_chunks],
            full_responses=[_make_final_json("Fallback ответ")],
        )

        runtime = ThinRuntime(llm_call=llm)
        events = await collect_events(runtime, "test", mode_hint="conversational")

        # Should srabotat fallback - finalnyy response poluchen
        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        # Not should byt error (fallback, not crash)
        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 0
