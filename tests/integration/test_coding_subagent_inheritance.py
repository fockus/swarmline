"""Integration tests for coding subagent inheritance (Phase 10).

CSUB-01: Thin subagents inherit coding profile, tool surface, policy from parent.
CSUB-02: Task context propagation via coding_profile on orchestrator.
CSUB-03: Incompatible inheritance state fails fast (no silent downgrade).
CVAL-01: Non-coding thin runs remain behaviorally unchanged.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from swarmline.orchestration.subagent_types import SubagentSpec
from swarmline.orchestration.thin_subagent import ThinSubagentOrchestrator
from swarmline.policy.tool_policy import DefaultToolPolicy
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.coding_toolpack import CODING_TOOL_NAMES
from swarmline.runtime.types import RuntimeConfig, ToolSpec
from swarmline.tools.types import SandboxConfig


def _make_coding_policy() -> DefaultToolPolicy:
    """Build a coding-scoped policy allowing all CODING_TOOL_NAMES."""
    return DefaultToolPolicy(allowed_system_tools=set(CODING_TOOL_NAMES))


def _make_coding_profile() -> CodingProfileConfig:
    return CodingProfileConfig(enabled=True, allow_host_execution=True)


def _make_tool_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Test tool: {name}",
        parameters={"type": "object", "properties": {}},
        is_local=True,
    )


def _make_sandbox_config() -> SandboxConfig:
    return SandboxConfig(
        root_path="/tmp/test-subagent",
        user_id="test",
        topic_id="child",
    )


def _make_llm_call_returning(text: str) -> Any:
    """Create a fake llm_call that returns a canned response."""

    async def _fake_llm_call(
        messages: Any, system_prompt: str = "", **kwargs: Any,
    ) -> str:
        return text

    return _fake_llm_call


def _make_mock_thin_runtime() -> MagicMock:
    """Create a mock ThinRuntime class whose instances yield final events."""
    from swarmline.runtime.types import RuntimeEvent

    async def _mock_run(*args: Any, **kwargs: Any) -> Any:
        yield RuntimeEvent(type="final", data={"final_message": "child done"})

    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.run = _mock_run
    mock_cls.return_value = mock_instance
    return mock_cls


# ---------------------------------------------------------------------------
# CSUB-01: Inherit tool_policy and hook_registry (behavioral proof)
# ---------------------------------------------------------------------------


class TestCodingPolicyInheritedByChild:
    """CSUB-01: Child ThinRuntime receives parent's tool_policy via constructor."""

    @pytest.mark.asyncio
    async def test_tool_policy_reaches_thin_runtime_constructor(self) -> None:
        """tool_policy passed to orchestrator is forwarded to ThinRuntime kwargs."""
        tool_policy = _make_coding_policy()
        coding_profile = _make_coding_profile()

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
            coding_profile=coding_profile,
            tool_policy=tool_policy,
        )

        spec = SubagentSpec(
            name="child",
            system_prompt="test child",
            tools=[_make_tool_spec("read")],
            sandbox_config=_make_sandbox_config(),
        )

        mock_cls = _make_mock_thin_runtime()

        with patch("swarmline.orchestration.thin_subagent.ThinRuntime", mock_cls):
            worker = orchestrator._create_runtime(spec)
            await worker.run("test")

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args
        assert call_kwargs.kwargs.get("tool_policy") is tool_policy

    @pytest.mark.asyncio
    async def test_hook_registry_reaches_thin_runtime_constructor(self) -> None:
        """hook_registry passed to orchestrator is forwarded to ThinRuntime."""
        hook_registry = MagicMock()
        coding_profile = _make_coding_profile()

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
            coding_profile=coding_profile,
            hook_registry=hook_registry,
        )

        spec = SubagentSpec(
            name="child",
            system_prompt="test",
            tools=[],
            sandbox_config=_make_sandbox_config(),
        )

        mock_cls = _make_mock_thin_runtime()

        with patch("swarmline.orchestration.thin_subagent.ThinRuntime", mock_cls):
            worker = orchestrator._create_runtime(spec)
            await worker.run("test")

        call_kwargs = mock_cls.call_args
        assert call_kwargs.kwargs.get("hook_registry") is hook_registry

    @pytest.mark.asyncio
    async def test_child_policy_matches_parent_allowed_tools(self) -> None:
        """Child's tool_policy.allowed_system_tools includes coding tools."""
        custom_allowed = set(CODING_TOOL_NAMES) | {"web_fetch"}
        tool_policy = DefaultToolPolicy(allowed_system_tools=custom_allowed)
        coding_profile = _make_coding_profile()

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
            coding_profile=coding_profile,
            tool_policy=tool_policy,
        )

        spec = SubagentSpec(
            name="child", system_prompt="test", tools=[],
            sandbox_config=_make_sandbox_config(),
        )

        mock_cls = _make_mock_thin_runtime()

        with patch("swarmline.orchestration.thin_subagent.ThinRuntime", mock_cls):
            worker = orchestrator._create_runtime(spec)
            await worker.run("test")

        passed_policy = mock_cls.call_args.kwargs.get("tool_policy")
        assert passed_policy.allowed_system_tools == frozenset(custom_allowed)


# ---------------------------------------------------------------------------
# CSUB-02: Task context propagation (coding_profile drives validation)
# ---------------------------------------------------------------------------


class TestTaskContextPropagation:
    """CSUB-02: coding_profile on orchestrator drives child validation."""

    @pytest.mark.asyncio
    async def test_orchestrator_uses_coding_profile_for_validation(self) -> None:
        """Orchestrator uses coding_profile for fail-fast validation in _create_runtime."""
        coding_profile = _make_coding_profile()

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
            coding_profile=coding_profile,
        )

        # With sandbox → no error (validation passes)
        spec_ok = SubagentSpec(
            name="child", system_prompt="test", tools=[],
            sandbox_config=_make_sandbox_config(),
        )
        worker = orchestrator._create_runtime(spec_ok)
        assert worker is not None

        # Without sandbox → ValueError (validation catches it)
        spec_bad = SubagentSpec(
            name="child-bad", system_prompt="test", tools=[],
            sandbox_config=None,
        )
        with pytest.raises(ValueError, match="sandbox"):
            orchestrator._create_runtime(spec_bad)


# ---------------------------------------------------------------------------
# CSUB-03: Incompatible inheritance fails fast
# ---------------------------------------------------------------------------


class TestIncompatibleInheritanceFailsFast:
    """CSUB-03: Incompatible inheritance fails fast with ValueError."""

    @pytest.mark.asyncio
    async def test_incompatible_inheritance_state_fails_fast(self) -> None:
        """Parent has coding profile but child spec has no sandbox → ValueError."""
        coding_profile = CodingProfileConfig(enabled=True, allow_host_execution=True)

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
            coding_profile=coding_profile,
        )

        spec = SubagentSpec(
            name="child-no-sandbox",
            system_prompt="test",
            tools=[_make_tool_spec("read")],
            sandbox_config=None,
        )

        with pytest.raises(ValueError, match="sandbox"):
            orchestrator._create_runtime(spec)

    @pytest.mark.asyncio
    async def test_disabled_profile_does_not_require_sandbox(self) -> None:
        """coding_profile.enabled=False → no sandbox requirement."""
        coding_profile = CodingProfileConfig(enabled=False)

        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
            coding_profile=coding_profile,
        )

        spec = SubagentSpec(
            name="child", system_prompt="test", tools=[], sandbox_config=None,
        )

        worker = orchestrator._create_runtime(spec)
        assert worker is not None


# ---------------------------------------------------------------------------
# CVAL-01: Non-coding parent → child unchanged
# ---------------------------------------------------------------------------


class TestNonCodingParentDoesNotPassCodingProfile:
    """CVAL-01: Parent without coding profile → child also without."""

    @pytest.mark.asyncio
    async def test_non_coding_parent_child_gets_no_policy(self) -> None:
        """Orchestrator without coding params → ThinRuntime gets no tool_policy."""
        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=2,
            llm_call=_make_llm_call_returning("done"),
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        spec = SubagentSpec(name="child", system_prompt="test", tools=[])

        mock_cls = _make_mock_thin_runtime()

        with patch("swarmline.orchestration.thin_subagent.ThinRuntime", mock_cls):
            worker = orchestrator._create_runtime(spec)
            await worker.run("test")

        call_kwargs = mock_cls.call_args
        assert call_kwargs.kwargs.get("tool_policy") is None
        assert call_kwargs.kwargs.get("hook_registry") is None

    @pytest.mark.asyncio
    async def test_non_coding_orchestrator_backward_compatible(self) -> None:
        """Creating orchestrator without new kwargs works as before."""
        orchestrator = ThinSubagentOrchestrator(
            max_concurrent=4,
            llm_call=_make_llm_call_returning("done"),
        )

        assert orchestrator._coding_profile is None
        assert orchestrator._tool_policy is None
        assert orchestrator._hook_registry is None
