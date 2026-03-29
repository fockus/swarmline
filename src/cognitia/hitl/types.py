"""HITL types — approval requests, responses, policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ApprovalRequest:
    """Request for human approval of an agent action."""

    action: str  # e.g. "tool_call", "plan_step", "send_message"
    description: str  # human-readable description
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalResponse:
    """Human response to an approval request."""

    approved: bool
    reason: str = ""
    modifications: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ApprovalCallback(Protocol):
    """Protocol for getting human approval."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse: ...


@runtime_checkable
class ApprovalPolicy(Protocol):
    """Protocol for deciding whether to require human approval."""

    def requires_approval(self, action: str, context: dict[str, Any]) -> bool: ...
