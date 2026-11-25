"""Tests for ApprovalGateManager implementation.

TDD: these tests written BEFORE the implementation.
Tests pattern matching, risk-based gating, auto-approve threshold.
"""

from __future__ import annotations

from swarmline.governance.protocols import ApprovalGatePort
from swarmline.governance.types import ApprovalGateConfig, PermissionLevel


def _make_gate_manager() -> ApprovalGatePort:
    from swarmline.governance.approval_gates import ApprovalGateManager

    return ApprovalGateManager()


class TestApprovalGateManagerSatisfiesProtocol:
    """ApprovalGateManager implements ApprovalGatePort."""

    def test_isinstance_check(self) -> None:
        mgr = _make_gate_manager()
        assert isinstance(mgr, ApprovalGatePort)


class TestBuiltInGates:
    """Default gates cover destructive and risky actions."""

    def test_has_default_gates(self) -> None:
        mgr = _make_gate_manager()
        gates = mgr.get_gates_for_action("deploy.production")
        assert len(gates) > 0

    def test_deploy_requires_approval(self) -> None:
        mgr = _make_gate_manager()
        gate = mgr.check_gate("deploy.production", PermissionLevel.EDIT)
        assert gate is not None
        assert gate.requires_approval is True

    def test_delete_requires_approval(self) -> None:
        mgr = _make_gate_manager()
        gate = mgr.check_gate("delete_file", PermissionLevel.EDIT)
        assert gate is not None
        assert gate.requires_approval is True

    def test_force_push_requires_approval(self) -> None:
        mgr = _make_gate_manager()
        gate = mgr.check_gate("force_push", PermissionLevel.EDIT)
        assert gate is not None
        assert gate.requires_approval is True


class TestPatternMatching:
    """Gates use fnmatch-style pattern matching on action strings."""

    def test_glob_pattern_matches(self) -> None:
        mgr = _make_gate_manager()
        gate = mgr.check_gate("deploy.staging", PermissionLevel.EDIT)
        assert gate is not None

    def test_no_match_returns_none(self) -> None:
        mgr = _make_gate_manager()
        gate = mgr.check_gate("read_file", PermissionLevel.READ_ONLY)
        assert gate is None

    def test_get_gates_for_action_multiple_matches(self) -> None:
        from swarmline.governance.approval_gates import ApprovalGateManager

        gates = [
            ApprovalGateConfig(
                action_pattern="deploy.*",
                risk_level="high",
                requires_approval=True,
                auto_approve_below=None,
            ),
            ApprovalGateConfig(
                action_pattern="deploy.production",
                risk_level="critical",
                requires_approval=True,
                auto_approve_below=None,
            ),
        ]
        mgr = ApprovalGateManager(gates=gates)
        result = mgr.get_gates_for_action("deploy.production")
        assert len(result) == 2

    def test_get_gates_for_action_no_match_empty(self) -> None:
        mgr = _make_gate_manager()
        result = mgr.get_gates_for_action("safe_action")
        assert result == []


class TestAutoApproveThreshold:
    """Auto-approve if profile level >= gate threshold."""

    def test_auto_approve_when_level_sufficient(self) -> None:
        from swarmline.governance.approval_gates import ApprovalGateManager

        gates = [
            ApprovalGateConfig(
                action_pattern="write_file",
                risk_level="medium",
                requires_approval=True,
                auto_approve_below=PermissionLevel.GIT_WRITE,
            ),
        ]
        mgr = ApprovalGateManager(gates=gates)
        gate = mgr.check_gate("write_file", PermissionLevel.GIT_WRITE)
        assert gate is None

    def test_gate_triggered_when_level_insufficient(self) -> None:
        from swarmline.governance.approval_gates import ApprovalGateManager

        gates = [
            ApprovalGateConfig(
                action_pattern="write_file",
                risk_level="medium",
                requires_approval=True,
                auto_approve_below=PermissionLevel.GIT_WRITE,
            ),
        ]
        mgr = ApprovalGateManager(gates=gates)
        gate = mgr.check_gate("write_file", PermissionLevel.EDIT)
        assert gate is not None
        assert gate.requires_approval is True


class TestCustomGates:
    """ApprovalGateManager accepts custom gate configurations."""

    def test_custom_gates_override_defaults(self) -> None:
        from swarmline.governance.approval_gates import ApprovalGateManager

        custom = [
            ApprovalGateConfig(
                action_pattern="custom_action",
                risk_level="low",
                requires_approval=False,
                auto_approve_below=None,
            ),
        ]
        mgr = ApprovalGateManager(gates=custom)
        result = mgr.get_gates_for_action("deploy.production")
        assert result == []
        result = mgr.get_gates_for_action("custom_action")
        assert len(result) == 1
