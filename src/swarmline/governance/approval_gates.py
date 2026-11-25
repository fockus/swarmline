"""ApprovalGateManager — configurable approval gates by action pattern.

Gates use fnmatch pattern matching on action strings.
Risk-based: destructive actions require approval.
Auto-approve if profile level >= gate threshold.
"""

from __future__ import annotations

import fnmatch

from swarmline.governance.types import ApprovalGateConfig, PermissionLevel

_BUILTIN_GATES: tuple[ApprovalGateConfig, ...] = (
    ApprovalGateConfig(
        action_pattern="deploy*",
        risk_level="critical",
        requires_approval=True,
        auto_approve_below=None,
    ),
    ApprovalGateConfig(
        action_pattern="force_*",
        risk_level="high",
        requires_approval=True,
        auto_approve_below=None,
    ),
    ApprovalGateConfig(
        action_pattern="delete_*",
        risk_level="high",
        requires_approval=True,
        auto_approve_below=PermissionLevel.DEPLOY_CAPABLE,
    ),
)


class ApprovalGateManager:
    """Configurable approval gate manager with pattern matching.

    Implements ApprovalGatePort:
    - check_gate: find first matching gate; auto-approve if level sufficient
    - get_gates_for_action: return all matching gates for an action
    """

    def __init__(self, gates: list[ApprovalGateConfig] | None = None) -> None:
        self._gates: tuple[ApprovalGateConfig, ...] = (
            tuple(gates) if gates is not None else _BUILTIN_GATES
        )

    def check_gate(
        self, action: str, profile_level: PermissionLevel
    ) -> ApprovalGateConfig | None:
        for gate in self._gates:
            if fnmatch.fnmatch(action, gate.action_pattern):
                if (
                    gate.auto_approve_below is not None
                    and profile_level >= gate.auto_approve_below
                ):
                    continue
                if gate.requires_approval:
                    return gate
        return None

    def get_gates_for_action(self, action: str) -> list[ApprovalGateConfig]:
        return [
            gate for gate in self._gates if fnmatch.fnmatch(action, gate.action_pattern)
        ]
