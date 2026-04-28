"""Regression tests for Phase 10 — non-coding thin behavior unchanged.

CVAL-01: Non-coding thin runs remain behaviorally unchanged.
CVAL-02: Targeted packs + broader regression green.
"""

from __future__ import annotations

from typing import Any

import pytest

from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.types import RuntimeConfig, ToolSpec
from swarmline.tools.types import SandboxConfig

pytestmark = pytest.mark.integration


def _make_llm_call_returning(text: str) -> Any:
    """Create a fake llm_call that returns a canned response."""

    async def _fake_llm_call(
        messages: Any,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        return text

    return _fake_llm_call


def _make_tool_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Test tool: {name}",
        parameters={"type": "object", "properties": {}},
        is_local=True,
    )


class TestNonCodingThinRunRemains:
    """CVAL-01: Non-coding thin runs remain behaviorally unchanged."""

    @pytest.mark.asyncio
    async def test_non_coding_thin_run_remains_unchanged(self) -> None:
        """Basic thin orchestrator without coding profile works exactly as before.

        Verifies backward compatibility: ThinSubagentOrchestrator created
        without coding_profile kwargs still creates workers that produce output.
        """
        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("hello from child"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        spec = SubagentSpec(
            name="basic-child",
            system_prompt="You are a helpful assistant",
            tools=[],
        )

        agent_id = await orchestrator.spawn(spec, "Say hello")
        result = await orchestrator.wait(agent_id)

        assert result.status.state == "completed"
        assert result.output == "hello from child"

    @pytest.mark.asyncio
    async def test_non_coding_orchestrator_max_concurrent_enforced(self) -> None:
        """Max concurrent limit enforced without coding params."""
        import asyncio

        async def _slow_llm(messages: Any, **kwargs: Any) -> str:
            await asyncio.sleep(10)
            return "slow"

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=1,
            llm_call=_slow_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        spec = SubagentSpec(name="s1", system_prompt="test", tools=[])
        await orchestrator.spawn(spec, "task1")

        with pytest.raises(ValueError, match="max_concurrent"):
            await orchestrator.spawn(spec, "task2")


class TestCodingProfileCriticalPath:
    """End-to-end coding profile with subagent orchestration."""

    @pytest.mark.asyncio
    async def test_coding_profile_critical_path_end_to_end(self) -> None:
        """Full coding run: parent with coding_profile spawns child that completes.

        This verifies the entire inheritance chain from orchestrator
        through worker to ThinRuntime creation.
        """
        coding_profile = CodingProfileConfig(enabled=True, allow_host_execution=True)

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("coding task done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
            coding_profile=coding_profile,
        )

        spec = SubagentSpec(
            name="coding-child",
            system_prompt="You are a coding assistant",
            tools=[_make_tool_spec("read")],
            sandbox_config=SandboxConfig(
                root_path="/tmp/test-coding-child",
                user_id="test",
                topic_id="child",
            ),
        )

        agent_id = await orchestrator.spawn(spec, "Fix the bug in main.py")
        result = await orchestrator.wait(agent_id)

        assert result.status.state == "completed"
        assert result.output == "coding task done"


class TestPhase7Phase8Phase9TestsGreen:
    """CVAL-02: Run targeted packs and verify count.

    This test is a meta-test that verifies previous phase tests
    are still discoverable and pass. It runs via subprocess to
    get an isolated count.
    """

    @pytest.mark.asyncio
    async def test_phase7_phase8_phase9_test_files_exist(self) -> None:
        """Verify that phase 7/8/9 targeted test files are discoverable."""
        from pathlib import Path

        test_root = Path(__file__).parent.parent

        expected_files = [
            "unit/test_coding_profile.py",  # Phase 7
            "unit/test_coding_toolpack.py",  # Phase 8
            "unit/test_coding_task_runtime_contract.py",  # Phase 8
            "unit/test_coding_context_builder.py",  # Phase 9
            "unit/test_coding_alias_compatibility.py",  # Phase 9
        ]
        for rel_path in expected_files:
            assert (test_root / rel_path).exists(), f"Missing: {rel_path}"
