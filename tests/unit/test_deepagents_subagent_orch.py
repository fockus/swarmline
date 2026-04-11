"""Tests DeepAgentsSubagentOrchestrator and ClaudeSubagentOrchestrator - TDD."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import patch

from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.runtime.types import RuntimeErrorData, RuntimeEvent, ToolSpec


class TestDeepAgentsSubagentOrchestrator:
    async def test_spawn_and_wait(self) -> None:
        from swarmline.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

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
        from swarmline.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

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
        from swarmline.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

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
        from swarmline.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator
        from swarmline.orchestration.subagent_protocol import SubagentOrchestrator

        orch = DeepAgentsSubagentOrchestrator()
        assert isinstance(orch, SubagentOrchestrator)

    async def test_default_runtime_passes_registered_local_tool_executors(self) -> None:
        from swarmline.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

        captured_tool_executors = {}

        class FakeRuntime:
            def __init__(self, *, config=None, tool_executors=None, mcp_servers=None) -> None:
                _ = (config, mcp_servers)
                captured_tool_executors.update(tool_executors or {})

            async def run(self, **kwargs) -> AsyncIterator[RuntimeEvent]:
                active_tools = kwargs["active_tools"]
                assert active_tools[0].name == "send_message"
                yield RuntimeEvent.final("deepagent result")

        orch = DeepAgentsSubagentOrchestrator()
        orch.register_tool("send_message", lambda args: args)

        spec = SubagentSpec(
            name="w",
            system_prompt="p",
            tools=[
                ToolSpec(
                    name="send_message",
                    description="message tool",
                    parameters={},
                    is_local=True,
                )
            ],
        )

        with patch("swarmline.orchestration.deepagents_subagent.DeepAgentsRuntime", FakeRuntime):
            aid = await orch.spawn(spec, "task")
            result = await orch.wait(aid)

        assert result.status.state == "completed"
        assert "send_message" in captured_tool_executors

    async def test_unregistered_local_tool_fails_before_runtime_execution(self) -> None:
        from swarmline.orchestration.deepagents_subagent import DeepAgentsSubagentOrchestrator

        runtime_run_called = False

        class FakeRuntime:
            def __init__(self, *, config=None, tool_executors=None, mcp_servers=None) -> None:
                _ = (config, tool_executors, mcp_servers)

            async def run(self, **kwargs) -> AsyncIterator[RuntimeEvent]:
                nonlocal runtime_run_called
                runtime_run_called = True
                _ = kwargs
                yield RuntimeEvent.final("deepagent result")

        orch = DeepAgentsSubagentOrchestrator()
        spec = SubagentSpec(
            name="w",
            system_prompt="p",
            tools=[
                ToolSpec(
                    name="send_message",
                    description="message tool",
                    parameters={},
                    is_local=True,
                )
            ],
        )

        with patch("swarmline.orchestration.deepagents_subagent.DeepAgentsRuntime", FakeRuntime):
            aid = await orch.spawn(spec, "task")
            result = await orch.wait(aid)

        assert result.status.state == "failed"
        assert "send_message" in (result.status.error or "")
        assert runtime_run_called is False


class TestClaudeSubagentOrchestrator:
    async def test_spawn_and_wait(self) -> None:
        from swarmline.orchestration.claude_subagent import ClaudeSubagentOrchestrator

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
        from swarmline.orchestration.claude_subagent import ClaudeSubagentOrchestrator

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
        from swarmline.orchestration.claude_subagent import ClaudeSubagentOrchestrator
        from swarmline.orchestration.subagent_protocol import SubagentOrchestrator

        orch = ClaudeSubagentOrchestrator()
        assert isinstance(orch, SubagentOrchestrator)
