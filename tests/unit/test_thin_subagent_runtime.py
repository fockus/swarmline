"""TDD RED: Tests ThinSubagentOrchestrator with realnym ThinRuntime. CRP-2.1: Full implementation _create_runtime() - sozdaet per-worker ThinRuntime.
Kazhdyy test = biznots-fakt, not tehnicheskiy check.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.runtime.types import ToolSpec


def _make_llm_call(response_text: str):
    """Factory mock LLM call - returns fiksirovannyy JSON envelope."""

    async def _llm_call(messages: list[dict], system_prompt: str, **kwargs) -> str:
        envelope = {"type": "final", "final_message": response_text}
        return json.dumps(envelope)

    return _llm_call


def _make_slow_llm_call(delay: float, response_text: str = "done"):
    """LLM call with zaderzhkoy - for testov cancel and concurrency."""

    async def _llm_call(messages: list[dict], system_prompt: str, **kwargs) -> str:
        await asyncio.sleep(delay)
        envelope = {"type": "final", "final_message": response_text}
        return json.dumps(envelope)

    return _llm_call


def _make_error_llm_call(error_message: str):
    """LLM call kotoryy returns oshibku."""

    async def _llm_call(messages: list[dict], system_prompt: str, **kwargs) -> str:
        raise RuntimeError(error_message)

    return _llm_call


class TestThinSubagentSpawnAndComplete:
    """spawn worker → run ThinRuntime → get result."""

    async def test_thin_subagent_spawn_and_complete(self) -> None:
        """Worker runssya cherez ThinRuntime and returns result."""
        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call("task completed successfully"),
        )
        spec = SubagentSpec(name="researcher", system_prompt="You are a researcher.")
        agent_id = await orch.spawn(spec, "Research topic X")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert "task completed successfully" in result.output


class TestThinSubagentCancelRunning:
    """cancel mid-execution → status=cancelled."""

    async def test_thin_subagent_cancel_running(self) -> None:
        """Worker is cancelled vo vremya vypolnotniya."""
        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_slow_llm_call(delay=10.0),
        )
        spec = SubagentSpec(name="slow-worker", system_prompt="Work slowly.")
        agent_id = await orch.spawn(spec, "Long running task")

        await asyncio.sleep(0.05)
        await orch.cancel(agent_id)

        status = await orch.get_status(agent_id)
        assert status.state == "cancelled"


class TestThinSubagentMaxConcurrent:
    """max_concurrent=2 -> 3rd worker zhdet (ValueError)."""

    async def test_thin_subagent_max_concurrent_respected(self) -> None:
        """Exceeding max_concurrent brosaet ValueError."""
        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_slow_llm_call(delay=10.0),
        )
        spec = SubagentSpec(name="w", system_prompt="p")

        await orch.spawn(spec, "t1")
        await orch.spawn(spec, "t2")

        with pytest.raises(ValueError, match="max_concurrent"):
            await orch.spawn(spec, "t3")


class TestThinSubagentErrorPropagated:
    """LLM error -> status=failed, error message saved."""

    async def test_thin_subagent_error_propagated(self) -> None:
        """Error LLM probrasyvaetsya in status failed."""
        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_error_llm_call("API rate limit exceeded"),
        )
        spec = SubagentSpec(name="failing-worker", system_prompt="Try hard.")
        agent_id = await orch.spawn(spec, "Do something")
        result = await orch.wait(agent_id)

        assert result.status.state == "failed"
        assert result.status.error is not None
        assert "rate limit" in result.status.error.lower()


class TestThinSubagentToolsInherited:
    """Worker inherits tools from SubagentSpec."""

    async def test_thin_subagent_tools_inherited(self) -> None:
        """Tools from SubagentSpec are passed in ThinRuntime worker."""
        tool_was_called = False
        tool_name = "search_docs"

        async def search_executor(query: str) -> str:
            nonlocal tool_was_called
            tool_was_called = True
            return f"Found results for: {query}"

        tool_spec = ToolSpec(
            name=tool_name,
            description="Search documentation",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        )

        # LLM vyzyvaet tool (ActionEnvelope format), potom finaliziruet
        call_count = 0

        async def tool_calling_llm(messages: list[dict], system_prompt: str, **kwargs) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps({
                    "type": "tool_call",
                    "tool": {
                        "name": tool_name,
                        "args": {"query": "test query"},
                    },
                })
            return json.dumps({
                "type": "final",
                "final_message": "Search completed",
            })

        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=tool_calling_llm,
            local_tools={tool_name: search_executor},
        )
        spec = SubagentSpec(
            name="search-worker",
            system_prompt="You search docs.",
            tools=[tool_spec],
        )
        agent_id = await orch.spawn(spec, "Search for Python async patterns")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert tool_was_called, "Tool из spec должен был быть вызван worker'ом"
