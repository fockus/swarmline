"""Contract gate: per-criterion routing + gate-repair budget (Epic G, Task 6).

Covers REQ-016, REQ-017, REQ-018, REQ-009. Deployed artifacts are checked
against an `OutputContract`'s acceptance criteria: `"deterministic"`
criteria are routed to a pre-configured `eval.scorers` `Scorer` looked up by
`criterion.verifier`; `"subjective"` criteria are routed to an injected
`SubjectiveJudge`. This is the routing layer only — scoring itself is never
re-implemented here (`swarmline.eval.scorers`), and the pass/fail decision
per run is never re-implemented either: each attempt builds a real
`VerificationLedger` and defers to `swarmline.verification.coverage.
unmet_criteria` (I-024), the SAME coverage rule the H6 finalize gate uses.
Every check is recorded with `advisory=False` so a criterion whose only
result is a judge verdict still counts as "covered", not silently ignored
by the coverage rule (which treats advisory-only coverage as unverified).

On failure the loop asks an injected `repair` callable to revise the
artifacts, bounded by `max_gate_repair` (mirrors Task 4's `VerifyPhase`
fail-fast `>= 1` contract). If the budget is exhausted — or no `repair` was
given at all — it escalates to a human via `ApprovalGate.check`, never
fails silently (REQ-009/REQ-010).

DIP boundary, stated honestly: `SubjectiveJudge` is a local Protocol, not a
concrete dependency on `multi_agent.shared_agents.SharedAgentRegistry`.
`SharedAgentRegistry` is a role -> `AgentNode` *registry* (a lookup table),
not an evaluator — invoking a judge/reviewer agent needs a runtime loop
(`RuntimeConfig`/`run()`) that this gate must not own, or it would collapse
the Application/Infrastructure boundary this module lives on (SRP: routing
vs. execution; DIP: depend on the abstraction, not the registry). Task 7's
engine resolves the reviewer/judge `AgentNode` from `SharedAgentRegistry`
and hands this gate a registry-backed `SubjectiveJudge` adapter that owns
the actual runtime call. This module never imports `shared_agents.py`.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable

from swarmline.eval.types import EvalCase, Scorer, ScorerResult
from swarmline.hitl.gate import ApprovalGate
from swarmline.orchestration.autopilot.types import (
    AcceptanceCriterion,
    GateVerdict,
    OutputContract,
)
from swarmline.types import (
    AcceptanceCriterion as VerificationCriterion,
    VerificationLedger,
    VerificationOutcome,
)
from swarmline.verification.coverage import unmet_criteria

__all__ = ["RoutingContractGate", "SubjectiveJudge", "RepairCallable"]


@runtime_checkable
class SubjectiveJudge(Protocol):
    """Evaluates a `"subjective"` criterion against the deployed artifacts."""

    async def judge(
        self, criterion: AcceptanceCriterion, artifacts: dict[str, str]
    ) -> tuple[bool, str]: ...


RepairCallable = Callable[[tuple[str, ...], dict[str, str]], Awaitable[dict[str, str]]]


class RoutingContractGate:
    """Routes each criterion to its verifier, bounded by a gate-repair budget.

    Reuses (never re-implements):
      - `eval.scorers.*` (`Scorer.score`) for deterministic checks.
      - `verification.coverage.unmet_criteria` for the pass/fail decision.
      - `ApprovalGate.check` (hitl/gate.py) for the human escalation itself.
    """

    def __init__(
        self,
        scorers: dict[str, Scorer],
        subjective_judge: SubjectiveJudge,
        approval_gate: ApprovalGate,
        *,
        repair: RepairCallable | None = None,
        pass_threshold: float = 1.0,
    ) -> None:
        self._scorers = scorers
        self._subjective_judge = subjective_judge
        self._approval_gate = approval_gate
        self._repair = repair
        self._pass_threshold = pass_threshold

    async def evaluate(
        self,
        artifacts: dict[str, str],
        contract: OutputContract,
        *,
        max_gate_repair: int = 3,
    ) -> GateVerdict:
        """Check `artifacts` against `contract.criteria`, repairing up to the budget.

        Returns PASSED as soon as a round clears every criterion (per
        `unmet_criteria`). If the budget is exhausted — or no `repair` was
        injected — escalates to the injected `ApprovalGate` and returns a
        failing verdict naming the still-unmet criterion ids.

        Fails fast on a non-positive budget, mirroring `VerifyPhase`'s
        `max_plan_repair >= 1` contract.
        """
        if max_gate_repair < 1:
            raise ValueError("max_gate_repair must be >= 1")

        current_artifacts = artifacts
        last_unmet_ids: tuple[str, ...] = ()
        attempts = 0

        # attempt 0 = the initial evaluation; attempts 1..max_gate_repair are
        # RE-evaluations AFTER a repair. This means each of the max_gate_repair
        # repairs is rechecked before escalating — a within-budget repair on the
        # final attempt is not falsely escalated (off-by-one guard).
        for attempt in range(max_gate_repair + 1):
            attempts = attempt + 1
            last_unmet_ids = await self._evaluate(current_artifacts, contract)
            if not last_unmet_ids:
                return GateVerdict(
                    passed=True,
                    failures=(),
                    log=f"all {len(contract.criteria)} criteria passed on attempt {attempts}",
                )
            if attempt == max_gate_repair or self._repair is None:
                break
            current_artifacts = await self._repair(last_unmet_ids, current_artifacts)

        approved = await self._approval_gate.check(
            "contract_gate_escalation",
            {"unmet": list(last_unmet_ids), "attempts": attempts},
            description=(
                "Contract gate failed after N repair attempts; human decision required"
            ),
            raise_on_deny=False,
        )
        return GateVerdict(
            passed=False,
            failures=last_unmet_ids,
            log=f"escalated after {attempts} attempts; approved={approved}",
        )

    async def _evaluate(
        self, artifacts: dict[str, str], contract: OutputContract
    ) -> tuple[str, ...]:
        """Route every criterion, build a ledger, return the unmet criterion ids.

        Reuses `verification.coverage.unmet_criteria` for the pass/fail
        decision — an empty tuple means every criterion passed this round.
        """
        outcomes = tuple(
            [await self._check_criterion(c, artifacts) for c in contract.criteria]
        )
        ledger = VerificationLedger(
            criteria=tuple(
                VerificationCriterion(id=c.id, description=c.description, kind=c.kind)
                for c in contract.criteria
            ),
            results=outcomes,
        )
        return tuple(c.id for c in unmet_criteria(ledger))

    async def _check_criterion(
        self, criterion: AcceptanceCriterion, artifacts: dict[str, str]
    ) -> VerificationOutcome:
        """Route `criterion` to its scorer (deterministic) or judge (subjective)."""
        output = "\n".join(artifacts.values())
        if criterion.kind == "deterministic":
            scorer = self._scorers.get(criterion.verifier)
            if scorer is None:
                return VerificationOutcome(
                    criterion_id=criterion.id,
                    passed=False,
                    advisory=False,
                    evidence=f"no scorer '{criterion.verifier}'",
                )
            case = EvalCase(id=criterion.id, input="", expected=criterion.description)
            result: ScorerResult = await scorer.score(case, output)
            return VerificationOutcome(
                criterion_id=criterion.id,
                passed=result.score >= self._pass_threshold,
                advisory=False,
                evidence=result.reason,
            )
        passed, evidence = await self._subjective_judge.judge(criterion, artifacts)
        return VerificationOutcome(
            criterion_id=criterion.id, passed=passed, advisory=False, evidence=evidence
        )
