"""Тесты ThinSubagentOrchestrator — TDD."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from cognitia.orchestration.subagent_types import SubagentSpec
from cognitia.runtime.types import ToolSpec


@pytest.fixture()
def orchestrator():
    from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator

    return ThinSubagentOrchestrator(max_concurrent=2)


class TestThinSubagentSpawn:
    async def test_spawn_returns_id(self, orchestrator) -> None:
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = "result"
        orchestrator._create_runtime = lambda spec: mock_runtime

        spec = SubagentSpec(name="worker", system_prompt="prompt")
        agent_id = await orchestrator.spawn(spec, "task text")
        assert isinstance(agent_id, str)
        assert len(agent_id) > 0

    async def test_spawn_and_wait(self, orchestrator) -> None:
        mock_runtime = AsyncMock()
        mock_runtime.run.return_value = "output text"
        orchestrator._create_runtime = lambda spec: mock_runtime

        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orchestrator.spawn(spec, "task")

        result = await orchestrator.wait(agent_id)
        assert result.output == "output text"
        assert result.status.state == "completed"

    async def test_list_active(self, orchestrator) -> None:
        mock_runtime = AsyncMock()

        # Задержка чтобы задача была active
        async def slow_run(*args, **kwargs):
            await asyncio.sleep(0.5)
            return "done"

        mock_runtime.run = slow_run
        orchestrator._create_runtime = lambda spec: mock_runtime

        spec = SubagentSpec(name="w", system_prompt="p")
        a1 = await orchestrator.spawn(spec, "t1")
        active = await orchestrator.list_active()
        assert a1 in active

    async def test_cancel(self, orchestrator) -> None:
        mock_runtime = AsyncMock()

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(10)
            return "done"

        mock_runtime.run = slow_run
        orchestrator._create_runtime = lambda spec: mock_runtime

        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orchestrator.spawn(spec, "t")
        # Ждём чтобы task стартовал
        await asyncio.sleep(0.05)
        await orchestrator.cancel(agent_id)

        status = await orchestrator.get_status(agent_id)
        # После cancel: cancelled или failed (из-за CancelledError)
        assert status.state in ("cancelled", "failed")

    async def test_max_concurrent(self, orchestrator) -> None:
        """Превышение max_concurrent → ValueError."""
        mock_runtime = AsyncMock()

        async def slow_run(*args, **kwargs):
            await asyncio.sleep(10)
            return "done"

        mock_runtime.run = slow_run
        orchestrator._create_runtime = lambda spec: mock_runtime

        spec = SubagentSpec(name="w", system_prompt="p")
        await orchestrator.spawn(spec, "t1")
        await orchestrator.spawn(spec, "t2")  # max=2

        with pytest.raises(ValueError, match="max_concurrent"):
            await orchestrator.spawn(spec, "t3")

    async def test_crash_does_not_affect_parent(self, orchestrator) -> None:
        """Subagent crash → status=failed, parent ok."""
        mock_runtime = AsyncMock()
        mock_runtime.run.side_effect = RuntimeError("crash!")
        orchestrator._create_runtime = lambda spec: mock_runtime

        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orchestrator.spawn(spec, "t")

        result = await orchestrator.wait(agent_id)
        assert result.status.state == "failed"
        assert "crash" in (result.status.error or "")


class TestThinSubagentFullImpl:
    """Tests for full _create_runtime with ThinRuntime backend."""

    async def test_thin_subagent_spawn_with_real_runtime(self) -> None:
        """spawn with real ThinRuntime (mock LLM) -> get result."""
        from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator

        async def mock_llm(messages: list, system_prompt: str, **kwargs: object) -> str:
            return json.dumps({"type": "final", "final_message": "worker result"})

        orch = ThinSubagentOrchestrator(max_concurrent=2, llm_call=mock_llm)

        spec = SubagentSpec(name="worker", system_prompt="You are a worker")
        agent_id = await orch.spawn(spec, "do task")
        result = await orch.wait(agent_id)
        assert result.status.state == "completed"
        assert "worker result" in result.output

    async def test_thin_subagent_error_propagated(self) -> None:
        """LLM error -> status=failed, error message propagated."""
        from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator

        async def mock_llm(messages: list, system_prompt: str, **kwargs: object) -> str:
            raise RuntimeError("LLM connection failed")

        orch = ThinSubagentOrchestrator(max_concurrent=2, llm_call=mock_llm)

        spec = SubagentSpec(name="worker", system_prompt="prompt")
        agent_id = await orch.spawn(spec, "task")
        result = await orch.wait(agent_id)
        assert result.status.state == "failed"
        assert result.status.error is not None

    async def test_thin_subagent_tools_inherited(self) -> None:
        """Worker inherits tools from SubagentSpec."""
        from cognitia.orchestration.thin_subagent import ThinSubagentOrchestrator

        received_tools: list[list[ToolSpec]] = []

        async def mock_llm(messages: list, system_prompt: str, **kwargs: object) -> str:
            return json.dumps({"type": "final", "final_message": "done"})

        orch = ThinSubagentOrchestrator(max_concurrent=2, llm_call=mock_llm)

        # Intercept _create_runtime to verify tools are passed
        original_create = orch._create_runtime

        def patched_create(spec: SubagentSpec) -> object:
            received_tools.append(list(spec.tools))
            return original_create(spec)

        orch._create_runtime = patched_create  # type: ignore[assignment]

        tools = [ToolSpec(name="my_tool", description="desc", parameters={})]
        spec = SubagentSpec(name="worker", system_prompt="prompt", tools=tools)
        agent_id = await orch.spawn(spec, "task")
        result = await orch.wait(agent_id)
        assert result.status.state == "completed"
        assert len(received_tools) == 1
        assert received_tools[0][0].name == "my_tool"
