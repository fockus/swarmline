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

        async def tool_calling_llm(
            messages: list[dict], system_prompt: str, **kwargs
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {
                            "name": tool_name,
                            "args": {"query": "test query"},
                        },
                    }
                )
            return json.dumps(
                {
                    "type": "final",
                    "final_message": "Search completed",
                }
            )

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


class TestThinSubagentCanUseTool:
    """The parent's can_use_tool callback must govern child worker tool calls
    too (I-098b regression fix): subagents were previously a side door around
    the permission gate -- a denied tool was silently inherited and executed
    unchecked in the child ThinRuntime."""

    async def test_parent_can_use_tool_denies_inherited_child_tool(self) -> None:
        """Callback denies 'danger' but allows everything else -> the child
        worker must NEVER execute 'danger', and the deny reaches the child's
        conversation (fed back into the next llm_call as a tool result)."""
        danger_called = False

        async def danger_tool(args: dict) -> dict:
            nonlocal danger_called
            danger_called = True
            return {"boom": True}

        async def gate(tool_name: str, tool_input: dict, context: object) -> object:
            if tool_name == "danger":
                return {"behavior": "deny", "message": "danger is not permitted"}
            return {"behavior": "allow"}

        call_count = 0
        second_call_messages: list = []

        async def tool_calling_llm(
            messages: list, system_prompt: str, **kwargs: object
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {"name": "danger", "args": {}},
                    }
                )
            second_call_messages.extend(messages)
            return json.dumps({"type": "final", "final_message": "done"})

        tool_spec = ToolSpec(
            name="danger",
            description="Dangerous tool",
            parameters={"type": "object", "properties": {}},
        )

        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=tool_calling_llm,
            local_tools={"danger": danger_tool},
            can_use_tool=gate,
        )
        spec = SubagentSpec(
            name="worker",
            system_prompt="You are a worker.",
            tools=[tool_spec],
        )
        agent_id = await orch.spawn(spec, "do something dangerous")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert not danger_called, "denied tool must NEVER execute in the child worker"
        combined = " ".join(str(getattr(m, "content", m)) for m in second_call_messages)
        assert "danger is not permitted" in combined

    async def test_parent_can_use_tool_allow_everything_child_executes_normally(
        self,
    ) -> None:
        """A permissive callback must not regress normal subagent tool
        execution (no callback wired = same behavior as before this fix)."""
        tool_called = False

        async def safe_tool(args: dict) -> dict:
            nonlocal tool_called
            tool_called = True
            return {"ok": True}

        async def allow_all(
            tool_name: str, tool_input: dict, context: object
        ) -> object:
            return {"behavior": "allow"}

        call_count = 0

        async def tool_calling_llm(
            messages: list, system_prompt: str, **kwargs: object
        ) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps(
                    {
                        "type": "tool_call",
                        "tool": {"name": "safe_tool", "args": {}},
                    }
                )
            return json.dumps({"type": "final", "final_message": "done"})

        tool_spec = ToolSpec(
            name="safe_tool",
            description="Safe tool",
            parameters={"type": "object", "properties": {}},
        )

        orch = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=tool_calling_llm,
            local_tools={"safe_tool": safe_tool},
            can_use_tool=allow_all,
        )
        spec = SubagentSpec(
            name="worker",
            system_prompt="You are a worker.",
            tools=[tool_spec],
        )
        agent_id = await orch.spawn(spec, "do something safe")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert tool_called, "allowed tool must execute normally in the child worker"


class TestThinSubagentCanUseToolRegistryPath:
    """Registry-worker path (SubagentSpec.runtime_name set): can_use_tool must
    reach the resolved factory the SAME (ungated) way tool_policy already
    does -- no new cross-runtime semantics invented, just consistency with
    the existing forwarding pattern."""

    async def test_registry_worker_receives_can_use_tool_in_kwargs(self) -> None:
        """A registered runtime factory sees can_use_tool in its kwargs,
        mirroring the existing (unconditional) tool_policy forwarding."""
        from swarmline.domain_types import RuntimeEvent
        from swarmline.runtime.registry import RuntimeRegistry
        from swarmline.runtime.types import RuntimeConfig

        captured_kwargs: list[dict] = []

        class _FakeRuntime:
            def run(self, **kwargs: object):
                async def _gen():
                    yield RuntimeEvent.final("registry worker done")

                return _gen()

        def factory(config: RuntimeConfig, **kwargs: object) -> _FakeRuntime:
            captured_kwargs.append(kwargs)
            return _FakeRuntime()

        registry = RuntimeRegistry()
        registry.register("fake_thin", factory)

        async def gate(tool_name: str, tool_input: dict, context: object) -> object:
            return {"behavior": "allow"}

        orch = ThinSubagentOrchestrator(
            registry=registry,
            max_concurrent=2,
            can_use_tool=gate,
        )
        spec = SubagentSpec(name="w", system_prompt="p", runtime_name="fake_thin")
        agent_id = await orch.spawn(spec, "task")
        result = await orch.wait(agent_id)

        assert result.status.state == "completed"
        assert captured_kwargs, "factory must have been called"
        assert captured_kwargs[0]["can_use_tool"] is gate
