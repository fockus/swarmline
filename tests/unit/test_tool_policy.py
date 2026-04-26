"""Tests for DefaultToolPolicy."""

import pytest
from swarmline.policy import (
    ALWAYS_DENIED_TOOLS,
    DefaultToolPolicy,
    PermissionAllow,
    PermissionDeny,
    ToolPolicyInput,
)


@pytest.fixture
def policy() -> DefaultToolPolicy:
    return DefaultToolPolicy()


def _make_state(
    active_skills: list[str] | None = None,
    local_tools: set[str] | None = None,
) -> ToolPolicyInput:
    return ToolPolicyInput(
        tool_name="",
        input_data={},
        active_skill_ids=active_skills or [],
        allowed_local_tools=local_tools or set(),
    )


class TestDenyList:
    """Tests on zapreshchennye tooly."""

    def test_bash_denied(self, policy: DefaultToolPolicy) -> None:
        """Bash vsegda zapreshchen."""
        result = policy.can_use_tool("Bash", {}, _make_state())
        assert isinstance(result, PermissionDeny)
        assert "Bash" in result.message

    def test_read_denied(self, policy: DefaultToolPolicy) -> None:
        """Read vsegda zapreshchen."""
        result = policy.can_use_tool("Read", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_write_denied(self, policy: DefaultToolPolicy) -> None:
        """Write vsegda zapreshchen."""
        result = policy.can_use_tool("Write", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_edit_denied(self, policy: DefaultToolPolicy) -> None:
        """Edit vsegda zapreshchen."""
        result = policy.can_use_tool("Edit", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_glob_denied(self, policy: DefaultToolPolicy) -> None:
        """Glob vsegda zapreshchen."""
        result = policy.can_use_tool("Glob", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_all_denied_tools_covered(self, policy: DefaultToolPolicy) -> None:
        """Vse tooly from ALWAYS_DENIED_TOOLS zapreshcheny."""
        for tool_name in ALWAYS_DENIED_TOOLS:
            result = policy.can_use_tool(tool_name, {}, _make_state())
            assert isinstance(result, PermissionDeny), (
                f"{tool_name} должен быть запрещён"
            )


class TestMcpTools:
    """Tests on MCP tooly."""

    def test_mcp_tool_allowed_when_skill_active(
        self, policy: DefaultToolPolicy
    ) -> None:
        """MCP tool razreshen, if server in aktivnyh skilah."""
        state = _make_state(active_skills=["iss"])
        result = policy.can_use_tool("mcp__iss__search_bonds", {}, state)
        assert isinstance(result, PermissionAllow)

    def test_mcp_tool_denied_when_skill_inactive(
        self, policy: DefaultToolPolicy
    ) -> None:
        """MCP tool zapreshchen, if server not in aktivnyh skilah."""
        state = _make_state(active_skills=["finuslugi"])
        result = policy.can_use_tool("mcp__iss__search_bonds", {}, state)
        assert isinstance(result, PermissionDeny)
        assert "iss" in result.message

    def test_mcp_tool_different_servers(self, policy: DefaultToolPolicy) -> None:
        """MCP tool ot finuslugi razreshen if finuslugi aktiven."""
        state = _make_state(active_skills=["finuslugi", "iss"])
        result = policy.can_use_tool("mcp__finuslugi__get_bank_deposits", {}, state)
        assert isinstance(result, PermissionAllow)


class TestLocalTools:
    """Tests on lokalnye tooly."""

    def test_local_tool_allowed(self, policy: DefaultToolPolicy) -> None:
        """Lokalnyy tool razreshen if in allowed_local_tools."""
        state = _make_state(local_tools={"mcp__freedom_tools__calculate_goal_plan"})
        result = policy.can_use_tool(
            "mcp__freedom_tools__calculate_goal_plan", {}, state
        )
        assert isinstance(result, PermissionAllow)

    def test_unknown_tool_denied(self, policy: DefaultToolPolicy) -> None:
        """Notizvestnyy tool zapreshchen."""
        state = _make_state()
        result = policy.can_use_tool("SomeRandomTool", {}, state)
        assert isinstance(result, PermissionDeny)


class TestAllowedSystemTools:
    """Tests on whitelist system tools (0.3.0-5)."""

    def test_bash_allowed_via_whitelist(self) -> None:
        """Bash razreshen if in allowed_system_tools."""
        policy = DefaultToolPolicy(allowed_system_tools={"Bash"})
        state = _make_state(local_tools={"Bash"})
        result = policy.can_use_tool("Bash", {}, state)
        assert isinstance(result, PermissionAllow)

    def test_read_write_allowed(self) -> None:
        """Read and Write razresheny cherez whitelist."""
        policy = DefaultToolPolicy(allowed_system_tools={"Read", "Write"})
        state = _make_state(local_tools={"Read", "Write"})

        assert isinstance(policy.can_use_tool("Read", {}, state), PermissionAllow)
        assert isinstance(policy.can_use_tool("Write", {}, state), PermissionAllow)

    def test_other_denied_tools_still_blocked(self) -> None:
        """Whitelist not vliyaet on drugie denied tools."""
        policy = DefaultToolPolicy(allowed_system_tools={"Bash"})
        state = _make_state()
        # Edit NE in whitelist - should byt zablokirovan
        result = policy.can_use_tool("Edit", {}, state)
        assert isinstance(result, PermissionDeny)

    def test_none_whitelist_backward_compat(self) -> None:
        """allowed_system_tools=None -> vse kak ranshe."""
        policy = DefaultToolPolicy(allowed_system_tools=None)
        state = _make_state()
        result = policy.can_use_tool("Bash", {}, state)
        assert isinstance(result, PermissionDeny)

    def test_empty_set_whitelist_backward_compat(self) -> None:
        """allowed_system_tools=set() -> vse kak ranshe."""
        policy = DefaultToolPolicy(allowed_system_tools=set())
        state = _make_state()
        result = policy.can_use_tool("Bash", {}, state)
        assert isinstance(result, PermissionDeny)

    def test_whitelist_with_extra_denied(self) -> None:
        """Whitelist + extra_denied - whitelist imeet prioritet."""
        policy = DefaultToolPolicy(
            allowed_system_tools={"Bash"},
            extra_denied={"CustomTool"},
        )
        state = _make_state(local_tools={"Bash"})
        # Bash razreshen cherez whitelist
        assert isinstance(policy.can_use_tool("Bash", {}, state), PermissionAllow)
        # CustomTool zapreshchen cherez extra_denied
        assert isinstance(policy.can_use_tool("CustomTool", {}, state), PermissionDeny)


class TestAgentLoggerIntegration:
    """GAP-4: AgentLogger.tool_policy_event() vyzyvaetsya in DefaultToolPolicy."""

    def test_logger_called_on_deny(self) -> None:
        """AgentLogger.tool_policy_event vyzyvaetsya pri deny (GAP-4)."""
        from unittest.mock import MagicMock

        mock_logger = MagicMock()
        policy = DefaultToolPolicy(agent_logger=mock_logger)
        state = _make_state()

        policy.can_use_tool("Bash", {}, state)

        mock_logger.tool_policy_event.assert_called_once_with(
            tool_name="Bash",
            allowed=False,
            reason="always_denied",
            server_id="",
        )

    def test_logger_called_on_allow(self) -> None:
        """AgentLogger.tool_policy_event vyzyvaetsya pri allow (GAP-4)."""
        from unittest.mock import MagicMock

        mock_logger = MagicMock()
        policy = DefaultToolPolicy(agent_logger=mock_logger)
        state = _make_state(active_skills=["iss"])

        policy.can_use_tool("mcp__iss__search_bonds", {}, state)

        mock_logger.tool_policy_event.assert_called_once_with(
            tool_name="mcp__iss__search_bonds",
            allowed=True,
            reason="mcp_active_skill",
            server_id="iss",
        )

    def test_works_without_logger(self) -> None:
        """Without AgentLogger - works kak ranshe (obratnaya sovmestimost)."""
        policy = DefaultToolPolicy()
        state = _make_state(active_skills=["iss"])
        result = policy.can_use_tool("mcp__iss__search_bonds", {}, state)
        assert isinstance(result, PermissionAllow)
