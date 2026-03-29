"""Built-in approval policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AlwaysApprovePolicy:
    """Never require human approval."""

    def requires_approval(self, action: str, context: dict[str, Any]) -> bool:
        return False


@dataclass
class AlwaysDenyPolicy:
    """Always require human approval (safest)."""

    def requires_approval(self, action: str, context: dict[str, Any]) -> bool:
        return True


@dataclass
class ToolApprovalPolicy:
    """Require approval for specific tools."""

    tools: frozenset[str] = frozenset()

    def requires_approval(self, action: str, context: dict[str, Any]) -> bool:
        if action != "tool_call":
            return False
        tool_name = context.get("tool_name", "")
        return tool_name in self.tools


@dataclass
class CostApprovalPolicy:
    """Require approval when estimated cost exceeds threshold."""

    threshold_usd: float = 0.10

    def requires_approval(self, action: str, context: dict[str, Any]) -> bool:
        cost = context.get("estimated_cost_usd", 0.0)
        return isinstance(cost, (int, float)) and cost > self.threshold_usd
