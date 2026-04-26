"""Tests for ThinRuntime budgets - loop_limit, budget_exceeded."""

from __future__ import annotations

import json

import pytest
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


class MockLLM:
    """Mock LLM: vechnye tool_call for testirovaniya limitov."""

    def __init__(
        self, response: str | None = None, responses: list[str] | None = None
    ) -> None:
        self._response = response
        self._responses = responses or []
        self._idx = 0

    async def __call__(self, messages, system_prompt) -> str:
        if self._responses:
            if self._idx < len(self._responses):
                r = self._responses[self._idx]
                self._idx += 1
                return r
            return self._responses[-1]
        return self._response or ""


async def collect(
    runtime: ThinRuntime, config: RuntimeConfig | None = None
) -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="test")],
        system_prompt="sys",
        active_tools=[ToolSpec(name="calc", description="c", parameters={})],
        config=config,
        mode_hint="react",
    ):
        events.append(ev)
    return events


class TestLoopLimit:
    """max_iterations → loop_limit error."""

    @pytest.mark.asyncio
    async def test_loop_limit_reached(self) -> None:
        """Exceeding max_iterations -> RuntimeError(kind=loop_limit)."""
        # LLM vsegda returns tool_call - loop not zavershitsya
        tool_call = json.dumps(
            {
                "type": "tool_call",
                "tool": {"name": "calc", "args": {}, "correlation_id": "c1"},
            }
        )
        llm = MockLLM(response=tool_call)
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"calc": lambda args: {"r": 1}},
        )

        config = RuntimeConfig(
            runtime_name="thin", max_iterations=3, max_tool_calls=100
        )
        events = await collect(runtime, config)

        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert errors[0].data["kind"] == "loop_limit"
        assert "3" in errors[0].data["message"]

    @pytest.mark.asyncio
    async def test_loop_limit_default(self) -> None:
        """Default max_iterations=6."""
        tool_call = json.dumps(
            {
                "type": "tool_call",
                "tool": {"name": "calc", "args": {}},
            }
        )
        llm = MockLLM(response=tool_call)
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"calc": lambda args: {"r": 1}},
        )

        events = await collect(runtime)
        errors = [e for e in events if e.type == "error"]
        assert errors[0].data["kind"] == "loop_limit"
        assert "6" in errors[0].data["message"]


class TestBudgetExceeded:
    """max_tool_calls → budget_exceeded error."""

    @pytest.mark.asyncio
    async def test_tool_calls_budget_exceeded(self) -> None:
        """Exceeding max_tool_calls -> RuntimeError(kind=budget_exceeded)."""
        tool_call = json.dumps(
            {
                "type": "tool_call",
                "tool": {"name": "calc", "args": {}},
            }
        )
        llm = MockLLM(response=tool_call)
        runtime = ThinRuntime(
            llm_call=llm,
            local_tools={"calc": lambda args: {"r": 1}},
        )

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=20,  # vysokiy, chtoby not srabotal loop_limit
            max_tool_calls=2,  # nizkiy - sworks budget_exceeded
        )
        events = await collect(runtime, config)

        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert errors[0].data["kind"] == "budget_exceeded"
        assert "2" in errors[0].data["message"]


class TestBadModelOutput:
    """max_model_retries → bad_model_output error."""

    @pytest.mark.asyncio
    async def test_bad_json_retries_exceeded_with_fallback(self) -> None:
        """LLM returns tekst without JSON > max_model_retries -> text fallback (not error)."""
        llm = MockLLM(response="это не JSON вообще")
        runtime = ThinRuntime(llm_call=llm)

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_model_retries=2,
        )
        events = await collect(runtime, config)

        # Fallback: tekst uses kak response, a not kak error
        errors = [e for e in events if e.type == "error"]
        finals = [e for e in events if e.type == "final"]
        deltas = [e for e in events if e.type == "assistant_delta"]
        assert len(errors) == 0
        assert len(finals) == 1
        assert len(deltas) >= 1
        assert "это не JSON вообще" in deltas[0].data.get("text", "")

    @pytest.mark.asyncio
    async def test_bad_json_retries_exceeded_json_like_no_fallback(self) -> None:
        """LLM returns invalid JSON-podobnyy response -> error (fallback not srabatyvaet)."""
        llm = MockLLM(response="{broken json}")
        runtime = ThinRuntime(llm_call=llm)

        config = RuntimeConfig(
            runtime_name="thin",
            max_iterations=10,
            max_model_retries=2,
        )
        events = await collect(runtime, config)

        errors = [e for e in events if e.type == "error"]
        assert len(errors) == 1
        assert errors[0].data["kind"] == "bad_model_output"

    @pytest.mark.asyncio
    async def test_bad_json_then_recovery(self) -> None:
        """Bad JSON -> retry -> good JSON -> success."""
        responses = [
            "bad json",
            json.dumps({"type": "final", "final_message": "Восстановлено"}),
        ]
        llm = MockLLM(responses=responses)
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime)
        finals = [e for e in events if e.type == "final"]
        assert len(finals) == 1
        assert "Восстановлено" in finals[0].data["text"]
