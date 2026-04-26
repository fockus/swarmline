"""Approval gate — middleware that pauses for human approval."""

from __future__ import annotations

from typing import Any

from swarmline.errors import SwarmlineError
from swarmline.hitl.types import ApprovalRequest, ApprovalResponse


class ApprovalDeniedError(SwarmlineError):
    """Raised when a human denies an action."""

    def __init__(self, request: ApprovalRequest, response: ApprovalResponse) -> None:
        self.request = request
        self.response = response
        super().__init__(
            f"Action '{request.action}' denied: {response.reason or 'no reason given'}"
        )


class ApprovalGate:
    """Middleware that checks a policy and requests human approval when needed.

    Usage:
        gate = ApprovalGate(policy=ToolApprovalPolicy(tools={"execute_code"}), callback=my_callback)
        approved = await gate.check("tool_call", {"tool_name": "execute_code", "args": {...}})
    """

    def __init__(self, policy: Any, callback: Any) -> None:
        self._policy = policy
        self._callback = callback

    async def check(
        self,
        action: str,
        context: dict[str, Any],
        *,
        description: str = "",
        raise_on_deny: bool = False,
    ) -> bool:
        """Check if action needs approval and get it.

        Returns True if approved (or no approval needed), False if denied.
        If raise_on_deny=True, raises ApprovalDeniedError on denial.
        """
        if not self._policy.requires_approval(action, context):
            return True

        request = ApprovalRequest(
            action=action,
            description=description or f"Agent wants to perform: {action}",
            tool_name=context.get("tool_name"),
            tool_args=context.get("tool_args", {}),
            estimated_cost_usd=context.get("estimated_cost_usd"),
            context=context,
        )
        response = await self._callback.request_approval(request)

        if response.approved:
            return True

        if raise_on_deny:
            raise ApprovalDeniedError(request, response)
        return False
