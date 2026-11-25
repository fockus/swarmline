"""Verify-before-done: ledger verifiers (application layer).

verify-before-done spec (design.md). This package is deliberately
separate from the crowded ``swarmline.orchestration`` verification
vocabulary (``orchestration.code_verifier.CodeVerifier``,
``orchestration.verification_types.VerificationResult`` — an unrelated,
pre-existing code-QUALITY pipeline). It groups the ledger-facing
:class:`~swarmline.protocols.verification.Verifier` implementations that
verify a :class:`~swarmline.types.VerificationLedger`'s acceptance
criteria before an agent is allowed to finalize as "done".

Application layer: depends only on domain (``swarmline.types``,
``swarmline.protocols.verification``) and stdlib. Must not be imported by
domain.

Public API
----------
LedgerCodeVerifier -- primary, deterministic verifier (Task 2, REQ-004/006)
Predicate          -- ``Callable[[object], Awaitable[tuple[bool, str]]]``
                       alias for a code-criterion predicate
JudgeVerifier      -- optional, advisory-only verifier (Task 3, REQ-007)
JudgeFn            -- ``Callable[[AcceptanceCriterion, object], Awaitable[tuple[bool, str]]]``
                       alias for an injected judge callable; no LLM/infra
                       import lives in this package (see JudgeVerifier docstring)
capture_ledger     -- capture a fresh VerificationLedger from success-criteria
                       strings (Task 5, REQ-002)
criterion_satisfied, non_advisory_results, unmet_criteria, unmet_report
                   -- the I-024 coverage-aware gate rule (H6 supervisor-orchestrator
                      Task 5 fix-cycle 2); the SINGLE source of truth shared by
                      ``verification.gate`` (runtime finalize) and
                      ``orchestration.supervisor.finalize`` (supervisor finalize)
"""

from __future__ import annotations

from swarmline.verification.capture import capture_ledger
from swarmline.verification.coverage import (
    criterion_satisfied,
    non_advisory_results,
    unmet_criteria,
    unmet_report,
)
from swarmline.verification.verifiers import (
    JudgeFn,
    JudgeVerifier,
    LedgerCodeVerifier,
    Predicate,
)

__all__ = [
    "JudgeFn",
    "JudgeVerifier",
    "LedgerCodeVerifier",
    "Predicate",
    "capture_ledger",
    "criterion_satisfied",
    "non_advisory_results",
    "unmet_criteria",
    "unmet_report",
]
