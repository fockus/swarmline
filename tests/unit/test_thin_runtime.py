"""Tests for ThinRuntime - react loop: tool_call -> final (mock LLM)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from swarmline.retry import ExponentialBackoff
from swarmline.runtime.thin.errors import ThinLlmError
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import (
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


def make_tool_call_response(
    name: str, args: dict | None = None, cid: str = "c1"
) -> str:
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
        """retry_policy should not add a second wrapper over buffered retry.

        The constructor may wrap user-provided llm_call with a thin config
        adapter, but must NOT add a retry wrapper -- retries are handled
        by ``run_buffered_llm_call`` at call time.
        """
        llm = MockLLM([make_final_response("Повторный ответ")])
        policy = ExponentialBackoff(max_retries=2, base_delay=0.0, jitter=False)
        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", retry_policy=policy),
            llm_call=llm,
        )

        # The stored callable is either the original or a thin config-adapter,
        # NOT a retry wrapper.  Verify by checking it's not doubly-wrapped
        # (no 'retry' in the closure name) and the call count stays at 1.
        assert llm._call_count == 0  # noqa: SLF001 - regression guard

        events = await collect(runtime, "test", mode_hint="conversational")
        final = next(e for e in events if e.type == "final")
        assert final.data["text"] == "Повторный ответ"
        # Only 1 call to the underlying LLM -- no extra retry wrapping
        assert llm._call_count == 1  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_conversational_streaming_without_postprocessing_keeps_eager_deltas(
        self,
    ) -> None:
        """Without guardrails/output_type/retry final_message text streams eagerly."""

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
        deltas = [
            event.data["text"] for event in events if event.type == "assistant_delta"
        ]
        final = next(event for event in events if event.type == "final")

        assert deltas == ["H", "e", "l", "l", "o"]
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
                message="google-genai SDK не установлен. Установите: pip install swarmline[thin]",
                recoverable=False,
            )
        )
        with patch(
            "swarmline.runtime.thin.llm_client.get_cached_adapter",
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
                    message="openai SDK не установлен. Установите: pip install swarmline[thin]",
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


# ---------------------------------------------------------------------------
# Per-call RuntimeConfig override (P1 bug fix)
# ---------------------------------------------------------------------------


class TestPerCallConfig:
    """Per-call RuntimeConfig should override constructor config for LLM calls."""

    @pytest.mark.asyncio
    async def test_per_call_config_uses_different_model(self) -> None:
        """Per-call config.model should be passed to the LLM call, not constructor model."""
        captured_configs: list[RuntimeConfig | None] = []

        async def capturing_llm_call(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            config: RuntimeConfig | None = None,
            **kwargs: Any,
        ) -> str:
            captured_configs.append(config)
            return json.dumps({"type": "final", "final_message": "response"})

        constructor_config = RuntimeConfig(runtime_name="thin", model="sonnet")
        override_config = RuntimeConfig(runtime_name="thin", model="opus")

        runtime = ThinRuntime(config=constructor_config, llm_call=capturing_llm_call)

        events: list[RuntimeEvent] = []
        async for ev in runtime.run(
            messages=[Message(role="user", content="test")],
            system_prompt="Test system prompt",
            active_tools=[],
            config=override_config,
            mode_hint="conversational",
        ):
            events.append(ev)

        assert any(e.type == "final" for e in events)
        # The LLM call must have received the override config
        assert len(captured_configs) >= 1
        assert captured_configs[0] is not None
        assert captured_configs[0].model == "opus"

    @pytest.mark.asyncio
    async def test_default_config_when_no_override(self) -> None:
        """Without per-call config, constructor config is used."""
        captured_configs: list[RuntimeConfig | None] = []

        async def capturing_llm_call(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            config: RuntimeConfig | None = None,
            **kwargs: Any,
        ) -> str:
            captured_configs.append(config)
            return json.dumps({"type": "final", "final_message": "response"})

        constructor_config = RuntimeConfig(runtime_name="thin", model="sonnet")
        runtime = ThinRuntime(config=constructor_config, llm_call=capturing_llm_call)

        events: list[RuntimeEvent] = []
        async for ev in runtime.run(
            messages=[Message(role="user", content="test")],
            system_prompt="Test system prompt",
            active_tools=[],
            mode_hint="conversational",
        ):
            events.append(ev)

        assert any(e.type == "final" for e in events)
        # Without override, config should be the constructor config
        assert len(captured_configs) >= 1
        assert captured_configs[0] is not None
        assert captured_configs[0].model == "sonnet"

    @pytest.mark.asyncio
    async def test_per_call_config_in_react_mode(self) -> None:
        """Per-call config override works in react mode too."""
        captured_configs: list[RuntimeConfig | None] = []

        async def capturing_llm_call(
            messages: list[dict[str, str]],
            system_prompt: str,
            *,
            config: RuntimeConfig | None = None,
            **kwargs: Any,
        ) -> str:
            captured_configs.append(config)
            return json.dumps({"type": "final", "final_message": "done"})

        constructor_config = RuntimeConfig(runtime_name="thin", model="sonnet")
        override_config = RuntimeConfig(runtime_name="thin", model="gpt-4o")

        runtime = ThinRuntime(config=constructor_config, llm_call=capturing_llm_call)

        events: list[RuntimeEvent] = []
        async for ev in runtime.run(
            messages=[Message(role="user", content="test")],
            system_prompt="Test",
            active_tools=[],
            config=override_config,
            mode_hint="react",
        ):
            events.append(ev)

        assert any(e.type == "final" for e in events)
        assert len(captured_configs) >= 1
        assert captured_configs[0] is not None
        assert captured_configs[0].model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_default_llm_call_receives_per_call_config(self) -> None:
        """When using _make_default_llm_call, per-call config should reach default_llm_call."""
        from unittest.mock import AsyncMock

        constructor_config = RuntimeConfig(runtime_name="thin", model="sonnet")
        override_config = RuntimeConfig(runtime_name="thin", model="opus")

        runtime = ThinRuntime(config=constructor_config)

        mock_default = AsyncMock(return_value="response text")
        with patch(
            "swarmline.runtime.thin.runtime.default_llm_call",
            mock_default,
        ):
            # Re-create the internal llm_call after patching
            runtime._llm_call = runtime._make_default_llm_call()  # noqa: SLF001

            events: list[RuntimeEvent] = []
            async for ev in runtime.run(
                messages=[Message(role="user", content="test")],
                system_prompt="Test",
                active_tools=[],
                config=override_config,
                mode_hint="conversational",
            ):
                events.append(ev)

        # default_llm_call should have been called with the override config
        assert mock_default.call_count >= 1
        first_call_config = mock_default.call_args_list[0][0][0]
        assert first_call_config.model == "opus"
