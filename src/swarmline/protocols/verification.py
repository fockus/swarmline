"""Verifier Protocol — grounds "done" in an external check, not self-report.

verify-before-done spec, Task 1 (REQ-001, REQ-003, REQ-007). Mirrors the
ADR behind :class:`~swarmline.protocols.external_signal.ExternalSignal`
(design.md; arxiv 2310.01798: intrinsic self-correction without an
external signal does not reliably work). Here the signal is a
:class:`~swarmline.types.VerificationLedger` of acceptance criteria fixed
BEFORE execution; ``verify`` fills in results, it never lets the model
declare its own criteria met.

Domain layer: zero external dependencies (stdlib + swarmline domain types
only). ISP: exactly 1 method (verify). The ``ctx`` parameter deliberately
stays un-annotated (``object``) rather than importing ``KernelContext`` —
unlike ``ExternalSignal.evaluate``, a ``Verifier`` (e.g. ``CodeVerifier``
running predicates against the filesystem/process) is not necessarily tied
to a kernel loop, so no domain-safe type currently fits; introducing one
speculatively would violate YAGNI. Revisit once Task 2/3 concrete
verifiers reveal what ``ctx`` actually needs to carry.

Usage::

    class AlwaysPassVerifier:
        async def verify(self, ledger: VerificationLedger, ctx: object) -> VerificationLedger:
            results = tuple(
                VerificationOutcome(
                    criterion_id=c.id, passed=True, advisory=False, evidence="ok"
                )
                for c in ledger.criteria
            )
            return VerificationLedger(criteria=ledger.criteria, results=results)

    from swarmline.protocols import Verifier
    assert isinstance(AlwaysPassVerifier(), Verifier)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from swarmline.types import VerificationLedger


@runtime_checkable
class Verifier(Protocol):
    """Evaluates a ledger's criteria and returns a NEW ledger with results.

    Implementations: ``CodeVerifier`` (primary, deterministic — Task 2),
    ``JudgeVerifier`` (optional, advisory-only — Task 3). ISP: exactly 1
    method — the verdict-producing behaviour is one thing; ledger capture
    (Task 5) and gate wiring (Task 4) live elsewhere.
    """

    async def verify(
        self, ledger: VerificationLedger, ctx: object
    ) -> VerificationLedger:
        """Verify *ledger*'s criteria, returning a new ledger with results filled in.

        Must not mutate *ledger* (frozen-dataclass convention across
        swarmline): the returned ledger carries the same ``criteria`` plus
        the (possibly extended) ``results`` tuple.
        """
        ...  # pragma: no cover
