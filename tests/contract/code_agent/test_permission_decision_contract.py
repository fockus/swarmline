"""Contract tests for `PermissionDecision` (code-agent-facade plan, Stage 1).

`PermissionDecision` is the single new public value object introduced by the
`CodeAgent` facade: a frozen, ergonomic return type for
`on_permission_request` callbacks so consumers never have to import the
infrastructure `HookResult` type. These tests pin that contract before any
wiring exists (Contract-First gate).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from swarmline.code_agent import PermissionDecision


class TestPermissionDecisionFactories:
    def test_permission_decision_allow_factory_sets_allowed_true(self) -> None:
        decision = PermissionDecision.allow()

        assert decision.allowed is True
        assert decision.reason == ""

    def test_permission_decision_deny_factory_carries_reason(self) -> None:
        decision = PermissionDecision.deny("destructive: rm -rf /")

        assert decision.allowed is False
        assert decision.reason == "destructive: rm -rf /"


class TestPermissionDecisionImmutability:
    @pytest.mark.parametrize(
        "field_name, value",
        [("allowed", False), ("reason", "mutated")],
    )
    def test_permission_decision_is_frozen_raises_on_mutation(
        self, field_name: str, value: object
    ) -> None:
        decision = PermissionDecision.allow()

        with pytest.raises(FrozenInstanceError):
            setattr(decision, field_name, value)
