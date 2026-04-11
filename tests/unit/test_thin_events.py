"""Tests for ThinRuntime - order of events, pairing of tool events."""

from __future__ import annotations

import json

import pytest
from swarmline.runtime.thin.runtime import ThinRuntime
from swarmline.runtime.types import Message, RuntimeConfig, RuntimeEvent, ToolSpec


class MockLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def __call__(self, messages, system_prompt) -> str:
        if self._idx < len(self._responses):
            r = self._responses[self._idx]
            self._idx += 1
            return r
        return json.dumps({"type": "final", "final_message": "fallback"})


async def collect(runtime: ThinRuntime, mode_hint: str = "react") -> list[RuntimeEvent]:
    events = []
    async for ev in runtime.run(
        messages=[Message(role="user", content="test")],
        system_prompt="sys",
        active_tools=[ToolSpec(name="calc", description="c", parameters={})],
        mode_hint=mode_hint,
    ):
        events.append(ev)
    return events


class TestEventOrdering:
    """Order of events."""

    @pytest.mark.asyncio
    async def test_status_before_final(self) -> None:
        """status (mode) is always the first, final is the last."""
        llm = MockLLM([json.dumps({"type": "final", "final_message": "ok"})])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime)
        assert events[0].type == "status"  # Mode: react
        assert events[-1].type == "final"

    @pytest.mark.asyncio
    async def test_final_always_last(self) -> None:
        """final event - always the last one (not error)."""
        llm = MockLLM(
            [
                json.dumps({"type": "tool_call", "tool": {"name": "calc", "args": {}}}),
                json.dumps({"type": "final", "final_message": "done"}),
            ]
        )
        runtime = ThinRuntime(llm_call=llm, local_tools={"calc": lambda a: {"r": 1}})

        events = await collect(runtime)
        assert events[-1].type == "final"

    @pytest.mark.asyncio
    async def test_error_is_terminal(self) -> None:
        """error -> not events after (JSON-like response, fallback not triggered)."""
        # JSON-like response: fallback cuts it off, so it will be an error
        llm = MockLLM(["{broken}"] * 5)
        runtime = ThinRuntime(llm_call=llm)

        config = RuntimeConfig(runtime_name="thin", max_model_retries=1)
        events = []
        async for ev in runtime.run(
            messages=[Message(role="user", content="x")],
            system_prompt="s",
            active_tools=[],
            config=config,
            mode_hint="react",
        ):
            events.append(ev)

        # After error should not be final
        error_idx = next(i for i, e in enumerate(events) if e.type == "error")
        assert error_idx == len(events) - 1

    @pytest.mark.asyncio
    async def test_text_fallback_is_terminal(self) -> None:
        """Text fallback (not JSON) -> final, not error."""
        llm = MockLLM(["plain text answer"] * 5)
        runtime = ThinRuntime(llm_call=llm)

        config = RuntimeConfig(runtime_name="thin", max_model_retries=1)
        events = []
        async for ev in runtime.run(
            messages=[Message(role="user", content="x")],
            system_prompt="s",
            active_tools=[],
            config=config,
            mode_hint="react",
        ):
            events.append(ev)

        # Fallback: text, not error
        errors = [e for e in events if e.type == "error"]
        finals = [e for e in events if e.type == "final"]
        assert len(errors) == 0
        assert len(finals) == 1


class TestToolEventPairing:
    """tool_call_started is always paired with tool_call_finished."""

    @pytest.mark.asyncio
    async def test_paired_tool_events(self) -> None:
        """Each tool_call_started corresponds to a tool_call_finished."""
        llm = MockLLM(
            [
                json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {"name": "calc", "args": {}, "correlation_id": "c1"},
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {"name": "calc", "args": {}, "correlation_id": "c2"},
                    }
                ),
                json.dumps({"type": "final", "final_message": "done"}),
            ]
        )
        runtime = ThinRuntime(llm_call=llm, local_tools={"calc": lambda a: {"r": 1}})

        events = await collect(runtime)

        started = [e for e in events if e.type == "tool_call_started"]
        finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(started) == len(finished)

    @pytest.mark.asyncio
    async def test_tool_error_still_paired(self) -> None:
        """Tool error -> tool_call_finished with ok=False (pairing is preserved)."""

        def bad(args):
            raise RuntimeError("fail")

        llm = MockLLM(
            [
                json.dumps({"type": "tool_call", "tool": {"name": "bad", "args": {}}}),
                json.dumps({"type": "final", "final_message": "error handled"}),
            ]
        )
        runtime = ThinRuntime(llm_call=llm, local_tools={"bad": bad})

        events = await collect(runtime)

        started = [e for e in events if e.type == "tool_call_started"]
        finished = [e for e in events if e.type == "tool_call_finished"]
        assert len(started) == len(finished)
        assert finished[0].data["ok"] is False


class TestFinalContainsNewMessages:
    """final event contains new_messages."""

    @pytest.mark.asyncio
    async def test_final_has_new_messages(self) -> None:
        llm = MockLLM([json.dumps({"type": "final", "final_message": "ответ"})])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime)
        final = next(e for e in events if e.type == "final")

        assert "new_messages" in final.data
        assert len(final.data["new_messages"]) >= 1
        assert final.data["new_messages"][0]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_final_has_metrics(self) -> None:
        llm = MockLLM([json.dumps({"type": "final", "final_message": "x"})])
        runtime = ThinRuntime(llm_call=llm)

        events = await collect(runtime)
        final = next(e for e in events if e.type == "final")

        assert "metrics" in final.data
        assert "latency_ms" in final.data["metrics"]
