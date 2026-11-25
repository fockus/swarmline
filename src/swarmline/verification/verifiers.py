"""Ledger verifiers — primary deterministic + advisory-judge checks.

verify-before-done spec, Task 2 (REQ-004, REQ-006) + Task 3 (REQ-007).
Grouping module: this file holds :class:`LedgerCodeVerifier` and the
advisory-only :class:`JudgeVerifier` together (design.md — both verifiers
belong to the same small vocabulary and neither warrants its own
single-class file, per the project's "no single-file-per-class" KISS
rule).

NAMING: this class is **``LedgerCodeVerifier``**, not ``CodeVerifier``.
``swarmline.orchestration.code_verifier.CodeVerifier`` already exists — a
5-method Protocol for an unrelated concept (the code-QUALITY pipeline:
verify_contracts/verify_tests_substantive/verify_tests_before_code/
verify_linters/verify_coverage). ``LedgerCodeVerifier`` instead verifies
the ``kind == "code"`` criteria of a :class:`~swarmline.types.VerificationLedger`
against caller-supplied predicates. This mirrors the Task-1 precedent of
renaming ``VerificationResult`` -> ``VerificationOutcome`` to resolve the
same class of vocabulary collision (see I-026 / test_verification_ledger.py).

Application layer: may depend on domain (``swarmline.types``,
``swarmline.protocols.verification``) and stdlib only. Must not be
imported by domain. No heavy infra imports at module level.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from swarmline.types import VerificationLedger, VerificationOutcome

if TYPE_CHECKING:
    from swarmline.types import AcceptanceCriterion

# A code-criterion predicate: given the verify() ``ctx``, returns
# ``(passed, evidence)``. Async so predicates can shell out (pytest run,
# file/schema checks) without blocking the event loop.
Predicate = Callable[[object], Awaitable[tuple[bool, str]]]

# A judge function: given the criterion being assessed and the verify()
# ``ctx``, returns ``(passed, reasoning)``. Async so an LLM-backed judge
# can await a network call without blocking the event loop. This is an
# INJECTED callable, not a class — see :class:`JudgeVerifier` docstring
# for why that is the load-bearing design decision here.
JudgeFn = Callable[["AcceptanceCriterion", object], Awaitable[tuple[bool, str]]]


class LedgerCodeVerifier:
    """Primary, deterministic :class:`~swarmline.protocols.verification.Verifier`.

    Runs a registered async predicate per ``kind == "code"`` criterion
    (resolved by :attr:`AcceptanceCriterion.check_ref`) and records a
    non-advisory :class:`VerificationOutcome` for each. ``kind == "judge"``
    criteria are ignored here — they are handled by the (Task 3) advisory
    ``JudgeVerifier``, never by this class.

    Fail-safe by construction (REQ-006 — deterministic checks are the
    primary gate and must never rubber-stamp an unverifiable criterion):

    - ``check_ref is None`` or not present in the predicate map -> a
      FAILING outcome naming the missing ref. An unverifiable code
      criterion must never silently pass a gate.
    - The predicate raises -> a FAILING outcome carrying the exception in
      ``evidence``. A buggy/flaky predicate must not crash the finalize
      path; it degrades to "blocked", never to "passed" and never to an
      uncaught exception.

    Immutability: ``verify`` never mutates the input ledger. It returns a
    NEW frozen ledger via ``dataclasses.replace`` whose ``results`` is the
    input's ``results`` tuple with the newly computed code outcomes
    APPENDED — existing results (e.g. from a prior ``JudgeVerifier`` pass,
    or from a previous ``LedgerCodeVerifier`` pass) are preserved verbatim.
    This append semantics is what makes ``LedgerCodeVerifier`` and
    ``JudgeVerifier`` composable in either order (design.md).
    """

    def __init__(self, predicates: Mapping[str, Predicate]) -> None:
        self._predicates = predicates

    async def verify(
        self, ledger: VerificationLedger, ctx: object
    ) -> VerificationLedger:
        """Verify *ledger*'s ``kind == "code"`` criteria, returning a new ledger.

        Does not mutate *ledger*. The returned ledger carries the same
        ``criteria`` and the input's ``results`` plus the newly computed
        outcomes appended (see class docstring — append, not replace).
        """
        new_outcomes: list[VerificationOutcome] = []
        for criterion in ledger.criteria:
            if criterion.kind != "code":
                continue
            new_outcomes.append(await self._verify_one(criterion, ctx))

        return dataclasses.replace(ledger, results=ledger.results + tuple(new_outcomes))

    async def _verify_one(
        self, criterion: AcceptanceCriterion, ctx: object
    ) -> VerificationOutcome:
        check_ref = criterion.check_ref
        predicate = self._predicates.get(check_ref) if check_ref is not None else None
        if predicate is None:
            return VerificationOutcome(
                criterion_id=criterion.id,
                passed=False,
                advisory=False,
                evidence=f"no predicate registered for check_ref={check_ref}",
            )

        try:
            passed, evidence = await predicate(ctx)
        except Exception as exc:  # noqa: BLE001 - fail-safe, never crash finalize
            return VerificationOutcome(
                criterion_id=criterion.id,
                passed=False,
                advisory=False,
                evidence=f"predicate raised: {exc}",
            )

        return VerificationOutcome(
            criterion_id=criterion.id,
            passed=passed,
            advisory=False,
            evidence=evidence,
        )


class JudgeVerifier:
    """Optional, advisory-only :class:`~swarmline.protocols.verification.Verifier`.

    Runs an INJECTED :data:`JudgeFn` per ``kind == "judge"`` criterion and
    records a :class:`VerificationOutcome` for each. ``kind == "code"``
    criteria are ignored here — they are handled by :class:`LedgerCodeVerifier`,
    never by this class.

    REQ-007 invariant — advisory, always: every outcome this class
    produces has ``advisory=True``, with NO exception (including when the
    judge itself raises). ``VerificationLedger.gate_passed`` ignores
    advisory results entirely, so a judge — however confident — can never
    by itself flip a criterion to "passed" at the gate level, and can
    never be the sole verifier a gate relies on. This is the
    verifier-local half of scenario 2 (design.md); the other half
    (requiring a deterministic result to exist per criterion before
    trusting ``gate_passed``) is gate WIRING, Task 4, per the Task-1
    CARRY-FORWARD I-024 note — not this class's responsibility.

    DESIGN DECISION — injected ``JudgeFn`` instead of a built-in LLM
    client: the spec requires the LLM dependency to be lazy-imported
    (design.md: "``JudgeVerifier.verify`` — LLM-оценка ... Lazy-import
    LLM-клиента"). Rather than importing an LLM SDK *inside* ``verify()``
    (a weaker, still-present-at-runtime form of laziness), this class
    takes the judge as a constructor-injected callable. The result: the
    ENTIRE ``swarmline.verification`` package — including this module —
    imports ZERO LLM/infra dependencies, at module load OR at call time.
    ``swarmline.verification`` stays pure application-layer (domain +
    stdlib only), matching ``LedgerCodeVerifier``'s existing predicate-map
    pattern exactly (Task 2). The concrete LLM-backed ``JudgeFn`` (the
    thing that actually imports an Anthropic/OpenAI/etc. client) is
    supplied by the caller — Task 4/5 wiring lazy-imports the client
    there, at the infrastructure boundary where such imports belong
    (Clean Architecture: Infrastructure -> Application -> Domain, never
    reversed). This is a strictly stronger property than function-local
    lazy-import and keeps this module trivially unit-testable with plain
    async fakes (see tests/unit/test_judge_verifier.py) with no mocking
    of any LLM SDK required.

    Fail-safe by construction (a judge is a nice-to-have signal, never a
    trust boundary):

    - The injected judge raises -> an advisory FAILING outcome carrying
      the exception in ``evidence``. A judge failure must never affect
      the gate and must never crash the finalize path.

    Immutability: ``verify`` never mutates the input ledger. It returns a
    NEW frozen ledger via ``dataclasses.replace`` whose ``results`` is the
    input's ``results`` tuple with the newly computed judge outcomes
    APPENDED — mirrors :class:`LedgerCodeVerifier` exactly, which is what
    makes the two composable in either order (design.md).
    """

    def __init__(self, judge: JudgeFn) -> None:
        self._judge = judge

    async def verify(
        self, ledger: VerificationLedger, ctx: object
    ) -> VerificationLedger:
        """Verify *ledger*'s ``kind == "judge"`` criteria, returning a new ledger.

        Does not mutate *ledger*. The returned ledger carries the same
        ``criteria`` and the input's ``results`` plus the newly computed
        outcomes appended (see class docstring — append, not replace).
        Every appended outcome has ``advisory=True`` (REQ-007).
        """
        new_outcomes: list[VerificationOutcome] = []
        for criterion in ledger.criteria:
            if criterion.kind != "judge":
                continue
            new_outcomes.append(await self._verify_one(criterion, ctx))

        return dataclasses.replace(ledger, results=ledger.results + tuple(new_outcomes))

    async def _verify_one(
        self, criterion: AcceptanceCriterion, ctx: object
    ) -> VerificationOutcome:
        try:
            passed, reasoning = await self._judge(criterion, ctx)
        except Exception as exc:  # noqa: BLE001 - fail-safe, never crash finalize
            return VerificationOutcome(
                criterion_id=criterion.id,
                passed=False,
                advisory=True,
                evidence=f"judge raised: {exc}",
            )

        return VerificationOutcome(
            criterion_id=criterion.id,
            passed=passed,
            advisory=True,
            evidence=reasoning,
        )
