"""Тесты для DefaultToolPolicy."""

import pytest

from cognitia.policy import (
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
    """Тесты на запрещённые инструменты."""

    def test_bash_denied(self, policy: DefaultToolPolicy) -> None:
        """Bash всегда запрещён."""
        result = policy.can_use_tool("Bash", {}, _make_state())
        assert isinstance(result, PermissionDeny)
        assert "Bash" in result.message

    def test_read_denied(self, policy: DefaultToolPolicy) -> None:
        """Read всегда запрещён."""
        result = policy.can_use_tool("Read", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_write_denied(self, policy: DefaultToolPolicy) -> None:
        """Write всегда запрещён."""
        result = policy.can_use_tool("Write", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_edit_denied(self, policy: DefaultToolPolicy) -> None:
        """Edit всегда запрещён."""
        result = policy.can_use_tool("Edit", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_glob_denied(self, policy: DefaultToolPolicy) -> None:
        """Glob всегда запрещён."""
        result = policy.can_use_tool("Glob", {}, _make_state())
        assert isinstance(result, PermissionDeny)

    def test_all_denied_tools_covered(self, policy: DefaultToolPolicy) -> None:
        """Все инструменты из ALWAYS_DENIED_TOOLS запрещены."""
        for tool_name in ALWAYS_DENIED_TOOLS:
            result = policy.can_use_tool(tool_name, {}, _make_state())
            assert isinstance(result, PermissionDeny), f"{tool_name} должен быть запрещён"


class TestMcpTools:
    """Тесты на MCP инструменты."""

    def test_mcp_tool_allowed_when_skill_active(self, policy: DefaultToolPolicy) -> None:
        """MCP tool разрешён, если сервер в активных скилах."""
        state = _make_state(active_skills=["iss"])
        result = policy.can_use_tool("mcp__iss__search_bonds", {}, state)
        assert isinstance(result, PermissionAllow)

    def test_mcp_tool_denied_when_skill_inactive(self, policy: DefaultToolPolicy) -> None:
        """MCP tool запрещён, если сервер не в активных скилах."""
        state = _make_state(active_skills=["finuslugi"])
        result = policy.can_use_tool("mcp__iss__search_bonds", {}, state)
        assert isinstance(result, PermissionDeny)
        assert "iss" in result.message

    def test_mcp_tool_different_servers(self, policy: DefaultToolPolicy) -> None:
        """MCP tool от finuslugi разрешён если finuslugi активен."""
        state = _make_state(active_skills=["finuslugi", "iss"])
        result = policy.can_use_tool("mcp__finuslugi__get_bank_deposits", {}, state)
        assert isinstance(result, PermissionAllow)


class TestLocalTools:
    """Тесты на локальные инструменты."""

    def test_local_tool_allowed(self, policy: DefaultToolPolicy) -> None:
        """Локальный tool разрешён если в allowed_local_tools."""
        state = _make_state(local_tools={"mcp__freedom_tools__calculate_goal_plan"})
        result = policy.can_use_tool("mcp__freedom_tools__calculate_goal_plan", {}, state)
        assert isinstance(result, PermissionAllow)

    def test_unknown_tool_denied(self, policy: DefaultToolPolicy) -> None:
        """Неизвестный tool запрещён."""
        state = _make_state()
        result = policy.can_use_tool("SomeRandomTool", {}, state)
        assert isinstance(result, PermissionDeny)


class TestAllowedSystemTools:
    """Тесты на whitelist system tools (0.3.0-5)."""

    def test_bash_allowed_via_whitelist(self) -> None:
        """Bash разрешён если в allowed_system_tools."""
        policy = DefaultToolPolicy(allowed_system_tools={"Bash"})
        state = _make_state(local_tools={"Bash"})
        result = policy.can_use_tool("Bash", {}, state)
        assert isinstance(result, PermissionAllow)

    def test_read_write_allowed(self) -> None:
        """Read и Write разрешены через whitelist."""
        policy = DefaultToolPolicy(allowed_system_tools={"Read", "Write"})
        state = _make_state(local_tools={"Read", "Write"})

        assert isinstance(policy.can_use_tool("Read", {}, state), PermissionAllow)
        assert isinstance(policy.can_use_tool("Write", {}, state), PermissionAllow)

    def test_other_denied_tools_still_blocked(self) -> None:
        """Whitelist не влияет на другие denied tools."""
        policy = DefaultToolPolicy(allowed_system_tools={"Bash"})
        state = _make_state()
        # Edit НЕ в whitelist — должен быть заблокирован
        result = policy.can_use_tool("Edit", {}, state)
        assert isinstance(result, PermissionDeny)

    def test_none_whitelist_backward_compat(self) -> None:
        """allowed_system_tools=None → всё как раньше."""
        policy = DefaultToolPolicy(allowed_system_tools=None)
        state = _make_state()
        result = policy.can_use_tool("Bash", {}, state)
        assert isinstance(result, PermissionDeny)

    def test_empty_set_whitelist_backward_compat(self) -> None:
        """allowed_system_tools=set() → всё как раньше."""
        policy = DefaultToolPolicy(allowed_system_tools=set())
        state = _make_state()
        result = policy.can_use_tool("Bash", {}, state)
        assert isinstance(result, PermissionDeny)

    def test_whitelist_with_extra_denied(self) -> None:
        """Whitelist + extra_denied — whitelist имеет приоритет."""
        policy = DefaultToolPolicy(
            allowed_system_tools={"Bash"},
            extra_denied={"CustomTool"},
        )
        state = _make_state(local_tools={"Bash"})
        # Bash разрешён через whitelist
        assert isinstance(policy.can_use_tool("Bash", {}, state), PermissionAllow)
        # CustomTool запрещён через extra_denied
        assert isinstance(policy.can_use_tool("CustomTool", {}, state), PermissionDeny)


class TestAgentLoggerIntegration:
    """GAP-4: AgentLogger.tool_policy_event() вызывается в DefaultToolPolicy."""

    def test_logger_called_on_deny(self) -> None:
        """AgentLogger.tool_policy_event вызывается при deny (GAP-4)."""
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
        """AgentLogger.tool_policy_event вызывается при allow (GAP-4)."""
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
        """Без AgentLogger — работает как раньше (обратная совместимость)."""
        policy = DefaultToolPolicy()
        state = _make_state(active_skills=["iss"])
        result = policy.can_use_tool("mcp__iss__search_bonds", {}, state)
        assert isinstance(result, PermissionAllow)
