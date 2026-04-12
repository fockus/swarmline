"""Tests for coding profile wiring — CADG-04, CADG-05.

RED phase: tests for runtime_wiring integration and policy scoping.
"""

from __future__ import annotations

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.policy.tool_policy import (
    ALWAYS_DENIED_TOOLS,
    DefaultToolPolicy,
    PermissionAllow,
    PermissionDeny,
    ToolPolicyInput,
)
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.coding_toolpack import CODING_SANDBOX_TOOL_NAMES, CODING_TOOL_NAMES


def _make_state(
    local_tools: set[str] | None = None,
) -> ToolPolicyInput:
    return ToolPolicyInput(
        tool_name="",
        input_data={},
        active_skill_ids=[],
        allowed_local_tools=local_tools or set(),
    )


# ---------------------------------------------------------------------------
# CADG-05: coding policy allows exactly the coding tool set
# ---------------------------------------------------------------------------


class TestCodingPolicyScope:
    """Policy with coding profile allows coding tools, denies others."""

    @pytest.mark.parametrize("tool_name", sorted(CODING_TOOL_NAMES))
    def test_coding_tool_allowed_by_policy(self, tool_name: str) -> None:
        """Policy with allowed_system_tools=CODING_TOOL_NAMES allows each coding tool."""
        policy = DefaultToolPolicy(allowed_system_tools=set(CODING_TOOL_NAMES))
        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionAllow), (
            f"Expected {tool_name} to be allowed, got {result}"
        )

    @pytest.mark.parametrize(
        "tool_name",
        ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    )
    def test_non_coding_pascal_case_tool_denied(self, tool_name: str) -> None:
        """PascalCase SDK tools NOT in CODING_TOOL_NAMES remain denied."""
        policy = DefaultToolPolicy(allowed_system_tools=set(CODING_TOOL_NAMES))
        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionDeny), (
            f"Expected {tool_name} to be denied, got {result}"
        )

    def test_coding_policy_fail_fast_on_unknown_tool(self) -> None:
        """Tools not in coding set or local tools are denied."""
        policy = DefaultToolPolicy(allowed_system_tools=set(CODING_TOOL_NAMES))

        result = policy.can_use_tool("dangerous_tool", {}, _make_state())
        assert isinstance(result, PermissionDeny)


# ---------------------------------------------------------------------------
# CADG-04: default-deny behavior unchanged without coding profile
# ---------------------------------------------------------------------------


class TestDefaultDenyUnchanged:
    """Without coding profile, default-deny behavior is preserved."""

    @pytest.mark.parametrize("tool_name", ["bash", "Bash", "read", "Read"])
    def test_tool_denied_without_coding_profile(self, tool_name: str) -> None:
        """bash/read and PascalCase variants denied without coding profile."""
        policy = DefaultToolPolicy()
        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionDeny)

    @pytest.mark.parametrize("tool_name", sorted(ALWAYS_DENIED_TOOLS))
    def test_always_denied_tool_still_denied(self, tool_name: str) -> None:
        """All ALWAYS_DENIED_TOOLS remain denied with no profile."""
        policy = DefaultToolPolicy()
        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionDeny), (
            f"Expected {tool_name} to be denied, got {result}"
        )


# ---------------------------------------------------------------------------
# CADG-01 wiring: coding_profile flows through runtime_wiring
# ---------------------------------------------------------------------------


class TestCodingProfileWiring:
    """coding_profile on AgentConfig flows into runtime_wiring create_kwargs."""

    @pytest.mark.parametrize("tool_name", sorted(CODING_TOOL_NAMES))
    def test_wiring_coding_tool_allowed_when_profile_enabled(
        self, tool_name: str,
    ) -> None:
        """build_portable_runtime_plan with coding_profile=enabled allows each coding tool."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        assert "tool_policy" in plan.create_kwargs
        policy = plan.create_kwargs["tool_policy"]
        assert isinstance(policy, DefaultToolPolicy)

        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionAllow), (
            f"Expected {tool_name} allowed via wiring, got {result}"
        )

    def test_wiring_no_coding_policy_when_profile_disabled(self) -> None:
        """build_portable_runtime_plan with coding_profile=disabled doesn't add coding policy."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=False),
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        assert "tool_policy" not in plan.create_kwargs, (
            "Disabled coding profile should not inject tool_policy"
        )

    def test_wiring_no_coding_policy_when_profile_none(self) -> None:
        """build_portable_runtime_plan without coding_profile preserves existing behavior."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        assert "tool_policy" not in plan.create_kwargs, (
            "No coding profile should not inject tool_policy"
        )

    @pytest.mark.parametrize("tool_name", sorted(CODING_TOOL_NAMES))
    def test_wiring_preserves_explicit_policy_with_coding_tool(
        self, tool_name: str,
    ) -> None:
        """Explicit tool_policy merged with coding_profile allows coding tool."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        explicit_policy = DefaultToolPolicy(
            allowed_system_tools={"web_fetch", "web_search"},
        )
        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            tool_policy=explicit_policy,
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        policy = plan.create_kwargs["tool_policy"]
        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionAllow), (
            f"Expected {tool_name} allowed, got {result}"
        )

    @pytest.mark.parametrize("tool_name", sorted(CODING_SANDBOX_TOOL_NAMES))
    def test_wiring_active_tools_include_coding_spec(self, tool_name: str) -> None:
        """active_tools in the plan include each sandbox coding tool spec when profile enabled."""
        from swarmline.agent.runtime_wiring import build_portable_runtime_plan

        cfg = AgentConfig(
            system_prompt="test",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        active_tool_names = {t.name for t in plan.active_tools}
        assert tool_name in active_tool_names, (
            f"Expected {tool_name} in active_tools, got {active_tool_names}"
        )
