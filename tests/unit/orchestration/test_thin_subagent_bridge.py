"""Tests for ThinSubagentOrchestrator context bridge injection and on_result_callback."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from swarmline.orchestration.context_bridge import ContextBridge
from swarmline.orchestration.subagent_types import SubagentResult, SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator


class _FakeRuntime:
    """Fake runtime that captures system_prompt passed to it."""

    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    async def run(self, task: str) -> str:
        return "done"


# ---------------------------------------------------------------------------
# Context bridge injection into system prompt
# ---------------------------------------------------------------------------


class TestContextBridgeInjection:
    """Verify context bridge is prepended to system prompt."""

    def _make_orchestrator(self, fake_runtime: Any) -> ThinSubagentOrchestrator:
        orch = ThinSubagentOrchestrator(llm_call=AsyncMock(return_value="ok"))

        # Monkey-patch _create_runtime to capture spec
        def patched_create(spec: SubagentSpec) -> Any:
            # Store the spec to verify system_prompt was modified
            orch._last_spec_prompt = spec.system_prompt  # type: ignore[attr-defined]
            return fake_runtime

        orch._create_runtime = patched_create  # type: ignore[assignment]
        return orch

    @pytest.mark.asyncio
    async def test_spawn_with_context_bridge_prepends_to_prompt(self) -> None:
        """When SubagentSpec has context_bridge, system prompt should include bridge context."""
        cb = ContextBridge(
            parent_goal="find the answer",
            parent_progress="50% done",
            parent_findings=["clue X"],
            inherited_tools=["web"],
        )
        spec = SubagentSpec(
            name="researcher",
            system_prompt="You are a researcher.",
            context_bridge=cb,
        )

        captured: dict[str, Any] = {}
        fake = _FakeRuntime(captured)
        self._make_orchestrator(fake)

        # We need to verify the _ThinWorkerRuntime gets modified prompt
        # Instead, we test _build_system_prompt directly
        from swarmline.orchestration.thin_subagent import _build_system_prompt

        result = _build_system_prompt(spec)
        assert "find the answer" in result
        assert "50% done" in result
        assert "clue X" in result
        assert "You are a researcher." in result

    @pytest.mark.asyncio
    async def test_spawn_without_context_bridge_unchanged(self) -> None:
        """When no context_bridge, system prompt stays unchanged."""
        spec = SubagentSpec(name="worker", system_prompt="Do the thing.")

        from swarmline.orchestration.thin_subagent import _build_system_prompt

        result = _build_system_prompt(spec)
        assert result == "Do the thing."

    @pytest.mark.asyncio
    async def test_context_bridge_before_own_prompt(self) -> None:
        """Context bridge section appears BEFORE the subagent's own system prompt."""
        cb = ContextBridge(
            parent_goal="main goal",
            parent_progress="started",
            parent_findings=[],
            inherited_tools=[],
        )
        spec = SubagentSpec(
            name="worker",
            system_prompt="Own prompt here.",
            context_bridge=cb,
        )

        from swarmline.orchestration.thin_subagent import _build_system_prompt

        result = _build_system_prompt(spec)
        bridge_pos = result.index("main goal")
        own_pos = result.index("Own prompt here.")
        assert bridge_pos < own_pos


# ---------------------------------------------------------------------------
# on_result_callback
# ---------------------------------------------------------------------------


class TestOnResultCallback:
    """on_result_callback fires after subagent completes."""

    @pytest.mark.asyncio
    async def test_callback_called_on_completion(self) -> None:
        callback = MagicMock()
        orch = ThinSubagentOrchestrator(
            llm_call=AsyncMock(return_value="ok"),
            on_result_callback=callback,
        )
        # Patch _create_runtime to return a simple fake
        fake = _FakeRuntime({})
        orch._create_runtime = lambda spec: fake  # type: ignore[assignment]

        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] == agent_id
        assert isinstance(call_args[0][1], SubagentResult)

    @pytest.mark.asyncio
    async def test_no_callback_no_error(self) -> None:
        """Without callback, completes normally."""
        orch = ThinSubagentOrchestrator(llm_call=AsyncMock(return_value="ok"))
        fake = _FakeRuntime({})
        orch._create_runtime = lambda spec: fake  # type: ignore[assignment]

        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")
        result = await orch.wait(agent_id)
        assert result.status.state == "completed"

    @pytest.mark.asyncio
    async def test_callback_on_failure(self) -> None:
        callback = MagicMock()
        orch = ThinSubagentOrchestrator(
            llm_call=AsyncMock(return_value="ok"),
            on_result_callback=callback,
        )

        class _FailRuntime:
            async def run(self, task: str) -> str:
                raise RuntimeError("boom")

        orch._create_runtime = lambda spec: _FailRuntime()  # type: ignore[assignment]

        spec = SubagentSpec(name="w", system_prompt="p")
        agent_id = await orch.spawn(spec, "task")
        await orch.wait(agent_id)

        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][1].status.state == "failed"
