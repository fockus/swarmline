"""`on_permission_request` -> PreToolUse hook adapter (code-agent-facade plan,
Stage 3).

Adapts the public `PermissionCallback` into a single `HookRegistry` entry by
reusing the EXISTING hook infrastructure (`HookRegistry` / `HookResult` /
`DefaultHookDispatcher`) -- no new interrupt machinery, no new Protocol. The
callback's own "ask the user" mechanics (however the host implements them)
are entirely opaque to this module; it only normalizes the callback's
`bool | PermissionDecision` return into a `HookResult`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from swarmline.hooks.dispatcher import HookResult
from swarmline.hooks.registry import HookRegistry

if TYPE_CHECKING:
    from swarmline.code_agent.types import PermissionCallback

logger = logging.getLogger(__name__)

_GENERIC_DENY_REASON = "Denied by on_permission_request callback"
_CALLBACK_ERROR_REASON = "on_permission_request callback raised an exception"
_UNEXPECTED_RETURN_REASON = (
    "on_permission_request callback returned an unexpected type "
    "(expected bool or PermissionDecision)"
)


def _normalize_decision(result: Any) -> HookResult:
    """Convert the callback's `bool | PermissionDecision` return into a
    `HookResult`.

    Only `PermissionDecision` and `bool` are honored. Anything else (a
    string, a dict, `None`, ...) is a fail-closed programming error, NOT
    coerced through Python's truthiness -- a bare `if result:` check would
    silently treat a non-empty string like `"false"`, or a non-empty dict,
    as "allow", the exact opposite of what a permission-denying value like
    that usually means.
    """
    from swarmline.code_agent.types import PermissionDecision

    if isinstance(result, PermissionDecision):
        if result.allowed:
            return HookResult.allow()
        return HookResult.block(result.reason or _GENERIC_DENY_REASON)
    if isinstance(result, bool):
        return HookResult.allow() if result else HookResult.block(_GENERIC_DENY_REASON)
    logger.warning(
        "on_permission_request callback returned unexpected type %s -- "
        "denying (fail-closed)",
        type(result).__name__,
    )
    return HookResult.block(_UNEXPECTED_RETURN_REASON)


def build_permission_hook(callback: PermissionCallback) -> HookRegistry:
    """Build a `HookRegistry` with one PreToolUse hook wrapping `callback`.

    Registered with an empty matcher, so it runs for every tool call (the
    callback itself decides what to allow/deny per `tool_name`).

    Fail-closed by construction: any exception `callback` raises is caught
    HERE and translated to `HookResult.block(...)`. This is deliberate --
    `DefaultHookDispatcher` itself is fail-OPEN on a raising hook (it logs a
    warning and treats the call as "allow", so one misbehaving hook never
    aborts an agent run). That default is right for cosmetic/best-effort
    hooks, but wrong for a security gate: a permission callback that raises
    must never silently become "allowed". So this adapter never lets the
    exception reach the dispatcher's own fail-open handling.
    """

    async def _on_pre_tool_use(
        *, tool_name: str, tool_input: dict[str, Any]
    ) -> HookResult:
        try:
            decision = await callback(tool_name, tool_input)
        except Exception:  # fail-closed -- never re-raise
            # The real exception (which may embed secrets/internal details
            # from the host's permission backend, e.g. a credential-lookup
            # failure) is logged server-side only -- NEVER echoed into the
            # HookResult message, which flows straight back into the
            # tool-call transcript the model itself sees.
            logger.warning(
                "on_permission_request callback raised while checking "
                "tool_name=%r -- denying (fail-closed)",
                tool_name,
                exc_info=True,
            )
            return HookResult.block(_CALLBACK_ERROR_REASON)
        return _normalize_decision(decision)

    registry = HookRegistry()
    registry.on_pre_tool_use(_on_pre_tool_use)
    return registry
