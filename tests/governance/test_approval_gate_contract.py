"""Contract tests for ApprovalGatePort.

These tests verify the Protocol contract, not any specific implementation.
Any class implementing check_gate + get_gates_for_action should pass.
"""

from __future__ import annotations

import pytest
from swarmline.governance.protocols import ApprovalGatePort
from swarmline.governance.types import (
    ApprovalGateConfig,
    PermissionLevel,
)


class _StubApprovalGate:
    """Minimal valid implementation for contract testing."""

    _gates: list[ApprovalGateConfig] = [
        ApprovalGateConfig(
            action_pattern="deploy.*",
            risk_level="high",
            requires_approval=True,
            auto_approve_below=None,
        ),
        ApprovalGateConfig(
            action_pattern="write_file",
            risk_level="medium",
            requires_approval=True,
            auto_approve_below=PermissionLevel.GIT_WRITE,
        ),
        ApprovalGateConfig(
            action_pattern="read_*",
            risk_level="low",
            requires_approval=False,
            auto_approve_below=None,
        ),
    ]

    def check_gate(
        self, action: str, profile_level: PermissionLevel
    ) -> ApprovalGateConfig | None:
        for gate in self._gates:
            if action.startswith(gate.action_pattern.rstrip("*")):
                return gate
        return None

    def get_gates_for_action(self, action: str) -> list[ApprovalGateConfig]:
        results = []
        for gate in self._gates:
            if action.startswith(gate.action_pattern.rstrip("*")):
                results.append(gate)
        return results


class _InvalidApprovalGate:
    """Class without required methods — should NOT satisfy Protocol."""

    pass


class TestApprovalGatePortContract:
    """ApprovalGatePort contract tests."""

    def test_protocol_is_runtime_checkable(self) -> None:
        impl = _StubApprovalGate()
        assert isinstance(impl, ApprovalGatePort)

    def test_invalid_impl_fails_isinstance(self) -> None:
        invalid = _InvalidApprovalGate()
        assert not isinstance(invalid, ApprovalGatePort)

    def test_check_gate_returns_config_or_none(self) -> None:
        impl = _StubApprovalGate()
        result = impl.check_gate("deploy.production", PermissionLevel.EDIT)
        assert isinstance(result, ApprovalGateConfig) or result is None

    def test_check_gate_matching_action(self) -> None:
        impl = _StubApprovalGate()
        result = impl.check_gate("deploy.staging", PermissionLevel.EDIT)
        assert result is not None
        assert result.risk_level == "high"

    def test_check_gate_no_match_returns_none(self) -> None:
        impl = _StubApprovalGate()
        result = impl.check_gate("unknown_action", PermissionLevel.EDIT)
        assert result is None

    def test_get_gates_for_action_returns_list(self) -> None:
        impl = _StubApprovalGate()
        result = impl.get_gates_for_action("deploy.production")
        assert isinstance(result, list)
        assert all(isinstance(g, ApprovalGateConfig) for g in result)

    def test_get_gates_for_action_no_match_empty_list(self) -> None:
        impl = _StubApprovalGate()
        result = impl.get_gates_for_action("unknown")
        assert result == []


class TestApprovalGateConfigFrozen:
    """ApprovalGateConfig is a frozen dataclass."""

    def test_gate_config_is_frozen(self) -> None:
        g = ApprovalGateConfig(
            action_pattern="test",
            risk_level="low",
            requires_approval=False,
            auto_approve_below=None,
        )
        with pytest.raises(AttributeError):
            g.action_pattern = "changed"  # type: ignore[misc]

    def test_gate_config_fields(self) -> None:
        g = ApprovalGateConfig(
            action_pattern="deploy.*",
            risk_level="high",
            requires_approval=True,
            auto_approve_below=PermissionLevel.NETWORK_ENABLED,
        )
        assert g.action_pattern == "deploy.*"
        assert g.risk_level == "high"
        assert g.requires_approval is True
        assert g.auto_approve_below == PermissionLevel.NETWORK_ENABLED
