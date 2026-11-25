"""Tests for LintDelta VO + DeltaLinter (baseline-subtraction).

Verifies that only edit-introduced lint errors surface and that a pre-existing
error which persists is annotated as "still-broken-not-new" rather than counted
as a newly introduced error.
"""

from __future__ import annotations

import pytest
from swarmline.orchestration.lint_delta import (
    BaselineSubtractionLinter,
    LintDelta,
)


def _lines(*errs: str) -> tuple[str, ...]:
    return tuple(errs)


class TestLintDeltaValueObject:
    def test_lint_delta_is_frozen(self) -> None:
        delta = LintDelta(
            new_errors=("E1",),
            preexisting_filtered=0,
            still_broken_not_new=False,
            summary="x",
        )
        with pytest.raises(Exception):
            delta.new_errors = ()  # type: ignore[misc]


class TestBaselineSubtractionLinter:
    @pytest.mark.asyncio
    async def test_lint_delta_filters_preexisting(self) -> None:
        """A pre-existing error in `before` is NOT reported; only a new one in `after`."""
        # before already has E_OLD; after has E_OLD (still) + E_NEW (introduced).
        responses = {
            "BEFORE": _lines("file.py:1: E_OLD undefined name"),
            "AFTER": _lines(
                "file.py:1: E_OLD undefined name",
                "file.py:5: E_NEW unused import",
            ),
        }

        async def lint(content: str) -> tuple[str, ...]:
            return responses["BEFORE" if content == "before-src" else "AFTER"]

        linter = BaselineSubtractionLinter(lint)

        delta = await linter.diff("file.py", "before-src", "after-src")

        assert delta.new_errors == ("file.py:5: E_NEW unused import",)
        assert "E_OLD" not in "".join(delta.new_errors)
        assert delta.preexisting_filtered == 1

    @pytest.mark.asyncio
    async def test_lint_delta_still_broken_not_new_annotated(self) -> None:
        """A pre-existing error that persists is annotated still-broken-not-new."""
        # before == after lint output: the only error pre-exists and still persists.
        same = _lines("file.py:1: E_OLD undefined name")

        async def lint(content: str) -> tuple[str, ...]:
            return same

        linter = BaselineSubtractionLinter(lint)

        delta = await linter.diff("file.py", "before-src", "after-src")

        assert delta.new_errors == ()
        assert delta.still_broken_not_new is True
        assert delta.preexisting_filtered == 1
        assert "still-broken" in delta.summary.lower()

    @pytest.mark.asyncio
    async def test_lint_delta_no_errors_clean(self) -> None:
        """No errors before or after → empty delta, no still-broken flag."""

        async def lint(content: str) -> tuple[str, ...]:
            return ()

        linter = BaselineSubtractionLinter(lint)

        delta = await linter.diff("file.py", "before-src", "after-src")

        assert delta.new_errors == ()
        assert delta.preexisting_filtered == 0
        assert delta.still_broken_not_new is False

    @pytest.mark.asyncio
    async def test_lint_delta_duplicate_line_second_occurrence_is_new(self) -> None:
        """Multiset subtraction: a 2nd identical occurrence the edit adds is NEW.

        Regression — plain set membership hid it (before={'E'} ⊇ both 'E' lines).
        before has one 'E'; after has two 'E' → exactly one is edit-introduced.
        """
        responses = {
            "before-src": _lines("file.py:1: E dup"),
            "after-src": _lines("file.py:1: E dup", "file.py:1: E dup"),
        }

        async def lint(content: str) -> tuple[str, ...]:
            return responses[content]

        linter = BaselineSubtractionLinter(lint)

        delta = await linter.diff("file.py", "before-src", "after-src")

        assert delta.new_errors == ("file.py:1: E dup",)
        assert delta.preexisting_filtered == 1
        assert delta.still_broken_not_new is True

    @pytest.mark.asyncio
    async def test_lint_delta_fixed_preexisting_not_still_broken(self) -> None:
        """A pre-existing error fixed by the edit → not still-broken, no new errors."""
        responses = {
            "before-src": _lines("file.py:1: E_OLD undefined name"),
            "after-src": _lines(),
        }

        async def lint(content: str) -> tuple[str, ...]:
            return responses[content]

        linter = BaselineSubtractionLinter(lint)

        delta = await linter.diff("file.py", "before-src", "after-src")

        assert delta.new_errors == ()
        assert delta.still_broken_not_new is False
        assert delta.preexisting_filtered == 0
