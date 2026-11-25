"""Public value types for the `CodeAgent` facade (code-agent-facade plan, Stage 1).

`PermissionDecision` and `PermissionCallback` are the *only* new abstractions
this facade introduces (see the plan's "New abstractions introduced"
section). `PermissionDecision` is a frozen value object -- not a Protocol --
so callers never need to import the infrastructure `HookResult` type.
`PermissionCallback` is a bare callable signature, also not a Protocol.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """Ergonomic, frozen result of an `on_permission_request` callback.

    Attributes:
        allowed: Whether the requested tool call may proceed.
        reason: Human-readable explanation, primarily used on denial.
    """

    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls) -> PermissionDecision:
        """Build a decision that permits the tool call to proceed."""
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> PermissionDecision:
        """Build a decision that blocks the tool call, carrying `reason`."""
        return cls(allowed=False, reason=reason)


# A permission callback receives the tool name and its arguments, and
# returns either a plain bool (True == allow) or a `PermissionDecision` for
# callers that want to carry a `reason`. Bare callable signature -- no new
# Protocol (kept ISP-trivial: a single call surface).
PermissionCallback = Callable[
    [str, dict[str, Any]], Awaitable["bool | PermissionDecision"]
]
