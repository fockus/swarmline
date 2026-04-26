"""Tests for background agent execution — TDD.

Covers: RuntimeEvent.background_complete, SubagentSpec.run_in_background,
background orchestration (spawn, timeout, output buffering, completion events).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from swarmline.domain_types import RUNTIME_EVENT_TYPES, RuntimeEvent
from swarmline.orchestration.subagent_types import SubagentSpec


@pytest.fixture()
def mock_runtime() -> AsyncMock:
    """Mock runtime whose run() returns immediately."""
    rt = AsyncMock()
    rt.run = AsyncMock(return_value="bg result")
    rt._cwd = None
    return rt


def _make_orchestrator(
    mock_runtime: AsyncMock | None = None,
    on_background_complete: object = None,
    **kwargs: object,
) -> object:
    from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator

    defaults: dict[str, object] = {"max_concurrent": 10}
    defaults.update(kwargs)
    if on_background_complete is not None:
        defaults["on_background_complete"] = on_background_complete

    orch = ThinSubagentOrchestrator(**defaults)  # type: ignore[arg-type]
    if mock_runtime is not None:
        orch._create_runtime = lambda spec: mock_runtime  # type: ignore[assignment]
    return orch


# ---------------------------------------------------------------------------
# RuntimeEvent.background_complete static factory
# ---------------------------------------------------------------------------


class TestRuntimeEventBackgroundComplete:
    def test_background_complete_in_event_types(self) -> None:
        assert "background_complete" in RUNTIME_EVENT_TYPES

    def test_background_complete_factory_with_result(self) -> None:
        event = RuntimeEvent.background_complete(agent_id="agent-1", result="done")
        assert event.type == "background_complete"
        assert event.data["agent_id"] == "agent-1"
        assert event.data["result"] == "done"
        assert "error" not in event.data

    def test_background_complete_factory_with_error(self) -> None:
        event = RuntimeEvent.background_complete(
            agent_id="agent-2", error="timeout exceeded"
        )
        assert event.type == "background_complete"
        assert event.data["agent_id"] == "agent-2"
        assert event.data["error"] == "timeout exceeded"
        assert "result" not in event.data

    def test_background_complete_factory_with_both(self) -> None:
        event = RuntimeEvent.background_complete(
            agent_id="a", result="partial", error="warning"
        )
        assert event.data["agent_id"] == "a"
        assert event.data["result"] == "partial"
        assert event.data["error"] == "warning"


# ---------------------------------------------------------------------------
# SubagentSpec.run_in_background field
# ---------------------------------------------------------------------------


class TestSubagentSpecRunInBackground:
    def test_run_in_background_defaults_false(self) -> None:
        spec = SubagentSpec(name="w", system_prompt="p")
        assert spec.run_in_background is False

    def test_run_in_background_accepts_true(self) -> None:
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        assert spec.run_in_background is True


# ---------------------------------------------------------------------------
# Background spawn lifecycle
# ---------------------------------------------------------------------------


class TestBackgroundSpawn:
    async def test_spawn_background_returns_agent_id(
        self, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_runtime)
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        assert isinstance(agent_id, str)
        assert len(agent_id) > 0

    async def test_background_agent_completes_and_stores_result(
        self, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_runtime)
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        status = await orch.get_status(agent_id)  # type: ignore[union-attr]
        assert status.state == "completed"

    async def test_background_agent_emits_completion_event(
        self, mock_runtime: AsyncMock
    ) -> None:
        events: list[RuntimeEvent] = []

        async def capture(event: RuntimeEvent) -> None:
            events.append(event)

        orch = _make_orchestrator(mock_runtime, on_background_complete=capture)
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].type == "background_complete"
        assert events[0].data["agent_id"] == agent_id
        assert events[0].data["result"] == "bg result"

    async def test_background_agent_error_emits_event_with_error(
        self, mock_runtime: AsyncMock
    ) -> None:
        mock_runtime.run = AsyncMock(side_effect=RuntimeError("crash"))
        events: list[RuntimeEvent] = []

        async def capture(event: RuntimeEvent) -> None:
            events.append(event)

        orch = _make_orchestrator(mock_runtime, on_background_complete=capture)
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].data["error"] is not None

    async def test_background_agent_timeout_sets_failed_status(
        self, mock_runtime: AsyncMock
    ) -> None:
        async def slow_run(*_a: object, **_kw: object) -> str:
            await asyncio.sleep(10)
            return "done"

        mock_runtime.run = slow_run  # type: ignore[assignment]
        orch = _make_orchestrator(mock_runtime, background_timeout=0.1)
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]

        status = await orch.get_status(agent_id)  # type: ignore[union-attr]
        assert status.state == "failed"
        assert "timed out" in (status.error or "")


# ---------------------------------------------------------------------------
# Output buffering
# ---------------------------------------------------------------------------


class TestOutputBuffering:
    async def test_get_output_returns_accumulated_text(
        self, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_runtime)
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]
        await asyncio.sleep(0.05)

        output = orch.get_output(agent_id)  # type: ignore[union-attr]
        assert output == "bg result"

    async def test_get_output_empty_for_unknown_agent(self) -> None:
        orch = _make_orchestrator()
        assert orch.get_output("nonexistent") == ""  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Foreground unaffected
# ---------------------------------------------------------------------------


class TestForegroundUnaffected:
    async def test_foreground_agent_works_as_before(
        self, mock_runtime: AsyncMock
    ) -> None:
        orch = _make_orchestrator(mock_runtime)
        spec = SubagentSpec(name="w", system_prompt="p")  # run_in_background=False
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        result = await orch.wait(agent_id)  # type: ignore[union-attr]
        assert result.output == "bg result"
        assert result.status.state == "completed"

    async def test_no_callback_no_crash(self, mock_runtime: AsyncMock) -> None:
        """Background agent without on_background_complete callback runs fine."""
        orch = _make_orchestrator(mock_runtime)  # no callback
        spec = SubagentSpec(name="w", system_prompt="p", run_in_background=True)
        agent_id = await orch.spawn(spec, "task")  # type: ignore[union-attr]
        await orch.wait(agent_id)  # type: ignore[union-attr]
        await asyncio.sleep(0.05)

        status = await orch.get_status(agent_id)  # type: ignore[union-attr]
        assert status.state == "completed"
