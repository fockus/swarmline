"""Тесты DeepAgentsSubagentOrchestrator и ClaudeSubagentOrchestrator — TDD."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from cognitia.orchestration.subagent_types import SubagentSpec
from cognitia.runtime.types import RuntimeErrorData, RuntimeEvent


class TestDeepAgentsSubagentOrchestrator:
    async def test_spawn_and_wait(self) -> None:
        from cognitia.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

        class FakeRuntime:
            async def run(self, **kwargs) -> AsyncIterator[RuntimeEvent]:
                _ = kwargs
                yield RuntimeEvent.assistant_delta("deepagent ")
                yield RuntimeEvent.final("deepagent result")

        orch = DeepAgentsSubagentOrchestrator(
            max_concurrent=2,
            runtime_factory=lambda spec: FakeRuntime(),
        )

        spec = SubagentSpec(name="w", system_prompt="p")
        aid = await orch.spawn(spec, "task")
        result = await orch.wait(aid)
        assert result.output == "deepagent result"
        assert result.status.state == "completed"

    async def test_error_event_maps_to_failed_status(self) -> None:
        from cognitia.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

        class FakeRuntime:
            async def run(self, **kwargs) -> AsyncIterator[RuntimeEvent]:
                _ = kwargs
                yield RuntimeEvent.error(
                    RuntimeErrorData(kind="runtime_crash", message="boom", recoverable=False),
                )

        orch = DeepAgentsSubagentOrchestrator(
            runtime_factory=lambda spec: FakeRuntime(),
        )
        aid = await orch.spawn(SubagentSpec(name="w", system_prompt="p"), "task")
        result = await orch.wait(aid)
        assert result.status.state == "failed"
        assert "boom" in (result.status.error or "")

    async def test_cancel_maps_to_cancelled_status(self) -> None:
        from cognitia.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

        class SlowRuntime:
            async def run(self, **kwargs) -> AsyncIterator[RuntimeEvent]:
                _ = kwargs
                await asyncio.sleep(1)
                yield RuntimeEvent.final("done")

        orch = DeepAgentsSubagentOrchestrator(
            runtime_factory=lambda spec: SlowRuntime(),
        )
        aid = await orch.spawn(SubagentSpec(name="w", system_prompt="p"), "task")
        await asyncio.sleep(0.05)
        await orch.cancel(aid)
        result = await orch.wait(aid)
        assert result.status.state in ("cancelled", "failed")

    async def test_isinstance_protocol(self) -> None:
        from cognitia.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator
        from cognitia.orchestration.subagent_protocol import SubagentOrchestrator

        orch = DeepAgentsSubagentOrchestrator()
        assert isinstance(orch, SubagentOrchestrator)


class TestClaudeSubagentOrchestrator:
    async def test_spawn_and_wait(self) -> None:
        from cognitia.orchestration.claude_subagent import ClaudeSubagentOrchestrator

        class FakeAdapter:
            is_connected = False

            async def connect(self) -> None:
                self.is_connected = True

            async def disconnect(self) -> None:
                self.is_connected = False

            async def stream_reply(self, user_text: str):
                _ = user_text
                class Event:
                    type = "text_delta"
                    text = "claude result"
                    tool_name = ""
                    tool_result = ""
                    tool_input = None

                yield Event()

        orch = ClaudeSubagentOrchestrator(
            max_concurrent=2,
            adapter_factory=lambda spec: FakeAdapter(),
        )

        spec = SubagentSpec(name="w", system_prompt="p")
        aid = await orch.spawn(spec, "task")
        result = await orch.wait(aid)
        assert result.output == "claude result"

    async def test_error_event_maps_to_failed_status(self) -> None:
        from cognitia.orchestration.claude_subagent import ClaudeSubagentOrchestrator

        class FakeAdapter:
            is_connected = False

            async def connect(self) -> None:
                self.is_connected = True

            async def disconnect(self) -> None:
                self.is_connected = False

            async def stream_reply(self, user_text: str):
                _ = user_text
                class Event:
                    type = "error"
                    text = "sdk boom"
                    tool_name = ""
                    tool_result = ""
                    tool_input = None

                yield Event()

        orch = ClaudeSubagentOrchestrator(adapter_factory=lambda spec: FakeAdapter())
        aid = await orch.spawn(SubagentSpec(name="w", system_prompt="p"), "task")
        result = await orch.wait(aid)
        assert result.status.state == "failed"
        assert "sdk boom" in (result.status.error or "")

    async def test_isinstance_protocol(self) -> None:
        from cognitia.orchestration.claude_subagent import ClaudeSubagentOrchestrator
        from cognitia.orchestration.subagent_protocol import SubagentOrchestrator

        orch = ClaudeSubagentOrchestrator()
        assert isinstance(orch, SubagentOrchestrator)
