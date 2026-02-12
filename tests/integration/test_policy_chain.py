"""Integration: ToolPolicy + ToolIdCodec + ToolBudget — полная цепочка проверки доступа.

Сценарий: реальный workflow, где пользователь с ролью deposit_advisor
активирует скиллы finuslugi и iss-price, затем агент вызывает tools.
"""

import pytest

from cognitia.policy.tool_budget import ToolBudget
from cognitia.policy.tool_id_codec import DefaultToolIdCodec
from cognitia.policy.tool_policy import (
    DefaultToolPolicy,
    PermissionAllow,
    PermissionDeny,
    ToolPolicyInput,
)


@pytest.fixture
def codec() -> DefaultToolIdCodec:
    return DefaultToolIdCodec()


@pytest.fixture
def policy(codec: DefaultToolIdCodec) -> DefaultToolPolicy:
    return DefaultToolPolicy(codec=codec)


@pytest.fixture
def budget() -> ToolBudget:
    return ToolBudget(max_tool_calls=5, max_mcp_calls=3)


def _state(
    skills: list[str] | None = None,
    local_tools: set[str] | None = None,
) -> ToolPolicyInput:
    """Создать ToolPolicyInput для тестов."""
    return ToolPolicyInput(
        tool_name="",  # перезаписывается в can_use_tool
        input_data={},
        active_skill_ids=skills or [],
        allowed_local_tools=local_tools or set(),
    )


class TestDepositAdvisorWorkflow:
    """Сценарий: deposit_advisor с finuslugi + iss-price скиллами."""

    def test_allow_finuslugi_tool(self, policy: DefaultToolPolicy) -> None:
        """MCP tool от активного скилла finuslugi → allow."""
        state = _state(skills=["finuslugi", "iss-price"])
        result = policy.can_use_tool(
            "mcp__finuslugi__get_deposits", {}, state
        )
        assert isinstance(result, PermissionAllow)

    def test_allow_iss_price_tool(self, policy: DefaultToolPolicy) -> None:
        """MCP tool от iss-price → allow."""
        state = _state(skills=["finuslugi", "iss-price"])
        result = policy.can_use_tool(
            "mcp__iss-price__get_bond_price", {}, state
        )
        assert isinstance(result, PermissionAllow)

    def test_deny_inactive_skill_tool(self, policy: DefaultToolPolicy) -> None:
        """MCP tool от неактивного скилла funds → deny."""
        state = _state(skills=["finuslugi", "iss-price"])
        result = policy.can_use_tool(
            "mcp__funds__get_fund_info", {}, state
        )
        assert isinstance(result, PermissionDeny)

    def test_deny_dangerous_tools(self, policy: DefaultToolPolicy) -> None:
        """File/shell tools всегда запрещены даже если в local."""
        state = _state(skills=["finuslugi"], local_tools={"Bash"})
        result = policy.can_use_tool("Bash", {}, state)
        assert isinstance(result, PermissionDeny)

    def test_allow_local_tool(self, policy: DefaultToolPolicy) -> None:
        """Local tool из allowlist → allow."""
        state = _state(
            skills=["finuslugi"],
            local_tools={"mcp__freedom_tools__calculate_deposit"},
        )
        result = policy.can_use_tool(
            "mcp__freedom_tools__calculate_deposit", {}, state
        )
        assert isinstance(result, PermissionAllow)


class TestBudgetIntegration:
    """ToolBudget + ToolPolicy: бюджет ограничивает вызовы."""

    def test_budget_tracks_mcp_calls(
        self, policy: DefaultToolPolicy, budget: ToolBudget
    ) -> None:
        """Бюджет считает MCP-вызовы отдельно."""
        state = _state(skills=["iss"])

        for i in range(3):
            result = policy.can_use_tool(f"mcp__iss__tool_{i}", {}, state)
            assert isinstance(result, PermissionAllow)
            assert budget.can_call(is_mcp=True)
            budget.record_call(is_mcp=True)

        # 4-й MCP вызов — бюджет исчерпан
        assert budget.can_call(is_mcp=True) is False

    def test_budget_allows_local_after_mcp_exhausted(
        self, policy: DefaultToolPolicy, budget: ToolBudget
    ) -> None:
        """Когда MCP-бюджет исчерпан, local tools ещё доступны."""
        for _ in range(3):
            budget.record_call(is_mcp=True)

        # MCP исчерпан
        assert budget.can_call(is_mcp=True) is False
        # Но local ещё можно (всего 3/5)
        assert budget.can_call(is_mcp=False) is True

    def test_total_budget_exhaustion(self, budget: ToolBudget) -> None:
        """Общий бюджет 5 — после 5 вызовов всё запрещено."""
        for _ in range(5):
            budget.record_call(is_mcp=False)
        assert budget.is_exhausted() is True
        assert budget.can_call(is_mcp=False) is False

    def test_reset_restores_budget(self, budget: ToolBudget) -> None:
        """Reset сбрасывает бюджет."""
        for _ in range(5):
            budget.record_call(is_mcp=True)
        assert budget.is_exhausted() is True
        budget.reset()
        assert budget.is_exhausted() is False
        assert budget.can_call(is_mcp=True) is True


class TestCodecIntegration:
    """ToolIdCodec корректно парсит реальные имена tools из MCP серверов."""

    def test_real_server_names(self, codec: DefaultToolIdCodec) -> None:
        """Парсинг реальных имён инструментов."""
        cases = [
            ("mcp__iss__get_emitent_id", "iss"),
            ("mcp__iss-price__get_bond_price", "iss-price"),
            ("mcp__finuslugi__search_deposits", "finuslugi"),
            ("mcp__funds__get_fund_list", "funds"),
        ]
        for tool_name, expected_server in cases:
            assert codec.extract_server(tool_name) == expected_server
            assert codec.matches(tool_name, expected_server) is True

    def test_encode_roundtrip(self, codec: DefaultToolIdCodec) -> None:
        """encode → extract_server = roundtrip."""
        encoded = codec.encode("iss-price", "get_bond_price")
        assert encoded == "mcp__iss-price__get_bond_price"
        assert codec.extract_server(encoded) == "iss-price"
