"""HookDispatcher — dispatches hook events to registered callbacks.

HookDispatcher Protocol (4 async methods, ISP-compliant) + DefaultHookDispatcher
that iterates HookRegistry entries with fnmatch-based tool name filtering.

Policy split (stage 28 / conformance-audit CONF-01):

- **PreToolUse is fail-closed.** It is an enforcement gate, not a
  fire-and-forget observer: an exception raised by a hook callback, or a
  verdict the dispatcher cannot recognize (including a bare ``None`` — a
  hook that forgot a ``return`` statement), BLOCKS execution. Otherwise any
  enforcement implemented as a PreToolUse hook is bypassable by a single
  exception. A hook that fails ``PRE_TOOL_QUARANTINE_THRESHOLD`` times in a
  row is quarantined (excluded from further dispatch) so a persistently
  broken — but not malicious — hook cannot wedge every tool call forever;
  every failure and the quarantine event itself are logged for
  observability. Zero registered hooks still allows (never block emptiness).
- **PostToolUse / Stop / UserPromptSubmit / session events remain
  fail-open**: any exception in a callback is logged as a warning and
  execution continues normally (different track, CONF-02).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Literal, Protocol, runtime_checkable

from swarmline.hooks._helpers import _hook_name
from swarmline.hooks.registry import HookRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HookResult:
    """Immutable result of a pre-tool hook dispatch.

    Use factory class methods instead of direct construction:
        HookResult.allow()
        HookResult.block("reason")
        HookResult.modify({"key": "value"})
    """

    action: Literal["allow", "block", "modify"]
    modified_input: dict[str, Any] | None = None
    message: str | None = None

    @classmethod
    def allow(cls) -> HookResult:
        """Allow tool execution without changes."""
        return cls(action="allow")

    @classmethod
    def block(cls, message: str) -> HookResult:
        """Block tool execution with a reason message."""
        return cls(action="block", message=message)

    @classmethod
    def modify(cls, modified_input: dict[str, Any]) -> HookResult:
        """Allow tool execution with modified input."""
        return cls(action="modify", modified_input=modified_input)


@runtime_checkable
class HookDispatcher(Protocol):
    """Port for dispatching hook events (ISP: exactly 5 methods).

    Implementations iterate registered hooks, apply matcher filtering,
    and aggregate results. ``dispatch_pre_tool`` is fail-closed (an
    enforcement gate — see module docstring); the other 4 methods are
    fail-open on callback exceptions.

    The 5th method ``dispatch_session_event`` handles all session-level
    events (file.edited, session.idle, session.compacted) with a single
    generic dispatch call — ISP compliant (≤5 methods per Protocol).
    """

    async def dispatch_pre_tool(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> HookResult: ...

    async def dispatch_post_tool(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> str | None: ...

    async def dispatch_stop(self, result_text: str) -> None: ...

    async def dispatch_user_prompt(self, prompt: str) -> str: ...

    async def dispatch_session_event(
        self, event: str, payload: dict[str, Any]
    ) -> None: ...


class DefaultHookDispatcher:
    """Default implementation of HookDispatcher backed by HookRegistry.

    Iterates hooks in registration order. Uses fnmatch for tool name matching.

    ``dispatch_pre_tool`` is fail-closed (see module docstring): an exception
    or an unrecognized verdict blocks execution, and a hook that fails
    ``PRE_TOOL_QUARANTINE_THRESHOLD`` times in a row is quarantined (excluded
    from further dispatch, logged). The other dispatch methods are fail-open:
    any exception in a callback → log warning, continue execution.
    """

    #: Consecutive PreToolUse failures (exception or unrecognized verdict)
    #: before a hook is quarantined (excluded from further dispatch).
    PRE_TOOL_QUARANTINE_THRESHOLD = 3

    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry
        self._pre_tool_failure_counts: dict[int, int] = {}
        self._pre_tool_quarantined: set[int] = set()

    async def dispatch_pre_tool(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> HookResult:
        """Dispatch PreToolUse hooks. First block wins; modify chains.

        Multiple modify hooks accumulate: each receives the already-modified
        input from the previous hook. Block stops iteration immediately.

        Supports both HookResult returns and legacy dict format
        (``{"decision": "block", "reason": ...}`` / ``{"continue_": True}``).

        Fail-closed (stage 28 / CONF-01 fix): a hook that raises, or returns
        a verdict the dispatcher cannot recognize, blocks execution instead
        of silently allowing it. A hook quarantined by a prior call (see
        ``_register_pre_tool_failure``) is skipped entirely — as if it were
        not registered — so a persistently broken hook does not wedge every
        future tool call. Zero registered (or all-quarantined/non-matching)
        hooks still allow: quarantine excludes the broken hook, it never
        blocks emptiness.
        """
        current_input = tool_input
        was_modified = False
        for entry in self._registry.get_hooks("PreToolUse"):
            if entry.matcher and not fnmatch(tool_name, entry.matcher):
                continue
            if id(entry) in self._pre_tool_quarantined:
                continue

            try:
                result = await entry.callback(
                    tool_name=tool_name, tool_input=current_input
                )
            except Exception:
                logger.warning(
                    "PreToolUse hook %r raised an exception, blocking execution (fail-closed)",
                    _hook_name(entry.callback),
                    exc_info=True,
                    extra={"hook": _hook_name(entry.callback), "tool_name": tool_name},
                )
                return self._register_pre_tool_failure(
                    entry,
                    "PreToolUse hook failed; execution blocked",
                )

            hook_result = self._coerce_pre_tool_result(result)
            if hook_result is None:
                logger.warning(
                    "PreToolUse hook %r returned an unrecognized verdict %r, blocking execution (fail-closed)",
                    _hook_name(entry.callback),
                    result,
                    extra={"hook": _hook_name(entry.callback), "tool_name": tool_name},
                )
                return self._register_pre_tool_failure(
                    entry,
                    "PreToolUse hook returned an unrecognized verdict; execution blocked",
                )

            # A recognized verdict — the hook is healthy again.
            self._pre_tool_failure_counts.pop(id(entry), None)

            if hook_result.action == "block":
                return hook_result
            if (
                hook_result.action == "modify"
                and hook_result.modified_input is not None
            ):
                current_input = hook_result.modified_input
                was_modified = True

        if was_modified:
            return HookResult.modify(current_input)
        return HookResult.allow()

    def _register_pre_tool_failure(self, entry: Any, reason: str) -> HookResult:
        """Record a PreToolUse failure for ``entry`` and block this call.

        Quarantines the hook (excludes it from future dispatch) once
        ``PRE_TOOL_QUARANTINE_THRESHOLD`` consecutive failures accumulate,
        logging the quarantine event as an error (observable, distinct from
        the per-failure warning above).

        Security: ``reason`` becomes ``HookResult.message``, which is
        caller/model-facing (``ToolExecutor`` JSON-serializes it into the
        tool result). Callers of this method MUST pass a generic, static
        reason — never hook identity/repr — since ``_hook_name`` falls back
        to ``repr(callback)`` for callables without ``__name__`` (e.g.
        ``functools.partial``), which can embed bound-argument secrets.
        Full diagnostics (hook name/repr, exception, verdict) belong in the
        ``logger.warning``/``logger.error`` calls at the call sites, not here.
        """
        key = id(entry)
        count = self._pre_tool_failure_counts.get(key, 0) + 1
        self._pre_tool_failure_counts[key] = count
        if count >= self.PRE_TOOL_QUARANTINE_THRESHOLD:
            self._pre_tool_quarantined.add(key)
            logger.error(
                "PreToolUse hook %r quarantined after %d consecutive failures — excluded from further dispatch",
                _hook_name(entry.callback),
                count,
                extra={
                    "hook": _hook_name(entry.callback),
                    "consecutive_failures": count,
                    "quarantined": True,
                },
            )
        return HookResult.block(reason)

    @staticmethod
    def _coerce_pre_tool_result(result: Any) -> HookResult | None:
        """Convert callback return value to HookResult, or None if unrecognized.

        Recognized formats: HookResult (pass-through); legacy dict
        ``{"decision": "block"|"allow", ...}`` or ``{"continue_": bool}``.

        Anything else — including a bare ``None`` (e.g. a hook that forgot a
        ``return`` statement), an arbitrary object, or a dict without a
        recognized shape — is an *unrecognized verdict*: returns ``None`` so
        the caller can fail closed (REQ-CONF-01-fix). PreToolUse is a gate,
        not a fire-and-forget observer, so silence is not consent.
        """
        if isinstance(result, HookResult):
            return result
        if isinstance(result, dict):
            decision = result.get("decision")
            if decision == "block":
                return HookResult.block(result.get("reason", "Blocked by hook"))
            if decision == "allow":
                return HookResult.allow()
            if "continue_" in result:
                return (
                    HookResult.allow()
                    if result["continue_"]
                    else HookResult.block("Blocked by hook (continue_=False)")
                )
        return None

    async def dispatch_post_tool(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> str | None:
        """Dispatch PostToolUse hooks. Returns modified output or None.

        Supports both string returns and legacy dict format
        (``{"tool_result": "..."}`` / ``{"continue_": True}``).
        """
        modified: str | None = None
        for entry in self._registry.get_hooks("PostToolUse"):
            if entry.matcher and not fnmatch(tool_name, entry.matcher):
                continue
            try:
                # Chain: each hook sees the already-modified output of the
                # previous one (mirrors PreToolUse), so later hooks compose onto
                # earlier modifications instead of clobbering them.
                hook_result = await entry.callback(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=modified if modified is not None else tool_output,
                )
            except Exception:
                logger.warning(
                    "PostToolUse hook %r raised an exception, skipping (fail-open)",
                    _hook_name(entry.callback),
                    exc_info=True,
                )
                continue

            coerced = self._coerce_post_tool_result(hook_result)
            if coerced is not None:
                modified = coerced
        return modified

    @staticmethod
    def _coerce_post_tool_result(result: Any) -> str | None:
        """Convert callback return value to str | None.

        Handles: str (pass-through), dict with tool_result key (legacy),
        dict with continue_ (no-op), None (no-op).
        """
        if result is None:
            return None
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if result.get("continue_"):
                return None
            if "tool_result" in result:
                return str(result["tool_result"])
        return None

    async def dispatch_session_event(self, event: str, payload: dict[str, Any]) -> None:
        """Dispatch a session-level event to all registered callbacks.

        Handles file.edited, session.idle, and session.compacted in a single
        generic method (ISP: keeps HookDispatcher Protocol at ≤5 methods).

        Callbacks receive ``event`` as a keyword arg plus all ``payload`` fields
        as keyword args: ``await callback(event=event, **payload)``.

        Fail-open (REQ-RCA-031): any exception in a callback is logged as a
        warning and execution continues — the run is never aborted by a hook.

        No-op path: when ``get_hooks(event)`` returns an empty list (no hooks
        registered for this event), this method returns immediately without any
        side effects — byte-identical to the pre-Task-5 code path.
        """
        for entry in self._registry.get_hooks(event):
            try:
                await entry.callback(event=event, **payload)
            except Exception:
                logger.warning(
                    "Session hook %r raised an exception for event %r, continuing (fail-open)",
                    _hook_name(entry.callback),
                    event,
                    exc_info=True,
                )

    async def dispatch_stop(self, result_text: str) -> None:
        """Dispatch Stop hooks. Calls all hooks; exceptions are swallowed."""
        for entry in self._registry.get_hooks("Stop"):
            try:
                await entry.callback(result_text=result_text)
            except Exception:
                logger.warning(
                    "Stop hook %r raised an exception, continuing (fail-open)",
                    _hook_name(entry.callback),
                    exc_info=True,
                )

    async def dispatch_user_prompt(self, prompt: str) -> str:
        """Dispatch UserPromptSubmit hooks. Chains prompt transformations."""
        current = prompt
        for entry in self._registry.get_hooks("UserPromptSubmit"):
            try:
                result = await entry.callback(prompt=current)
            except Exception:
                logger.warning(
                    "UserPromptSubmit hook %r raised an exception, keeping current prompt (fail-open)",
                    _hook_name(entry.callback),
                    exc_info=True,
                )
                continue
            if isinstance(result, str):
                current = result
        return current
