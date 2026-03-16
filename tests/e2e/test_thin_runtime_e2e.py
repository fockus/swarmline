"""E2E: ThinRuntime — все 3 режима + CRP фичи.

Полный user journey: создание runtime → конфигурация → выполнение → результат.
Fake LLM через async callable (NOT mock.patch) — единственный mock (внешняя граница).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec
from cognitia.tools.types import ExecutionResult


# ---------------------------------------------------------------------------
# Helpers: Fake LLM + MockSandbox (DI, no monkeypatch)
# ---------------------------------------------------------------------------


def _final_envelope(text: str) -> str:
    """Сформировать JSON-ответ LLM в формате final envelope."""
    return json.dumps({"type": "final", "final_message": text})


def _tool_call_envelope(
    tool_name: str,
    args: dict[str, Any],
    *,
    correlation_id: str = "c1",
    assistant_message: str = "",
) -> str:
    """Сформировать JSON-ответ LLM в формате tool_call envelope."""
    return json.dumps(
        {
            "type": "tool_call",
            "tool": {"name": tool_name, "args": args, "correlation_id": correlation_id},
            "assistant_message": assistant_message,
        }
    )


def _plan_envelope(
    goal: str,
    steps: list[dict[str, Any]],
    final_format: str = "summary",
) -> str:
    """Сформировать JSON-ответ LLM в формате plan."""
    return json.dumps(
        {
            "type": "plan",
            "goal": goal,
            "steps": steps,
            "final_format": final_format,
        }
    )


class MockSandbox:
    """Fake SandboxProvider — in-memory файловая система для тестов."""

    def __init__(self) -> None:
        self._files: dict[str, str] = {}
        self._commands: list[str] = []

    async def read_file(self, path: str) -> str:
        if path in self._files:
            return self._files[path]
        raise FileNotFoundError(f"File not found: {path}")

    async def write_file(self, path: str, content: str) -> None:
        self._files[path] = content

    async def execute(self, command: str) -> ExecutionResult:
        self._commands.append(command)
        return ExecutionResult(stdout=f"executed: {command}", stderr="", exit_code=0, timed_out=False)

    async def list_dir(self, path: str = ".") -> list[str]:
        return list(self._files.keys())

    async def glob_files(self, pattern: str) -> list[str]:
        return [p for p in self._files.keys() if p.endswith(pattern.replace("*", ""))]


async def _collect_events(runtime: ThinRuntime, **run_kwargs: Any) -> list[RuntimeEvent]:
    """Собрать все RuntimeEvent из stream."""
    events: list[RuntimeEvent] = []
    async for event in runtime.run(**run_kwargs):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# 1. Conversational mode — full cycle
# ---------------------------------------------------------------------------


class TestThinConversationalE2E:
    """Conversational: single LLM call -> final."""

    @pytest.mark.asyncio
    async def test_thin_conversational_full_cycle(self) -> None:
        """Agent(runtime="thin") -> query("What is 2+2?") -> result.text contains answer.

        Fake LLM возвращает JSON envelope {"type": "final", "final_message": "4"}.
        """
        call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal call_count
            call_count += 1
            return _final_envelope("The answer is 4")

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=fake_llm,
        )

        events = await _collect_events(
            runtime,
            messages=[Message(role="user", content="What is 2+2?")],
            system_prompt="You are a math tutor",
            active_tools=[],
            mode_hint="conversational",
        )

        event_types = [e.type for e in events]
        assert "final" in event_types, "Conversational mode должен emit final event"
        assert "status" in event_types, "Должен emit status с названием режима"

        final = next(e for e in events if e.type == "final")
        assert "4" in final.data["text"], "Финальный текст должен содержать ответ"
        assert final.data["new_messages"], "Должны быть new_messages"
        assert call_count >= 1, "LLM должна быть вызвана хотя бы 1 раз"


# ---------------------------------------------------------------------------
# 2. React mode — tool call cycle
# ---------------------------------------------------------------------------


class TestThinReactE2E:
    """React: LLM -> tool_call -> execute -> LLM -> final."""

    @pytest.mark.asyncio
    async def test_thin_react_with_tool_call_cycle(self) -> None:
        """Agent + calculate tool -> LLM вызывает tool -> tool executes -> final.

        Проверяем полный цикл: tool_call_started, tool_call_finished, final.
        """
        tool_called = False
        call_sequence: list[str] = []

        async def calculate(args: dict[str, Any]) -> str:
            nonlocal tool_called
            tool_called = True
            a = args.get("a", 0)
            b = args.get("b", 0)
            return json.dumps({"result": a * b})

        llm_turn = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal llm_turn
            llm_turn += 1
            call_sequence.append(f"llm_call_{llm_turn}")
            if llm_turn == 1:
                # Первый вызов: LLM хочет вызвать tool
                return _tool_call_envelope("calculate", {"a": 15, "b": 23})
            # Второй вызов: получили результат, отдаём final
            return _final_envelope("15 * 23 = 345")

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin", max_iterations=6),
            llm_call=fake_llm,
            local_tools={"calculate": calculate},
        )

        calc_spec = ToolSpec(
            name="calculate",
            description="Multiply two numbers",
            parameters={"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
            is_local=True,
        )

        events = await _collect_events(
            runtime,
            messages=[Message(role="user", content="Calculate 15*23")],
            system_prompt="You are a calculator assistant",
            active_tools=[calc_spec],
            mode_hint="react",
        )

        event_types = [e.type for e in events]

        # Tool lifecycle events
        assert "tool_call_started" in event_types, "Должен emit tool_call_started"
        assert "tool_call_finished" in event_types, "Должен emit tool_call_finished"
        assert "final" in event_types, "Должен emit final"

        # Tool was actually called
        assert tool_called, "Tool calculate должен быть вызван"

        # Tool call details
        tc_started = next(e for e in events if e.type == "tool_call_started")
        assert tc_started.data["name"] == "calculate"

        tc_finished = next(e for e in events if e.type == "tool_call_finished")
        assert tc_finished.data["ok"] is True

        # Final answer
        final = next(e for e in events if e.type == "final")
        assert "345" in final.data["text"]

        # LLM was called at least twice (tool_call + final)
        assert llm_turn >= 2


# ---------------------------------------------------------------------------
# 3. Planner mode — multi-step cycle
# ---------------------------------------------------------------------------


class TestThinPlannerE2E:
    """Planner: plan -> step execution -> final assembly."""

    @pytest.mark.asyncio
    async def test_thin_planner_multi_step_cycle(self) -> None:
        """LLM возвращает PlanSchema с 2 шагами -> executes each -> assembly.

        Проверяем: result.text содержит результаты обоих шагов.
        """
        llm_call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal llm_call_count
            llm_call_count += 1

            # Вызов 1: LLM возвращает план
            if llm_call_count == 1:
                return _plan_envelope(
                    goal="Research and summarize",
                    steps=[
                        {
                            "id": "step1",
                            "title": "Research topic",
                            "mode": "conversational",
                            "tool_hints": [],
                            "success_criteria": [],
                            "max_iterations": 4,
                        },
                        {
                            "id": "step2",
                            "title": "Write summary",
                            "mode": "conversational",
                            "tool_hints": [],
                            "success_criteria": [],
                            "max_iterations": 4,
                        },
                    ],
                    final_format="concise summary",
                )

            # Вызов 2: шаг 1 (conversational) -> результат
            if llm_call_count == 2:
                return _final_envelope("AI research findings: transformers are powerful")

            # Вызов 3: шаг 2 (conversational) -> результат
            if llm_call_count == 3:
                return _final_envelope("Summary: AI uses transformer architecture")

            # Вызов 4: финальная сборка
            return _final_envelope(
                "Research: transformers are powerful. Summary: AI uses transformer architecture."
            )

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=fake_llm,
        )

        events = await _collect_events(
            runtime,
            messages=[Message(role="user", content="Research and summarize AI trends")],
            system_prompt="You are a researcher",
            active_tools=[],
            mode_hint="planner",
        )

        event_types = [e.type for e in events]
        assert "final" in event_types, "Planner должен emit final event"

        # Должны быть status events для шагов плана
        status_events = [e for e in events if e.type == "status"]
        assert len(status_events) >= 3, "Должны быть status events: режим + шаги + plan"

        # Финальный текст содержит оба результата
        final = next(e for e in events if e.type == "final")
        assert "transformer" in final.data["text"].lower(), "Финал содержит результаты шагов"

        # LLM была вызвана минимум 4 раза (план + 2 шага + сборка)
        assert llm_call_count >= 4


# ---------------------------------------------------------------------------
# 4. Builtin tools — доступны при наличии sandbox
# ---------------------------------------------------------------------------


class TestThinBuiltinToolsE2E:
    """Builtin tools доступны agent'у через sandbox."""

    @pytest.mark.asyncio
    async def test_thin_builtin_tools_available_in_agent(self) -> None:
        """Agent(runtime="thin", sandbox=MockSandbox) -> agent has builtin tools.

        Fake LLM calls read_file -> sandbox.read_file called -> result.
        """
        sandbox = MockSandbox()
        sandbox._files["hello.txt"] = "Hello, World!"
        llm_turn = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal llm_turn
            llm_turn += 1
            if llm_turn == 1:
                return _tool_call_envelope("read_file", {"path": "hello.txt"})
            return _final_envelope("File content: Hello, World!")

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=fake_llm,
            sandbox=sandbox,
        )

        # Builtin tools должны быть зарегистрированы как local_tools
        assert "read_file" in runtime._executor.local_tool_names

        events = await _collect_events(
            runtime,
            messages=[Message(role="user", content="Read hello.txt")],
            system_prompt="File reader",
            active_tools=[],
            mode_hint="react",
        )

        event_types = [e.type for e in events]
        assert "tool_call_started" in event_types
        assert "tool_call_finished" in event_types

        tc_finished = next(e for e in events if e.type == "tool_call_finished")
        assert tc_finished.data["ok"] is True
        assert "Hello, World" in tc_finished.data["result_summary"]

        final = next(e for e in events if e.type == "final")
        assert "Hello, World" in final.data["text"]


# ---------------------------------------------------------------------------
# 5. Streaming — token-level deltas
# ---------------------------------------------------------------------------


class TestThinStreamingE2E:
    """Streaming: ThinRuntime emit'ит assistant_delta events."""

    @pytest.mark.asyncio
    async def test_thin_streaming_token_level(self) -> None:
        """Agent.stream() -> collect events -> multiple assistant_delta events.

        Fake LLM поддерживает streaming (возвращает AsyncIterator).
        """

        async def fake_llm_streaming(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str | AsyncIterator[str]:
            if kwargs.get("stream"):
                # Возвращаем async iterator с несколькими chunks
                async def _gen() -> AsyncIterator[str]:
                    # Отправляем JSON частями
                    yield '{"type": "final",'
                    yield ' "final_message": "Token '
                    yield 'by token response"}'

                return _gen()
            return _final_envelope("Token by token response")

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=fake_llm_streaming,
        )

        events = await _collect_events(
            runtime,
            messages=[Message(role="user", content="Hi")],
            system_prompt="test",
            active_tools=[],
            mode_hint="conversational",
        )

        deltas = [e for e in events if e.type == "assistant_delta"]
        assert len(deltas) > 1, "Streaming должен emit более 1 assistant_delta"

        final = next(e for e in events if e.type == "final")
        assert "Token by token response" in final.data["text"]


# ---------------------------------------------------------------------------
# 6. Feature mode portable — no builtins
# ---------------------------------------------------------------------------


class TestThinFeatureModeE2E:
    """Feature mode portable: builtin tools отфильтровываются."""

    @pytest.mark.asyncio
    async def test_thin_feature_mode_portable_no_builtins(self) -> None:
        """Agent(feature_mode="portable", sandbox=MockSandbox) -> 0 builtin tools."""
        from cognitia.runtime.thin.builtin_tools import (
            filter_thin_builtins_by_mode,
            get_thin_builtin_specs,
        )

        sandbox = MockSandbox()
        specs = get_thin_builtin_specs(sandbox)

        # Без фильтра — есть builtin tools
        assert len(specs) > 0, "С sandbox должны быть builtin tools"

        # Portable mode — все builtins отфильтрованы
        portable_specs = filter_thin_builtins_by_mode(specs, feature_mode="portable")
        assert len(portable_specs) == 0, "Portable mode не включает builtins"

        # Hybrid mode — builtins сохранены
        hybrid_specs = filter_thin_builtins_by_mode(specs, feature_mode="hybrid")
        assert len(hybrid_specs) > 0, "Hybrid mode включает builtins"

    @pytest.mark.asyncio
    async def test_thin_no_sandbox_no_builtins(self) -> None:
        """Без sandbox — runtime работает без builtin tools."""

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            return _final_envelope("No tools needed")

        runtime = ThinRuntime(
            config=RuntimeConfig(runtime_name="thin"),
            llm_call=fake_llm,
            sandbox=None,
        )

        # Без sandbox — нет builtin executors
        assert len(runtime._executor.local_tool_names) == 0

        events = await _collect_events(
            runtime,
            messages=[Message(role="user", content="Hi")],
            system_prompt="test",
            active_tools=[],
            mode_hint="conversational",
        )

        final = next(e for e in events if e.type == "final")
        assert final.data["text"] == "No tools needed"
