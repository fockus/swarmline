"""Pre-deploy verify-loop + repair budget + HITL escalation (Epic G, Task 4).

Covers REQ-007, REQ-008, REQ-010. Runs the two pre-deploy verification layers
(deterministic `validate_blueprint` + LLM `BlueprintCritic`) in a bounded
plan-repair loop: on any failure the injected `Planner.replan` is asked to
revise the blueprint using the combined feedback, up to `max_plan_repair`
rounds. If the budget is exhausted without a clean pass, the loop escalates
to a human via an injected `ApprovalGate` — it never fails silently.

Honest nuance on reuse of `DoDStateMachine`/`DoDStatus`: `DoDStateMachine.
verify_dod` re-runs identical *code-DoD criterion closures* against a fixed
artifact — it never regenerates the artifact between iterations, so it has
no notion of "repair" beyond re-checking. It therefore cannot itself drive a
plan-repair loop that must call `planner.replan()` each round (a fresh
blueprint each time, not a fixed one re-checked). `VerifyPhase` mirrors its
bounded-loop-until-pass-or-max-loops contract and reuses its `DoDStatus`
terminal vocabulary (`PASSED` / `MAX_LOOPS_EXCEEDED`) for outcome parity
across the codebase, while the loop body itself is autopilot-specific:
`validate_blueprint` (Task 2, layer 1) + `critic.critique` (Task 3, layer 2)
+ `planner.replan` (Task 3) each round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from swarmline.hitl.gate import ApprovalGate
from swarmline.multi_agent.graph_governance import GraphGovernanceConfig
from swarmline.orchestration.autopilot.critic import BlueprintCritic
from swarmline.orchestration.autopilot.planner import Planner
from swarmline.orchestration.autopilot.types import OrchestrationBlueprint
from swarmline.orchestration.autopilot.validators import validate_blueprint
from swarmline.orchestration.dod_state_machine import DoDStatus


@dataclass(frozen=True)
class VerifyOutcome:
    """Result of a `VerifyPhase.run` call."""

    status: DoDStatus  # PASSED | MAX_LOOPS_EXCEEDED
    blueprint: OrchestrationBlueprint
    iterations: int
    escalated: bool = False
    approved: bool | None = None  # human decision when escalated (gate.check result)
    problems: tuple[str, ...] = field(
        default=()
    )  # last-seen problems + critic failures


class VerifyPhase:
    """Bounded pre-deploy verify loop: validator + critic + repair + HITL.

    Reuses (never re-implements):
      - `DoDStatus` (dod_state_machine.py) for terminal outcome vocabulary.
      - `validate_blueprint` (validators.py, Task 2) for deterministic checks.
      - `BlueprintCritic.critique` (critic.py, Task 3) for the judgement layer.
      - `Planner.replan` (planner.py, Task 3) to regenerate a repaired blueprint.
      - `ApprovalGate.check` (hitl/gate.py) for the human escalation itself.
    """

    def __init__(
        self,
        planner: Planner,
        critic: BlueprintCritic,
        approval_gate: ApprovalGate,
        *,
        governance: GraphGovernanceConfig,
        graph_schema: Callable[[dict], tuple[str, ...]] | None = None,
    ) -> None:
        self._planner = planner
        self._critic = critic
        self._approval_gate = approval_gate
        self._governance = governance
        self._graph_schema = graph_schema

    async def run(
        self, blueprint: OrchestrationBlueprint, *, max_plan_repair: int = 3
    ) -> VerifyOutcome:
        """Validate + critique `blueprint`, repairing via replan up to the budget.

        Returns PASSED as soon as a round clears both layers clean. If the
        budget is exhausted, escalates to the injected `ApprovalGate` and
        returns MAX_LOOPS_EXCEEDED carrying the human's decision.

        Fails fast on a non-positive budget, mirroring `DoDStateMachine`'s
        `max_loops >= 1` contract.
        """
        if max_plan_repair < 1:
            raise ValueError("max_plan_repair must be >= 1")

        current = blueprint
        last_problems: tuple[str, ...] = ()
        attempts = 0

        # attempt 0 = the initial verification; attempts 1..max_plan_repair are
        # RE-verifications after each replan, so every one of the max_plan_repair
        # repairs is rechecked before escalating — a within-budget repair on the
        # final attempt is not falsely escalated (matches RoutingContractGate's
        # off-by-one guard).
        for attempt in range(max_plan_repair + 1):
            attempts = attempt + 1
            problems = validate_blueprint(
                current,
                governance=self._governance,
                graph_schema=self._graph_schema,
            )
            verdict = await self._critic.critique(current)

            if not problems and verdict.passed:
                return VerifyOutcome(
                    status=DoDStatus.PASSED,
                    blueprint=current,
                    iterations=attempts,
                )

            last_problems = (*problems, *verdict.failures)
            if attempt == max_plan_repair:
                break
            feedback = "; ".join(last_problems) or "Verification failed."
            current = await self._planner.replan(current, feedback)

        approved = await self._approval_gate.check(
            "plan_verification_escalation",
            {"iterations": attempts, "problems": list(last_problems)},
            description=(
                "Plan failed verification after "
                f"{max_plan_repair} repair attempts; human decision required"
            ),
            raise_on_deny=False,
        )
        return VerifyOutcome(
            status=DoDStatus.MAX_LOOPS_EXCEEDED,
            blueprint=current,
            iterations=attempts,
            escalated=True,
            approved=approved,
            problems=last_problems,
        )
