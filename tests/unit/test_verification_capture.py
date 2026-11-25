"""Tests for ledger capture from success_criteria (REQ-002).

verify-before-done spec, Task 5 (REQ-002).
TDD: RED phase — written BEFORE ``swarmline.verification.capture`` and
``swarmline.runtime.thin.verification_capture`` exist.

Covers two capture primitives:

- ``swarmline.verification.capture.capture_ledger`` (application layer,
  domain-only imports) — the generic "list of criterion strings ->
  VerificationLedger" primitive.
- ``swarmline.runtime.thin.verification_capture.ledger_from_plan``
  (infrastructure layer, PlanSchema-coupled) — flattens every step's
  ``success_criteria`` into one ledger with stable per-step ids.
"""

from __future__ import annotations

from swarmline.runtime.thin.schemas import PlanSchema, PlanStep
from swarmline.runtime.thin.verification_capture import ledger_from_plan
from swarmline.types import VerificationLedger
from swarmline.verification.capture import capture_ledger


# ---------------------------------------------------------------------------
# capture_ledger — generic primitive (application layer, domain-only)
# ---------------------------------------------------------------------------


class TestCaptureLedgerPrimitive:
    def test_capture_ledger_maps_id_check_ref_and_kind(self) -> None:
        ledger = capture_ledger(["all tests pass", "no linter warnings"])

        assert isinstance(ledger, VerificationLedger)
        assert ledger.results == ()
        assert len(ledger.criteria) == 2

        c0, c1 = ledger.criteria
        assert c0.id == "sc-0"
        assert c0.check_ref == "sc-0"
        assert c0.description == "all tests pass"
        assert c0.kind == "code"
        assert c1.id == "sc-1"
        assert c1.check_ref == "sc-1"
        assert c1.description == "no linter warnings"

    def test_capture_ledger_honors_custom_id_prefix_and_kind(self) -> None:
        ledger = capture_ledger(["reviewed"], id_prefix="task42", kind="judge")

        (criterion,) = ledger.criteria
        assert criterion.id == "task42-0"
        assert criterion.check_ref == "task42-0"
        assert criterion.kind == "judge"

    def test_capture_ledger_empty_criteria_yields_empty_ledger(self) -> None:
        ledger = capture_ledger([])

        assert ledger.criteria == ()
        assert ledger.results == ()


# ---------------------------------------------------------------------------
# ledger_from_plan — plan adapter (infrastructure layer, PlanSchema-coupled)
# ---------------------------------------------------------------------------


def _plan(*, steps: list[PlanStep]) -> PlanSchema:
    return PlanSchema(goal="ship the feature", steps=steps)


class TestLedgerFromPlan:
    def test_ledger_captured_from_plan_success_criteria(self) -> None:
        """REQ-002: a plan's success_criteria are captured into a ledger.

        Content-branched, not tautological: two steps, DIFFERENT criteria
        counts and text, asserted individually by index/id/description.
        """
        plan = _plan(
            steps=[
                PlanStep(
                    id="step-1",
                    title="write code",
                    success_criteria=["all tests pass", "no linter warnings"],
                ),
                PlanStep(
                    id="step-2",
                    title="ship it",
                    success_criteria=["deployed to staging"],
                ),
            ]
        )

        ledger = ledger_from_plan(plan)

        assert isinstance(ledger, VerificationLedger)
        assert ledger.results == ()
        assert len(ledger.criteria) == 3

        c0, c1, c2 = ledger.criteria
        assert c0.id == "step-1:sc0"
        assert c0.check_ref == "step-1:sc0"
        assert c0.description == "all tests pass"
        assert c0.kind == "code"

        assert c1.id == "step-1:sc1"
        assert c1.check_ref == "step-1:sc1"
        assert c1.description == "no linter warnings"
        assert c1.kind == "code"

        assert c2.id == "step-2:sc0"
        assert c2.check_ref == "step-2:sc0"
        assert c2.description == "deployed to staging"
        assert c2.kind == "code"

    def test_ledger_from_plan_honors_custom_kind(self) -> None:
        plan = _plan(
            steps=[
                PlanStep(id="s1", title="t", success_criteria=["looks clean"]),
            ]
        )

        ledger = ledger_from_plan(plan, kind="judge")

        (criterion,) = ledger.criteria
        assert criterion.kind == "judge"

    def test_ledger_from_plan_empty_success_criteria_yields_empty_ledger(self) -> None:
        """REQ-009: a plan whose steps carry no success_criteria at all captures
        an empty ledger — the gate becomes a no-op downstream."""
        plan = _plan(
            steps=[
                PlanStep(id="s1", title="no criteria here"),
                PlanStep(id="s2", title="also none"),
            ]
        )

        ledger = ledger_from_plan(plan)

        assert ledger.criteria == ()
        assert ledger.results == ()
