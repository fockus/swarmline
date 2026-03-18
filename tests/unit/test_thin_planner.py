"""Tests for ThinRuntime planner mode - plan -> step execution -> final."""

from __future__ import annotations

import json

import pytest
from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import Message, RuntimeEvent, ToolSpec

# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockLLM:
    """Mock LLM: returns answers from queues."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def __call__(self, messages, system_prompt) -> str:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return json.dumps({"type": "final", "final_message": "fallback"})


async def collect(
    runtime: ThinRuntime, text: str, tools: list[ToolSpec] | None = None
) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content=text)],
        system_prompt="system",
        active_tools=tools or [],
        mode_hint="planner",
    ):
        events.append(ev)
    return events


# ---------------------------------------------------------------------------
# Planner tests
# ---------------------------------------------------------------------------


class TestThinRuntimePlanner:
    """Planner-lite: plan → steps → final."""

    @pytest.mark.asyncio
    async def test_two_step_plan(self) -> None:
        """Plan with 2 steps: react + conversational -> final."""
        plan = json.dumps(
            {
                "type": "plan",
                "goal": "Оценить финансы",
                "steps": [
                    {"id": "s1", "title": "Считать", "mode": "conversational", "max_iterations": 2},
                    {
                        "id": "s2",
                        "title": "Рекомендации",
                        "mode": "conversational",
                        "max_iterations": 2,
                    },
                ],
                "final_format": "Оценка + рекомендации",
            }
        )

        step1_result = json.dumps({"type": "final", "final_message": "Шаг 1 готов"})
        step2_result = json.dumps({"type": "final", "final_message": "Шаг 2 готов"})
        final_assembly = json.dumps({"type": "final", "final_message": "Итого: всё хорошо"})

        llm = MockLLM([plan, step1_result, step2_result, final_assembly])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "Составь план финансов")
        types = [e.type for e in events]

        assert "status" in types  # mode + plan status
        status_texts = [str(e.data.get("text", "")) for e in events if e.type == "status"]
        assert any("Следующие шаги:" in text for text in status_texts)
        assert "final" in types

        final = next(e for e in events if e.type == "final")
        assert "Итого" in final.data["text"]

    @pytest.mark.asyncio
    async def test_plan_with_react_step(self) -> None:
        """Plan with react-step (tool_call inside step)."""
        plan = json.dumps(
            {
                "type": "plan",
                "goal": "Найти вклады",
                "steps": [
                    {"id": "s1", "title": "Поиск", "mode": "react", "max_iterations": 3},
                ],
                "final_format": "Список вкладов",
            }
        )

        # react step: tool_call -> final
        tool_call = json.dumps(
            {
                "type": "tool_call",
                "tool": {"name": "search", "args": {"q": "вклады"}, "correlation_id": "c1"},
            }
        )
        step_final = json.dumps({"type": "final", "final_message": "Найдено 3 вклада"})
        assembly = json.dumps({"type": "final", "final_message": "Вклады: A, B, C"})

        def search(args):
            return {"results": ["A", "B", "C"]}

        llm = MockLLM([plan, tool_call, step_final, assembly])
        runtime = ThinRuntime(llm_call=llm, local_tools={"search": search})

        events = await collect(
            runtime,
            "Составь план по вкладам",
            tools=[ToolSpec(name="search", description="s", parameters={})],
        )
        types = [e.type for e in events]

        assert "tool_call_started" in types
        assert "tool_call_finished" in types
        assert "final" in types

    @pytest.mark.asyncio
    async def test_bad_plan_json(self) -> None:
        """Notcorrect JSON plan -> error after retry."""
        llm = MockLLM(["not a plan", "still not a plan"])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "Составь план")
        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert errors[0].data["kind"] == "bad_model_output"

    @pytest.mark.asyncio
    async def test_plan_step_error_stops_plan(self) -> None:
        """Error in step -> plan ends with error."""
        plan = json.dumps(
            {
                "type": "plan",
                "goal": "Test",
                "steps": [
                    {"id": "s1", "title": "Bad step", "mode": "react", "max_iterations": 1},
                ],
                "final_format": "",
            }
        )

        # React step: 1 iteration -> loop_limit (max_iterations=1 and not final)
        llm = MockLLM(
            [
                plan,
                json.dumps({"type": "tool_call", "tool": {"name": "x", "args": {}}}),
                json.dumps({"type": "tool_call", "tool": {"name": "x", "args": {}}}),
            ]
        )
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime, "test plan")
        errors = [e for e in events if e.type == "error"]
        assert len(errors) >= 1
