"""Тесты DeepAgentsSubagentOrchestrator и ClaudeSubagentOrchestrator — TDD."""

from __future__ import annotations

from unittest.mock import AsyncMock

from cognitia.orchestration.subagent_types import SubagentSpec


class TestDeepAgentsSubagentOrchestrator:
    async def test_spawn_and_wait(self) -> None:
        from cognitia.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

        orch = DeepAgentsSubagentOrchestrator(max_concurrent=2)
        mock_rt = AsyncMock()
        mock_rt.run.return_value = "deepagent result"
        orch._create_runtime = lambda spec: mock_rt

        spec = SubagentSpec(name="w", system_prompt="p")
        aid = await orch.spawn(spec, "task")
        result = await orch.wait(aid)
        assert result.output == "deepagent result"
        assert result.status.state == "completed"

    async def test_isinstance_protocol(self) -> None:
        from cognitia.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator
        from cognitia.orchestration.subagent_protocol import SubagentOrchestrator

        orch = DeepAgentsSubagentOrchestrator()
        assert isinstance(orch, SubagentOrchestrator)


class TestClaudeSubagentOrchestrator:
    async def test_spawn_and_wait(self) -> None:
        from cognitia.orchestration.claude_subagent import ClaudeSubagentOrchestrator

        orch = ClaudeSubagentOrchestrator(max_concurrent=2)
        mock_rt = AsyncMock()
        mock_rt.run.return_value = "claude result"
        orch._create_runtime = lambda spec: mock_rt

        spec = SubagentSpec(name="w", system_prompt="p")
        aid = await orch.spawn(spec, "task")
        result = await orch.wait(aid)
        assert result.output == "claude result"

    async def test_isinstance_protocol(self) -> None:
        from cognitia.orchestration.claude_subagent import ClaudeSubagentOrchestrator
        from cognitia.orchestration.subagent_protocol import SubagentOrchestrator

        orch = ClaudeSubagentOrchestrator()
        assert isinstance(orch, SubagentOrchestrator)
