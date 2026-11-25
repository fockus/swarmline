"""Unit tests for TemporalAgentRuntime (client facade) and registry wiring.

Uses a duck-typed fake Temporal client/handle — no temporalio, no server.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from swarmline.domain_types import Message, ToolSpec
from swarmline.observability.event_bus import InMemoryEventBus
from swarmline.runtime.temporal.options import TemporalRuntimeOptions
from swarmline.runtime.temporal.payloads import AgentRunInput, AgentRunResult
from swarmline.runtime.temporal.runtime import TemporalAgentRuntime
from swarmline.runtime.temporal.stream import RunEventPublisher
from swarmline.runtime.types import RuntimeConfig


class FakeHandle:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.cancelled = False
        self.result_gate: asyncio.Event | None = None

    async def result(self) -> Any:
        if self.result_gate is not None:
            await self.result_gate.wait()
        if self._error is not None:
            raise self._error
        return self._result

    async def cancel(self) -> None:
        self.cancelled = True


class FakeClient:
    def __init__(self, handle: FakeHandle) -> None:
        self._handle = handle
        self.started: list[dict[str, Any]] = []
        self.attached: list[str] = []

    async def start_workflow(self, name: str, arg: Any, **kwargs: Any) -> FakeHandle:
        self.started.append({"name": name, "arg": arg, **kwargs})
        return self._handle

    def get_workflow_handle(self, workflow_id: str, **kwargs: Any) -> FakeHandle:
        self.attached.append(workflow_id)
        return self._handle


def _ok_result(**overrides: Any) -> AgentRunResult:
    defaults: dict[str, Any] = {
        "text": "done",
        "new_messages": [{"role": "assistant", "content": "done"}],
        "events": [
            {"id": "e1", "type": "assistant_delta", "data": {"text": "done"}},
        ],
        "iterations": 1,
        "tool_calls": 0,
        "status": "ok",
    }
    defaults.update(overrides)
    return AgentRunResult(**defaults)


async def _collect(runtime: TemporalAgentRuntime, **kwargs: Any) -> list[Any]:
    defaults: dict[str, Any] = {
        "messages": [Message(role="user", content="hi")],
        "system_prompt": "sys",
        "active_tools": [],
    }
    defaults.update(kwargs)
    return [event async for event in runtime.run(**defaults)]


class TestBufferedMode:
    async def test_replays_events_then_final(self) -> None:
        handle = FakeHandle(result=_ok_result())
        runtime = TemporalAgentRuntime(client=FakeClient(handle))

        events = await _collect(runtime)

        assert [e.type for e in events] == ["assistant_delta", "final"]
        assert events[-1].data["text"] == "done"
        # RuntimeEvent.final serializes new_messages to dicts
        assert events[-1].data["new_messages"][0]["content"] == "done"

    async def test_workflow_input_carries_run_parameters(self) -> None:
        handle = FakeHandle(result=_ok_result())
        client = FakeClient(handle)
        config = RuntimeConfig(
            runtime_name="temporal", model="m9", max_iterations=3, max_tool_calls=2
        )
        runtime = TemporalAgentRuntime(
            config,
            options=TemporalRuntimeOptions(task_queue="q1", workflow_id_prefix="p-"),
            client=client,
        )

        await _collect(
            runtime,
            active_tools=[ToolSpec(name="calc", description="d", parameters={})],
        )

        started = client.started[0]
        assert started["name"] == "SwarmlineAgentLoop"
        assert started["task_queue"] == "q1"
        assert started["id"].startswith("p-")
        inp = started["arg"]
        assert isinstance(inp, AgentRunInput)
        assert inp.model == "m9"
        assert inp.max_iterations == 3
        assert inp.max_tool_calls == 2
        assert inp.tools[0]["name"] == "calc"
        assert inp.messages == [{"role": "user", "content": "hi"}]

    async def test_error_result_maps_to_error_event(self) -> None:
        handle = FakeHandle(
            result=_ok_result(
                status="error",
                error_kind="loop_limit",
                error_message="Max iterations exceeded (6)",
                events=[],
            )
        )
        runtime = TemporalAgentRuntime(client=FakeClient(handle))

        events = await _collect(runtime)

        assert events[-1].type == "error"
        assert events[-1].data["kind"] == "loop_limit"

    async def test_workflow_failure_maps_to_runtime_crash(self) -> None:
        handle = FakeHandle(error=RuntimeError("worker exploded"))
        runtime = TemporalAgentRuntime(client=FakeClient(handle))

        events = await _collect(runtime)

        assert events[-1].type == "error"
        assert events[-1].data["kind"] == "runtime_crash"
        assert "worker exploded" in events[-1].data["message"]

    async def test_unknown_error_kind_falls_back_to_runtime_crash(self) -> None:
        handle = FakeHandle(
            result=_ok_result(status="error", error_kind="not_a_kind", events=[])
        )
        runtime = TemporalAgentRuntime(client=FakeClient(handle))

        events = await _collect(runtime)

        assert events[-1].data["kind"] == "runtime_crash"


class TestStreamingMode:
    async def test_streams_relay_events_then_final_without_replay(self) -> None:
        bus = InMemoryEventBus()
        handle = FakeHandle(result=_ok_result())
        handle.result_gate = asyncio.Event()
        runtime = TemporalAgentRuntime(
            options=TemporalRuntimeOptions(stream_events=True),
            client=FakeClient(handle),
            event_bus=bus,
        )

        collected: list[Any] = []

        async def consume() -> None:
            async for event in runtime.run(
                messages=[Message(role="user", content="hi")],
                system_prompt="sys",
                active_tools=[],
            ):
                collected.append(event)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        # Worker-side publisher streams an event while the workflow "runs"
        run_id = FakeClientRunId(runtime)
        await RunEventPublisher(bus).publish(
            run_id,
            [{"id": "s1", "type": "assistant_delta", "data": {"text": "chunk"}}],
        )
        await asyncio.sleep(0.05)
        handle.result_gate.set()
        await asyncio.wait_for(consumer, timeout=2)

        types = [e.type for e in collected]
        assert types == ["assistant_delta", "final"]
        assert collected[0].data["text"] == "chunk"
        # Buffered events from the result are NOT replayed in streaming mode
        assert sum(1 for e in collected if e.type == "assistant_delta") == 1


def FakeClientRunId(runtime: TemporalAgentRuntime) -> str:
    """Extract the run_id the facade generated (from the started workflow input)."""
    client = runtime._client
    assert client.started, "workflow was not started yet"
    return client.started[0]["arg"].run_id


class TestCancelAndLifecycle:
    async def test_cancel_requests_workflow_cancellation(self) -> None:
        bus_gate = asyncio.Event()
        handle = FakeHandle(result=_ok_result())
        handle.result_gate = bus_gate
        runtime = TemporalAgentRuntime(client=FakeClient(handle))

        async def consume() -> list[Any]:
            return await _collect(runtime)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        runtime.cancel()
        await asyncio.sleep(0.05)
        bus_gate.set()
        await asyncio.wait_for(consumer, timeout=2)

        assert handle.cancelled

    async def test_context_manager(self) -> None:
        runtime = TemporalAgentRuntime(client=FakeClient(FakeHandle()))
        async with runtime as rt:
            assert rt is runtime

    async def test_options_from_config_extra(self) -> None:
        config = RuntimeConfig(
            runtime_name="temporal",
            extra={"temporal": {"task_queue": "custom-q", "unknown_key": 1}},
        )
        runtime = TemporalAgentRuntime(config, client=FakeClient(FakeHandle()))
        assert runtime._options.task_queue == "custom-q"

    async def test_approval_timeout_forwarded_to_workflow_input(self) -> None:
        handle = FakeHandle(result=_ok_result())
        client = FakeClient(handle)
        runtime = TemporalAgentRuntime(
            options=TemporalRuntimeOptions(approval_timeout_seconds=120.0),
            client=client,
        )

        await _collect(runtime)

        assert client.started[0]["arg"].approval_timeout_seconds == 120.0

    async def test_scale_options_forwarded_to_workflow_input(self) -> None:
        handle = FakeHandle(result=_ok_result())
        client = FakeClient(handle)
        runtime = TemporalAgentRuntime(
            options=TemporalRuntimeOptions(
                use_reference_history=True, continue_as_new_after_iterations=25
            ),
            client=client,
        )

        await _collect(runtime)

        inp = client.started[0]["arg"]
        assert inp.use_reference_history
        assert inp.continue_after_iterations == 25


class TestAttach:
    async def test_attach_replays_buffered_run_by_run_id(self) -> None:
        handle = FakeHandle(result=_ok_result())
        client = FakeClient(handle)
        runtime = TemporalAgentRuntime(client=client)

        events = [event async for event in runtime.attach("r9")]

        assert client.attached == ["swarmline-agent-r9"]
        assert client.started == []  # no new workflow
        assert [e.type for e in events] == ["assistant_delta", "final"]
        assert events[-1].data["text"] == "done"

    async def test_attach_respects_workflow_id_prefix(self) -> None:
        handle = FakeHandle(result=_ok_result())
        client = FakeClient(handle)
        runtime = TemporalAgentRuntime(
            options=TemporalRuntimeOptions(workflow_id_prefix="prod-"),
            client=client,
        )

        _ = [event async for event in runtime.attach("r9")]

        assert client.attached == ["prod-r9"]

    async def test_attach_maps_workflow_failure_to_error_event(self) -> None:
        handle = FakeHandle(error=RuntimeError("gone"))
        runtime = TemporalAgentRuntime(client=FakeClient(handle))

        events = [event async for event in runtime.attach("r9")]

        assert events[-1].type == "error"
        assert events[-1].data["kind"] == "runtime_crash"


class TestRegistryWiring:
    def test_temporal_registered_with_capabilities(self) -> None:
        from swarmline.runtime.capabilities import get_runtime_capabilities
        from swarmline.runtime.registry import get_default_registry

        registry = get_default_registry()
        assert registry.is_registered("temporal")
        caps = get_runtime_capabilities("temporal")
        assert caps.tier == "full"
        assert caps.supports_interrupt
        assert caps.supports_resume  # reattach to a running workflow
        assert caps.supports_hitl  # durable approval signals

    def test_factory_rejects_client_side_tools(self) -> None:
        from swarmline.runtime.registry import _create_temporal

        with pytest.raises(ValueError, match="worker"):
            _create_temporal(
                RuntimeConfig(runtime_name="temporal"),
                local_tools={"x": lambda: None},
            )

    def test_agent_runtime_protocol_conformance(self) -> None:
        from swarmline.protocols.runtime import AgentRuntime

        runtime = TemporalAgentRuntime(client=FakeClient(FakeHandle()))
        assert isinstance(runtime, AgentRuntime)
