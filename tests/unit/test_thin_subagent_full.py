"""TDD Red Phase: ThinSubagent full implementation (Etap 2.1). Tests verify:
- spawn worker -> get result (cherez ThinRuntime with llm_call)
- cancel mid-execution -> status=cancelled
- max_concurrent=2 -> 3rd raises ValueError
- LLM error -> status=failed, error message
- Worker inherits tools from spec Contract: ThinSubagentOrchestrator with llm_call -> per-worker ThinRuntime
"""

from __future__ import annotations

import asyncio
import json

import pytest
from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.runtime.types import ToolSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_final(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


class MockLLMForSubagent:
    """Mock LLM for subagent workers."""

    def __init__(self, response_text: str = "done", delay: float = 0.0) -> None:
        self._response_text = response_text
        self._delay = delay
        self.call_count = 0

    async def __call__(self, messages: list[dict], system_prompt: str) -> str:
        self.call_count += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        return _make_final(self._response_text)


class ErrorLLM:
    """Mock LLM kotoryy vsegda returns oshibku."""

    async def __call__(self, messages: list[dict], system_prompt: str) -> str:
        raise RuntimeError("LLM API connection failed")


class SlowLLM:
    """Mock LLM with zaderzhkoy (for cancel testov)."""

    async def __call__(self, messages: list[dict], system_prompt: str) -> str:
        await asyncio.sleep(10)
        return _make_final("slow result")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestThinSubagentEdgeCases:
    """Edge cases for ThinSubagentOrchestrator."""

    @pytest.mark.asyncio
    async def test_thin_subagent_get_status_unknown_agent(self) -> None:
        """get_status for notsushchestvuyushchego agent -> pending."""
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=MockLLMForSubagent())
        status = await orch.get_status("nonexistent-id")
        assert status.state == "pending"

    @pytest.mark.asyncio
    async def test_thin_subagent_wait_unknown_agent(self) -> None:
        """wait for notsushchestvuyushchego agent -> pending result."""
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=MockLLMForSubagent())
        result = await orch.wait("nonexistent-id")
        assert result.status.state == "pending"
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_thin_subagent_list_active_empty(self) -> None:
        """list_active pri otsutstvii workers -> empty list."""
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=MockLLMForSubagent())
        active = await orch.list_active()
        assert active == []

    @pytest.mark.asyncio
    async def test_thin_subagent_list_active_after_complete(self) -> None:
        """list_active posle zaversheniya worker -> empty list."""
        llm = MockLLMForSubagent(response_text="done")
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=llm)
        spec = SubagentSpec(name="worker", system_prompt="Work.")
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)
        active = await orch.list_active()
        assert agent_id not in active

    @pytest.mark.asyncio
    async def test_thin_subagent_cancel_nonexistent_noop(self) -> None:
        """cancel for notsushchestvuyushchego agent -> not crash."""
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=MockLLMForSubagent())
        await orch.cancel("nonexistent-id")  # Not should raise


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestThinSubagentFullImplementation:
    """ThinSubagent with realnym ThinRuntime cherez llm_call."""

    @pytest.mark.asyncio
    async def test_thin_subagent_spawn_and_complete(self) -> None:
        """Spawn worker cherez ThinRuntime -> get result."""
        llm = MockLLMForSubagent(response_text="Research complete: X is Y")
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=llm)

        spec = SubagentSpec(
            name="researcher",
            system_prompt="You are a researcher.",
        )

        agent_id = await orch.spawn(spec, "Find information about X")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert "Research complete" in result.output

    @pytest.mark.asyncio
    async def test_thin_subagent_cancel_running(self) -> None:
        """Cancel mid-execution → status=cancelled."""
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=SlowLLM())

        spec = SubagentSpec(
            name="slow_worker",
            system_prompt="Take your time.",
        )

        agent_id = await orch.spawn(spec, "Long running task")
        await asyncio.sleep(0.05)
        await orch.cancel(agent_id)

        status = await orch.get_status(agent_id)
        assert status.state in ("cancelled", "failed")

    @pytest.mark.asyncio
    async def test_thin_subagent_max_concurrent_respected(self) -> None:
        """max_concurrent=2 → 3rd spawn raises ValueError."""
        orch = ThinSubagentOrchestrator(max_concurrent=2, llm_call=SlowLLM())

        spec = SubagentSpec(name="worker", system_prompt="Do work.")

        await orch.spawn(spec, "task1")
        await orch.spawn(spec, "task2")

        with pytest.raises(ValueError, match="max_concurrent"):
            await orch.spawn(spec, "task3")

    @pytest.mark.asyncio
    async def test_thin_subagent_error_propagated(self) -> None:
        """LLM error -> status=failed, error message saved."""
        orch = ThinSubagentOrchestrator(max_concurrent=4, llm_call=ErrorLLM())

        spec = SubagentSpec(
            name="broken_worker",
            system_prompt="Will fail.",
        )

        agent_id = await orch.spawn(spec, "trigger error")
        result = await orch.wait(agent_id)

        assert result.status.state == "failed"
        assert result.status.error is not None
        assert "LLM API connection failed" in result.status.error

    @pytest.mark.asyncio
    async def test_thin_subagent_tools_inherited(self) -> None:
        """Worker inherits tools from SubagentSpec - tools are passed in runtime.run()."""
        tool_call_json = json.dumps({
            "type": "tool_call",
            "tool": {"name": "my_tool", "args": {"x": 1}, "correlation_id": "c1"},
            "assistant_message": "",
        })
        final_json = _make_final("Used tool successfully")

        call_idx = {"n": 0}

        async def llm_with_tool(messages: list[dict], system_prompt: str) -> str:
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                return tool_call_json
            return final_json

        def my_tool_executor(args: dict) -> dict:
            return {"result": args.get("x", 0) * 2}

        orch = ThinSubagentOrchestrator(
            max_concurrent=4,
            llm_call=llm_with_tool,
            local_tools={"my_tool": my_tool_executor},
        )

        tools = [
            ToolSpec(
                name="my_tool",
                description="Test tool",
                parameters={"type": "object"},
                is_local=True,
            ),
        ]

        spec = SubagentSpec(
            name="tool_worker",
            system_prompt="Use tools.",
            tools=tools,
        )

        agent_id = await orch.spawn(spec, "use my_tool")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert "Used tool successfully" in result.output
