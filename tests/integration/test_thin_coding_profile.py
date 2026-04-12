"""Integration: ThinRuntime with coding profile — CADG-01..05.

Tests verify that the coding profile opt-in correctly wires up:
- Coding tool specs into active_tools (visible surface)
- Coding tool executors into ToolExecutor (executable surface)
- Policy scoping allows coding tools, denies non-coding
- Default-deny behavior unchanged without coding profile
- Name parity between specs and executors from one builder
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarmline.agent.config import AgentConfig
from swarmline.agent.runtime_wiring import build_portable_runtime_plan
from swarmline.policy.tool_policy import (
    DefaultToolPolicy,
    PermissionAllow,
    PermissionDeny,
    ToolPolicyInput,
)
from swarmline.runtime.thin.coding_profile import CodingProfileConfig
from swarmline.runtime.thin.coding_toolpack import (
    CODING_SANDBOX_TOOL_NAMES,
    CODING_TOOL_NAMES,
    build_coding_toolpack,
)
from swarmline.tools.sandbox_local import LocalSandboxProvider
from swarmline.tools.types import SandboxConfig


def _make_sandbox(tmp_path: Path) -> LocalSandboxProvider:
    """Create real LocalSandboxProvider with workspace in tmp."""
    config = SandboxConfig(
        root_path=str(tmp_path),
        user_id="u1",
        topic_id="t1",
        allow_host_execution=True,
    )
    workspace = Path(config.workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)
    return LocalSandboxProvider(config)


def _make_state(local_tools: set[str] | None = None) -> ToolPolicyInput:
    return ToolPolicyInput(
        tool_name="",
        input_data={},
        active_skill_ids=[],
        allowed_local_tools=local_tools or set(),
    )


# ---------------------------------------------------------------------------
# CADG-02: name parity from one builder
# ---------------------------------------------------------------------------


class TestCodingToolPackIntegration:
    """Integration: coding tool pack from real sandbox."""

    def test_pack_names_match_sandbox_tools(self, tmp_path: Path) -> None:
        """All 8 coding tools created from real sandbox provider."""
        sandbox = _make_sandbox(tmp_path)
        pack = build_coding_toolpack(sandbox)

        assert pack.tool_names == CODING_SANDBOX_TOOL_NAMES
        assert set(pack.specs.keys()) == set(pack.executors.keys())

    @pytest.mark.asyncio
    async def test_read_executor_works(self, tmp_path: Path) -> None:
        """read executor can actually read a file."""
        sandbox = _make_sandbox(tmp_path)
        workspace = Path(sandbox._config.workspace_path)
        test_file = workspace / "test.txt"
        test_file.write_text("hello coding", encoding="utf-8")

        pack = build_coding_toolpack(sandbox)
        result = await pack.executors["read"]({"path": "test.txt"})
        parsed = json.loads(result)

        assert parsed["status"] == "ok"
        assert "hello coding" in parsed["content"]

    @pytest.mark.asyncio
    async def test_write_executor_works(self, tmp_path: Path) -> None:
        """write executor can create a file."""
        sandbox = _make_sandbox(tmp_path)
        pack = build_coding_toolpack(sandbox)

        result = await pack.executors["write"]({"path": "out.txt", "content": "written"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    @pytest.mark.asyncio
    async def test_bash_executor_works(self, tmp_path: Path) -> None:
        """bash executor can run a command."""
        sandbox = _make_sandbox(tmp_path)
        pack = build_coding_toolpack(sandbox)

        result = await pack.executors["bash"]({"command": "echo hello"})
        parsed = json.loads(result)
        assert "hello" in parsed.get("stdout", "")


# ---------------------------------------------------------------------------
# CADG-05: policy scope integration
# ---------------------------------------------------------------------------


class TestCodingPolicyScopeIntegration:
    """Integration: coding policy from wiring correctly scopes tool access."""

    @pytest.mark.parametrize("tool_name", sorted(CODING_TOOL_NAMES))
    def test_wired_policy_allows_coding_tool(self, tool_name: str) -> None:
        """Policy from coding profile wiring allows each coding tool."""
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        policy = plan.create_kwargs["tool_policy"]

        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionAllow), (
            f"{tool_name} should be allowed"
        )

    @pytest.mark.parametrize(
        "tool_name",
        ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    )
    def test_wired_policy_denies_pascal_case_tool(self, tool_name: str) -> None:
        """PascalCase SDK names not in coding set are still denied."""
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        policy = plan.create_kwargs["tool_policy"]

        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionDeny), (
            f"PascalCase {tool_name} should still be denied"
        )

    def test_wired_policy_denies_arbitrary_tools(self) -> None:
        """Unknown tools are denied by coding profile policy."""
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")
        policy = plan.create_kwargs["tool_policy"]

        result = policy.can_use_tool("malicious_tool", {}, _make_state())
        assert isinstance(result, PermissionDeny)


# ---------------------------------------------------------------------------
# CADG-04: default-deny safety preserved without coding profile
# ---------------------------------------------------------------------------


class TestNonCodingAgentSafety:
    """Non-coding agents are not affected by coding profile changes."""

    def test_no_coding_profile_no_policy_injected(self) -> None:
        """Without coding profile, no tool_policy is auto-injected."""
        cfg = AgentConfig(
            system_prompt="chat assistant",
            runtime="thin",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        assert "tool_policy" not in plan.create_kwargs, (
            "No coding profile should not inject tool_policy"
        )

    @pytest.mark.parametrize("tool_name", sorted(CODING_TOOL_NAMES))
    def test_disabled_coding_profile_tool_absent(self, tool_name: str) -> None:
        """Disabled coding profile doesn't inject coding tools."""
        cfg = AgentConfig(
            system_prompt="chat assistant",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=False),
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        active_tool_names = {t.name for t in plan.active_tools}
        assert tool_name not in active_tool_names, (
            f"{tool_name} should NOT be in active_tools when profile disabled"
        )

    @pytest.mark.parametrize("tool_name", sorted(CODING_TOOL_NAMES))
    def test_no_coding_profile_tool_absent(self, tool_name: str) -> None:
        """Without coding profile and no user tools, coding tools absent."""
        cfg = AgentConfig(
            system_prompt="chat assistant",
            runtime="thin",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        active_tool_names = {t.name for t in plan.active_tools}
        assert tool_name not in active_tool_names


# ---------------------------------------------------------------------------
# CADG-01: opt-in coding profile flows end-to-end
# ---------------------------------------------------------------------------


class TestCodingProfileEndToEnd:
    """End-to-end: coding profile on AgentConfig → wiring → plan."""

    @pytest.mark.parametrize("tool_name", sorted(CODING_SANDBOX_TOOL_NAMES))
    def test_coding_profile_active_tool_present(self, tool_name: str) -> None:
        """active_tools in the plan include each sandbox coding tool spec."""
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        active_tool_names = {t.name for t in plan.active_tools}
        assert tool_name in active_tool_names

    @pytest.mark.parametrize("tool_name", sorted(CODING_SANDBOX_TOOL_NAMES))
    def test_coding_profile_executor_present(self, tool_name: str) -> None:
        """tool_executors in create_kwargs include each sandbox coding executor."""
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        executors = plan.create_kwargs.get("tool_executors", {})
        assert tool_name in executors, f"{tool_name} missing from executors"
        assert callable(executors[tool_name])

    def test_coding_profile_with_user_tools(self) -> None:
        """User tools + coding profile = both in active_tools."""
        from swarmline.agent.tool import ToolDefinition

        async def my_tool(args: dict) -> str:
            return "ok"

        user_tool = ToolDefinition(
            name="my_custom_tool",
            description="custom tool",
            parameters={},
            handler=my_tool,
        )
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            tools=(user_tool,),
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        active_tool_names = {t.name for t in plan.active_tools}
        assert "my_custom_tool" in active_tool_names
        for tool_name in CODING_SANDBOX_TOOL_NAMES:
            assert tool_name in active_tool_names

    @pytest.mark.parametrize("tool_name", sorted(CODING_TOOL_NAMES))
    def test_coding_profile_merged_policy_allows_coding_tool(
        self, tool_name: str,
    ) -> None:
        """Explicit tool_policy + coding profile = merged policy allows coding tool."""
        explicit_policy = DefaultToolPolicy(
            allowed_system_tools={"web_fetch", "web_search"},
        )
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            tool_policy=explicit_policy,
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        policy = plan.create_kwargs["tool_policy"]
        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionAllow)

    @pytest.mark.parametrize("tool_name", ["web_fetch", "web_search"])
    def test_coding_profile_merged_policy_preserves_explicit_tools(
        self, tool_name: str,
    ) -> None:
        """Explicit tool_policy tools still allowed after merge with coding profile."""
        explicit_policy = DefaultToolPolicy(
            allowed_system_tools={"web_fetch", "web_search"},
        )
        cfg = AgentConfig(
            system_prompt="code assistant",
            runtime="thin",
            tool_policy=explicit_policy,
            coding_profile=CodingProfileConfig(enabled=True),
            cwd="/tmp/test-coding",
        )
        plan = build_portable_runtime_plan(cfg, "thin")

        policy = plan.create_kwargs["tool_policy"]
        result = policy.can_use_tool(tool_name, {}, _make_state())
        assert isinstance(result, PermissionAllow)
