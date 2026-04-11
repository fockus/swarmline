"""Guardrails — pre/post-LLM safety checks.

Provides:
- GuardrailContext: immutable context for guardrail checks
- GuardrailResult: result of a guardrail check (pass/fail/tripwire)
- Guardrail: base protocol for all guardrails
- InputGuardrail / OutputGuardrail: marker protocols
- ContentLengthGuardrail: rejects text exceeding max_length
- RegexGuardrail: rejects text matching forbidden patterns
- CallerAllowlistGuardrail: rejects calls from unknown session_ids
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Context & Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardrailContext:
    """Immutable context passed to every guardrail check."""

    session_id: str | None = None
    model: str = ""
    turn: int = 0


@dataclass
class GuardrailResult:
    """Result of a guardrail check.

    Attributes:
        passed: True if the check passed.
        reason: Human-readable explanation when check fails.
        tripwire: If True, the failure is non-recoverable (hard stop).
    """

    passed: bool
    reason: str | None = None
    tripwire: bool = False


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class Guardrail(Protocol):
    """Base protocol for all guardrails."""

    async def check(self, context: GuardrailContext, text: str) -> GuardrailResult: ...


@runtime_checkable
class InputGuardrail(Guardrail, Protocol):
    """Marker for input guardrails -- checked before LLM call."""


@runtime_checkable
class OutputGuardrail(Guardrail, Protocol):
    """Marker for output guardrails -- checked after LLM response."""


# ---------------------------------------------------------------------------
# Builtin guardrails
# ---------------------------------------------------------------------------


class ContentLengthGuardrail:
    """Rejects input/output exceeding max_length characters."""

    def __init__(self, max_length: int = 100_000) -> None:
        self._max_length = max_length

    async def check(self, context: GuardrailContext, text: str) -> GuardrailResult:
        if len(text) <= self._max_length:
            return GuardrailResult(passed=True)
        return GuardrailResult(
            passed=False,
            reason=f"Text length {len(text)} exceeds limit {self._max_length}",
        )


class RegexGuardrail:
    """Rejects text matching any of the forbidden patterns."""

    def __init__(
        self,
        patterns: list[str],
        reason: str = "Forbidden pattern matched",
    ) -> None:
        self._compiled = [re.compile(p) for p in patterns]
        self._reason = reason

    async def check(self, context: GuardrailContext, text: str) -> GuardrailResult:
        for pattern in self._compiled:
            if pattern.search(text):
                return GuardrailResult(passed=False, reason=self._reason)
        return GuardrailResult(passed=True)


class CallerAllowlistGuardrail:
    """Rejects calls from session_ids not in allowlist.

    If session_id is None, the check fails with tripwire=True
    (unidentified caller is a security concern).
    """

    def __init__(self, allowed_session_ids: set[str]) -> None:
        self._allowed = frozenset(allowed_session_ids)

    async def check(self, context: GuardrailContext, text: str) -> GuardrailResult:
        if context.session_id is None:
            return GuardrailResult(
                passed=False,
                reason="No session_id provided",
                tripwire=True,
            )
        if context.session_id not in self._allowed:
            return GuardrailResult(
                passed=False,
                reason=f"Session '{context.session_id}' not in allowlist",
            )
        return GuardrailResult(passed=True)
