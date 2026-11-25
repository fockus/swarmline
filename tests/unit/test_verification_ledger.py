"""Tests for verification-ledger domain types + Verifier Protocol.

verify-before-done spec, Task 1 (REQ-001, REQ-003, REQ-007).
TDD: RED phase — tests written BEFORE implementation.

NOTE: named ``test_verification_ledger.py`` (not ``test_verification_types.py``)
because that filename is already taken by tests for the unrelated
``swarmline.orchestration.verification_types`` (code-verification-pipeline)
module. See ``swarmline.types.VerificationLedger`` / ``AcceptanceCriterion``
/ ``VerificationOutcome`` for the domain types under test here.

The domain type here is named ``VerificationOutcome`` (not
``VerificationResult``) precisely to avoid colliding with the pre-existing,
unrelated ``swarmline.orchestration.verification_types.VerificationResult``
(different fields/purpose, part of the code-verification pipeline). The
collision is resolved by this naming choice.
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError

import pytest


# ---------------------------------------------------------------------------
# AcceptanceCriterion / VerificationOutcome / VerificationLedger — frozen
# ---------------------------------------------------------------------------


class TestTypesFrozen:
    """test_types_frozen — mutating any field raises FrozenInstanceError."""

    def test_acceptance_criterion_frozen(self) -> None:
        from swarmline.types import AcceptanceCriterion

        criterion = AcceptanceCriterion(id="c1", description="tests pass", kind="code")
        with pytest.raises(FrozenInstanceError):
            criterion.description = "mutated"  # type: ignore[misc]

    def test_verification_outcome_frozen(self) -> None:
        from swarmline.types import VerificationOutcome

        result = VerificationOutcome(
            criterion_id="c1", passed=True, advisory=False, evidence="ok"
        )
        with pytest.raises(FrozenInstanceError):
            result.passed = False  # type: ignore[misc]

    def test_verification_ledger_frozen(self) -> None:
        from swarmline.types import VerificationLedger

        ledger = VerificationLedger()
        with pytest.raises(FrozenInstanceError):
            ledger.criteria = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AcceptanceCriterion — construction / defaults
# ---------------------------------------------------------------------------


class TestAcceptanceCriterion:
    def test_create_with_check_ref(self) -> None:
        from swarmline.types import AcceptanceCriterion

        criterion = AcceptanceCriterion(
            id="c1", description="all tests pass", kind="code", check_ref="pytest -q"
        )
        assert criterion.id == "c1"
        assert criterion.description == "all tests pass"
        assert criterion.kind == "code"
        assert criterion.check_ref == "pytest -q"

    def test_check_ref_defaults_to_none(self) -> None:
        from swarmline.types import AcceptanceCriterion

        criterion = AcceptanceCriterion(id="c2", description="looks good", kind="judge")
        assert criterion.check_ref is None


# ---------------------------------------------------------------------------
# VerificationLedger.gate_passed — REQ-007
# ---------------------------------------------------------------------------


class TestLedgerGatePassed:
    def test_ledger_gate_passed_ignores_advisory_results(self) -> None:
        """REQ-007: a failing ADVISORY result never blocks the gate."""
        from swarmline.types import (
            AcceptanceCriterion,
            VerificationLedger,
            VerificationOutcome,
        )

        criteria = (
            AcceptanceCriterion(id="c1", description="tests pass", kind="code"),
            AcceptanceCriterion(id="c2", description="looks clean", kind="judge"),
        )
        results = (
            VerificationOutcome(
                criterion_id="c1", passed=True, advisory=False, evidence="ok"
            ),
            VerificationOutcome(
                criterion_id="c2", passed=False, advisory=True, evidence="judge says no"
            ),
        )
        ledger = VerificationLedger(criteria=criteria, results=results)

        assert ledger.gate_passed is True

    def test_ledger_gate_passed_false_when_non_advisory_result_fails(self) -> None:
        """Mirror case: a failing NON-advisory result blocks the gate."""
        from swarmline.types import (
            AcceptanceCriterion,
            VerificationLedger,
            VerificationOutcome,
        )

        criteria = (
            AcceptanceCriterion(id="c1", description="tests pass", kind="code"),
        )
        results = (
            VerificationOutcome(
                criterion_id="c1",
                passed=False,
                advisory=False,
                evidence="2 tests failed",
            ),
        )
        ledger = VerificationLedger(criteria=criteria, results=results)

        assert ledger.gate_passed is False

    def test_ledger_gate_passed_true_when_all_non_advisory_pass(self) -> None:
        from swarmline.types import (
            AcceptanceCriterion,
            VerificationLedger,
            VerificationOutcome,
        )

        criteria = (
            AcceptanceCriterion(id="c1", description="tests pass", kind="code"),
            AcceptanceCriterion(id="c2", description="lint clean", kind="code"),
        )
        results = (
            VerificationOutcome(
                criterion_id="c1", passed=True, advisory=False, evidence="ok"
            ),
            VerificationOutcome(
                criterion_id="c2", passed=True, advisory=False, evidence="ok"
            ),
        )
        ledger = VerificationLedger(criteria=criteria, results=results)

        assert ledger.gate_passed is True

    def test_ledger_gate_passed_true_on_empty_ledger(self) -> None:
        """Vacuous case: no criteria, no results — gate_passed is trivially True.

        The opt-in no-op for an empty/disabled ledger at finalization time
        (REQ-008/REQ-009) is gate WIRING (Task 4), not this property.
        """
        from swarmline.types import VerificationLedger

        ledger = VerificationLedger()

        assert ledger.gate_passed is True
        assert ledger.failed == ()


# ---------------------------------------------------------------------------
# VerificationLedger.failed
# ---------------------------------------------------------------------------


class TestLedgerFailed:
    def test_ledger_failed_lists_unmet_non_advisory(self) -> None:
        """failed contains exactly the non-advisory failed results."""
        from swarmline.types import (
            AcceptanceCriterion,
            VerificationLedger,
            VerificationOutcome,
        )

        criteria = (
            AcceptanceCriterion(id="c1", description="tests pass", kind="code"),
            AcceptanceCriterion(id="c2", description="lint clean", kind="code"),
            AcceptanceCriterion(id="c3", description="looks good", kind="judge"),
        )
        passing_non_advisory = VerificationOutcome(
            criterion_id="c1", passed=True, advisory=False, evidence="ok"
        )
        failing_non_advisory = VerificationOutcome(
            criterion_id="c2", passed=False, advisory=False, evidence="lint error"
        )
        failing_advisory = VerificationOutcome(
            criterion_id="c3", passed=False, advisory=True, evidence="judge unsure"
        )
        ledger = VerificationLedger(
            criteria=criteria,
            results=(passing_non_advisory, failing_non_advisory, failing_advisory),
        )

        assert ledger.failed == (failing_non_advisory,)

    def test_ledger_failed_empty_when_nothing_failed(self) -> None:
        from swarmline.types import (
            AcceptanceCriterion,
            VerificationLedger,
            VerificationOutcome,
        )

        criteria = (
            AcceptanceCriterion(id="c1", description="tests pass", kind="code"),
        )
        results = (
            VerificationOutcome(
                criterion_id="c1", passed=True, advisory=False, evidence="ok"
            ),
        )
        ledger = VerificationLedger(criteria=criteria, results=results)

        assert ledger.failed == ()


# ---------------------------------------------------------------------------
# Verifier Protocol — domain, @runtime_checkable, 1 method
# ---------------------------------------------------------------------------


class TestVerifierProtocol:
    def test_verifier_is_runtime_checkable(self) -> None:
        from swarmline.protocols.verification import Verifier

        assert getattr(Verifier, "_is_runtime_protocol", False) is True

    def test_conforming_class_passes_isinstance(self) -> None:
        from swarmline.protocols import Verifier
        from swarmline.types import VerificationLedger

        class DummyVerifier:
            async def verify(
                self, ledger: VerificationLedger, ctx: object
            ) -> VerificationLedger:
                return ledger

        assert isinstance(DummyVerifier(), Verifier)

    def test_non_conforming_class_fails_isinstance(self) -> None:
        from swarmline.protocols import Verifier

        class NotAVerifier:
            def unrelated(self) -> None:
                pass

        assert not isinstance(NotAVerifier(), Verifier)

    def test_verifier_reexported_from_protocols_package(self) -> None:
        from swarmline.protocols import Verifier as ReExported
        from swarmline.protocols.verification import Verifier as Direct

        assert ReExported is Direct


# ---------------------------------------------------------------------------
# Domain purity — zero external deps (stdlib + swarmline only)
# ---------------------------------------------------------------------------


class TestDomainPurity:
    def test_verification_protocol_module_has_no_third_party_imports(self) -> None:
        import swarmline.protocols.verification as mod

        source = inspect.getsource(mod)
        assert "import anthropic" not in source
        assert "import openai" not in source
        assert "import structlog" not in source

    def test_types_module_has_no_third_party_imports(self) -> None:
        import swarmline.types as mod

        source = inspect.getsource(mod)
        # types.py is domain-only: only stdlib + swarmline imports at module level.
        for line in source.splitlines():
            stripped = line.strip()
            if (
                stripped.startswith(("import ", "from "))
                and "swarmline" not in stripped
            ):
                assert stripped.split()[1].split(".")[0] in {
                    "__future__",
                    "collections",
                    "dataclasses",
                    "typing",
                }, f"unexpected non-stdlib import in domain module: {stripped}"
