# Attribution: adapted from hermes (MIT)
# Upstream file: hermes/lint_delta.py (H2 baseline-subtraction)
# Copyright: (c) Nous Research and contributors
# Changes: rewritten as an async DeltaLinter Protocol over a pluggable lint
#          callable; LintDelta expressed as a frozen value object; the
#          "still-broken-not-new" annotation derived from set arithmetic on the
#          before/after lint outputs instead of hermes' inline diffing.
"""Lint-delta — surface only edit-introduced lint errors via baseline subtraction.

The core idea (hermes H2): lint the *before* content and the *after* content,
then subtract the pre-existing error set from the new one. Only errors absent
in ``before`` but present in ``after`` are genuinely *introduced* by the edit.
A pre-existing error that *persists* is annotated ``still_broken_not_new`` so the
agent is informed without being blamed for a fault it did not create.

Framework-free: depends only on a pluggable ``LintCallable`` (``async (content)
-> tuple[str, ...]``). No infrastructure imports — Clean Architecture domain.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# A pluggable lint runner: maps file content → tuple of error lines.
# Kept as a plain callable (not VerificationRunnerPort) because the runner port
# is session-scoped and cannot lint arbitrary before/after content snapshots.
LintCallable = Callable[[str], Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, slots=True)
class LintDelta:
    """Result of baseline-subtraction between a before/after lint run.

    Attributes:
        new_errors: Error lines present in ``after`` but absent in ``before`` —
                    the errors the edit *introduced*.
        preexisting_filtered: Count of error lines present in ``before`` that
                              were excluded from ``new_errors`` (filtered out).
        still_broken_not_new: True when at least one pre-existing error persists
                              in ``after`` (broken before, broken still — not new).
        summary: Human-readable one-line summary for the tool-result feedback.
    """

    new_errors: tuple[str, ...]
    preexisting_filtered: int
    still_broken_not_new: bool
    summary: str


@runtime_checkable
class DeltaLinter(Protocol):
    """Port: compute the lint delta introduced by an edit (before → after)."""

    async def diff(self, path: str, before: str, after: str) -> LintDelta: ...


class BaselineSubtractionLinter:
    """Concrete ``DeltaLinter`` using baseline subtraction (hermes H2).

    Runs the injected lint callable on the ``before`` and ``after`` content,
    then subtracts the pre-existing error set so only edit-introduced errors
    surface. A pre-existing error that persists is flagged still-broken-not-new.
    """

    def __init__(self, lint: LintCallable) -> None:
        self._lint = lint

    async def diff(self, path: str, before: str, after: str) -> LintDelta:
        before_errors = await self._lint(before)
        after_errors = await self._lint(after)

        # Multiset (not set) subtraction: a line in `after` is "pre-existing" only
        # as many times as it appeared in `before`. The 2nd identical occurrence an
        # edit introduces is genuinely new — plain set membership would hide it.
        remaining = Counter(before_errors)
        new_errors_list: list[str] = []
        matched = 0
        for line in after_errors:  # order-preserving on `after`
            if remaining.get(line, 0) > 0:
                remaining[line] -= 1
                matched += 1
            else:
                new_errors_list.append(line)
        new_errors = tuple(new_errors_list)
        # A pre-existing error persists when ≥1 before-occurrence reappears in after.
        still_broken_not_new = matched > 0
        preexisting_filtered = matched

        summary = self._summarize(
            path=path,
            new_count=len(new_errors),
            preexisting_filtered=preexisting_filtered,
            still_broken_not_new=still_broken_not_new,
        )
        return LintDelta(
            new_errors=new_errors,
            preexisting_filtered=preexisting_filtered,
            still_broken_not_new=still_broken_not_new,
            summary=summary,
        )

    @staticmethod
    def _summarize(
        *,
        path: str,
        new_count: int,
        preexisting_filtered: int,
        still_broken_not_new: bool,
    ) -> str:
        if new_count == 0 and not still_broken_not_new:
            return f"{path}: lint clean (no edit-introduced errors)"
        parts: list[str] = []
        if new_count:
            noun = "error" if new_count == 1 else "errors"
            parts.append(f"{new_count} new lint {noun} introduced by this edit")
        if still_broken_not_new:
            parts.append(
                f"{preexisting_filtered} pre-existing still-broken-not-new "
                "(present before the edit — not introduced)"
            )
        return f"{path}: " + "; ".join(parts)
