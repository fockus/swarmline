"""Tests for the contract gate: per-criterion routing + gate-repair budget.

TDD Task 6 of the autopilot-orchestrator spec (Epic G). Covers REQ-016,
REQ-017, REQ-018, REQ-009. Uses offline stub scorer/judge/repair + a REAL
ApprovalGate wired to `AlwaysDenyPolicy` and a stub callback — no network
calls.
"""

from __future__ import annotations

from swarmline.eval.types import EvalCase, ScorerResult
from swarmline.hitl.gate import ApprovalGate
from swarmline.hitl.policies import AlwaysDenyPolicy
from swarmline.hitl.types import ApprovalRequest, ApprovalResponse
from swarmline.orchestration.autopilot.gate import RoutingContractGate
from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    OutputContract,
)


def _det_criterion(
    id_: str = "crit-det", verifier: str = "unit_scorer"
) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=id_, description="Output contains X", kind="deterministic", verifier=verifier
    )


def _subj_criterion(
    id_: str = "crit-subj", verifier: str = "reviewer"
) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=id_, description="Tone is professional", kind="subjective", verifier=verifier
    )


class _StubScorer:
    """Offline stub Scorer — returns queued results in order, repeats the last."""

    def __init__(self, name: str, results: list[ScorerResult]) -> None:
        self._name = name
        self._queue = list(results)
        self.calls: list[EvalCase] = []

    @property
    def name(self) -> str:
        return self._name

    async def score(self, case: EvalCase, output: str) -> ScorerResult:
        self.calls.append(case)
        if len(self._queue) > 1:
            return self._queue.pop(0)
        return self._queue[0]


class _StubJudge:
    """Offline stub SubjectiveJudge — returns a fixed verdict, records calls."""

    def __init__(self, verdict: tuple[bool, str]) -> None:
        self._verdict = verdict
        self.calls: list[AcceptanceCriterion] = []

    async def judge(
        self, criterion: AcceptanceCriterion, artifacts: dict[str, str]
    ) -> tuple[bool, str]:
        self.calls.append(criterion)
        return self._verdict


class _StubRepair:
    """Offline stub RepairCallable — returns queued artifacts, records calls."""

    def __init__(self, results: list[dict[str, str]]) -> None:
        self._queue = list(results)
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    async def __call__(
        self, unmet_ids: tuple[str, ...], artifacts: dict[str, str]
    ) -> dict[str, str]:
        self.calls.append((unmet_ids, artifacts))
        if self._queue:
            return self._queue.pop(0)
        return artifacts


class _StubApprovalCallback:
    """Records calls and always denies — exercises the real ApprovalGate."""

    def __init__(self) -> None:
        self.calls: list[ApprovalRequest] = []

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        self.calls.append(request)
        return ApprovalResponse(approved=False, reason="human declined")


async def test_gate_passes_when_all_criteria_pass() -> None:
    """All criteria (deterministic + subjective) pass -> verdict passed, no escalation."""
    # Arrange
    det = _det_criterion()
    subj = _subj_criterion()
    contract = OutputContract(deliverables=("out.txt",), criteria=(det, subj))
    scorer = _StubScorer("unit_scorer", [ScorerResult(score=1.0, reason="ok")])
    judge = _StubJudge((True, "reads well"))
    callback = _StubApprovalCallback()
    approval_gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=judge,
        approval_gate=approval_gate,
    )

    # Act
    verdict = await gate.evaluate({"file": "X present"}, contract, max_gate_repair=3)

    # Assert
    assert verdict.passed is True
    assert verdict.failures == ()
    assert callback.calls == []


async def test_gate_routes_deterministic_to_scorer_and_subjective_to_judge() -> None:
    """A deterministic criterion is routed to its scorer; a subjective one to the judge."""
    # Arrange
    det = _det_criterion()
    subj = _subj_criterion()
    contract = OutputContract(deliverables=("out.txt",), criteria=(det, subj))
    scorer = _StubScorer("unit_scorer", [ScorerResult(score=1.0, reason="ok")])
    judge = _StubJudge((True, "reads well"))
    callback = _StubApprovalCallback()
    approval_gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=judge,
        approval_gate=approval_gate,
    )

    # Act
    verdict = await gate.evaluate({"file": "X present"}, contract, max_gate_repair=3)

    # Assert
    assert verdict.passed is True
    assert len(scorer.calls) == 1
    assert len(judge.calls) == 1
    assert judge.calls[0].id == "crit-subj"


async def test_gate_repairs_then_passes_within_budget() -> None:
    """First attempt fails; repair is invoked; second attempt passes."""
    # Arrange
    det = _det_criterion()
    contract = OutputContract(deliverables=("out.txt",), criteria=(det,))
    scorer = _StubScorer(
        "unit_scorer",
        [
            ScorerResult(score=0.0, reason="missing"),
            ScorerResult(score=1.0, reason="ok"),
        ],
    )
    judge = _StubJudge((True, "n/a"))
    callback = _StubApprovalCallback()
    approval_gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    repair = _StubRepair([{"file": "X present now"}])
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=judge,
        approval_gate=approval_gate,
        repair=repair,
    )

    # Act
    verdict = await gate.evaluate({"file": "X missing"}, contract, max_gate_repair=3)

    # Assert
    assert verdict.passed is True
    assert len(repair.calls) == 1
    assert callback.calls == []


async def test_gate_exhausts_budget_then_escalates() -> None:
    """Criteria always fail and there is no repair -> budget exhausted -> HITL escalation."""
    # Arrange
    det = _det_criterion()
    contract = OutputContract(deliverables=("out.txt",), criteria=(det,))
    scorer = _StubScorer("unit_scorer", [ScorerResult(score=0.0, reason="missing")])
    judge = _StubJudge((True, "n/a"))
    callback = _StubApprovalCallback()
    approval_gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=judge,
        approval_gate=approval_gate,
        repair=None,
    )

    # Act
    verdict = await gate.evaluate({"file": "X missing"}, contract, max_gate_repair=3)

    # Assert
    assert verdict.passed is False
    assert len(callback.calls) == 1
    assert verdict.failures == ("crit-det",)


async def test_gate_repair_on_final_attempt_is_evaluated_not_escalated() -> None:
    """A within-budget repair on the LAST attempt is rechecked, not falsely escalated.

    Regression: with ``max_gate_repair=1`` the single repair's artifacts must
    be re-evaluated; the off-by-one bug called repair then escalated without
    checking the fixed result.
    """
    # Arrange
    det = _det_criterion()
    contract = OutputContract(deliverables=("out.txt",), criteria=(det,))
    scorer = _StubScorer(
        "unit_scorer",
        [
            ScorerResult(score=0.0, reason="missing"),
            ScorerResult(score=1.0, reason="ok"),
        ],
    )
    judge = _StubJudge((True, "n/a"))
    callback = _StubApprovalCallback()
    approval_gate = ApprovalGate(policy=AlwaysDenyPolicy(), callback=callback)
    repair = _StubRepair([{"file": "X present now"}])
    gate = RoutingContractGate(
        scorers={"unit_scorer": scorer},
        subjective_judge=judge,
        approval_gate=approval_gate,
        repair=repair,
    )

    # Act — only ONE repair allowed; it fixes the artifacts.
    verdict = await gate.evaluate({"file": "X missing"}, contract, max_gate_repair=1)

    # Assert — the repaired artifacts were rechecked and passed; no escalation.
    assert verdict.passed is True
    assert len(repair.calls) == 1
    assert callback.calls == []
