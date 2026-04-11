"""Unit: HITL patterns — policies, gate, callbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarmline.hitl.gate import ApprovalDeniedError, ApprovalGate
from swarmline.hitl.policies import (
    AlwaysApprovePolicy,
    AlwaysDenyPolicy,
    CostApprovalPolicy,
    ToolApprovalPolicy,
)
from swarmline.hitl.types import (
    ApprovalCallback,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResponse,
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class TestTypes:

    def test_approval_request_creation(self) -> None:
        req = ApprovalRequest(action="tool_call", description="Execute code")
        assert req.action == "tool_call"

    def test_approval_response_creation(self) -> None:
        resp = ApprovalResponse(approved=True, reason="looks safe")
        assert resp.approved is True

    def test_protocol_checkable(self) -> None:
        class FakeCallback:
            async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
                return ApprovalResponse(approved=True)

        assert isinstance(FakeCallback(), ApprovalCallback)

    def test_policy_protocol_checkable(self) -> None:
        class FakePolicy:
            def requires_approval(self, action: str, context: dict) -> bool:
                return True

        assert isinstance(FakePolicy(), ApprovalPolicy)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


class TestAlwaysApprovePolicy:

    def test_never_requires(self) -> None:
        p = AlwaysApprovePolicy()
        assert p.requires_approval("tool_call", {}) is False
        assert p.requires_approval("plan_step", {}) is False


class TestAlwaysDenyPolicy:

    def test_always_requires(self) -> None:
        p = AlwaysDenyPolicy()
        assert p.requires_approval("tool_call", {}) is True
        assert p.requires_approval("plan_step", {}) is True


class TestToolApprovalPolicy:

    def test_requires_for_listed_tool(self) -> None:
        p = ToolApprovalPolicy(tools=frozenset({"execute_code", "write_file"}))
        assert p.requires_approval("tool_call", {"tool_name": "execute_code"}) is True

    def test_does_not_require_for_unlisted_tool(self) -> None:
        p = ToolApprovalPolicy(tools=frozenset({"execute_code"}))
        assert p.requires_approval("tool_call", {"tool_name": "web_search"}) is False

    def test_does_not_require_for_non_tool_action(self) -> None:
        p = ToolApprovalPolicy(tools=frozenset({"execute_code"}))
        assert p.requires_approval("plan_step", {"tool_name": "execute_code"}) is False


class TestCostApprovalPolicy:

    def test_requires_when_over_threshold(self) -> None:
        p = CostApprovalPolicy(threshold_usd=0.50)
        assert p.requires_approval("query", {"estimated_cost_usd": 1.00}) is True

    def test_does_not_require_when_under(self) -> None:
        p = CostApprovalPolicy(threshold_usd=0.50)
        assert p.requires_approval("query", {"estimated_cost_usd": 0.10}) is False

    def test_does_not_require_when_no_cost(self) -> None:
        p = CostApprovalPolicy(threshold_usd=0.50)
        assert p.requires_approval("query", {}) is False


# ---------------------------------------------------------------------------
# ApprovalGate
# ---------------------------------------------------------------------------


class TestApprovalGate:

    def _make_callback(self, approved: bool = True, reason: str = "") -> AsyncMock:
        cb = AsyncMock()
        cb.request_approval = AsyncMock(
            return_value=ApprovalResponse(approved=approved, reason=reason)
        )
        return cb

    async def test_no_approval_needed(self) -> None:
        cb = self._make_callback()
        gate = ApprovalGate(policy=AlwaysApprovePolicy(), callback=cb)
        result = await gate.check("tool_call", {})
        assert result is True
        cb.request_approval.assert_not_called()

    async def test_approval_granted(self) -> None:
        cb = self._make_callback(approved=True)
        gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=cb)
        result = await gate.check("tool_call", {})
        assert result is True
        cb.request_approval.assert_called_once()

    async def test_approval_denied(self) -> None:
        cb = self._make_callback(approved=False, reason="too risky")
        gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=cb)
        result = await gate.check("tool_call", {})
        assert result is False

    async def test_raise_on_deny(self) -> None:
        cb = self._make_callback(approved=False, reason="nope")
        gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=cb)
        with pytest.raises(ApprovalDeniedError) as exc_info:
            await gate.check("execute", {}, raise_on_deny=True)
        assert "nope" in str(exc_info.value)

    async def test_tool_policy_integration(self) -> None:
        cb = self._make_callback(approved=True)
        policy = ToolApprovalPolicy(tools=frozenset({"execute_code"}))
        gate = ApprovalGate(policy=policy, callback=cb)

        # Allowed tool — no approval needed
        result = await gate.check("tool_call", {"tool_name": "web_search"})
        assert result is True
        cb.request_approval.assert_not_called()

        # Restricted tool — approval requested
        result = await gate.check("tool_call", {"tool_name": "execute_code"})
        assert result is True
        cb.request_approval.assert_called_once()

    async def test_gate_passes_context_to_request(self) -> None:
        cb = self._make_callback()
        gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=cb)
        await gate.check(
            "tool_call",
            {"tool_name": "exec", "tool_args": {"code": "rm -rf /"}},
            description="Dangerous operation",
        )
        req = cb.request_approval.call_args[0][0]
        assert req.tool_name == "exec"
        assert req.description == "Dangerous operation"
