"""Engine facade: plan -> verify -> [approval] -> deploy -> gate (Epic G, Task 7).

Covers REQ-003 (hardcode mode skips planning), REQ-011/REQ-012 (optional
plan-approval gate before deploy), REQ-021 (phase events on an observability
event bus). Wires the phase components built in Tasks 3-6 (`Planner`,
`VerifyPhase`, `DeployPhase`, `RoutingContractGate`) into the two supported
orchestrator modes without re-implementing any of their internals.

EventBus vs message_bus: `observability/event_bus.py`'s `EventBus` (plain
pub-sub: `emit(event_type, data)`) is the correct phase-event seam here —
phase transitions are observability signal, not an inter-agent message.
`multi_agent/message_bus.py` carries `TeamMessage` objects between AGENTS in
a team topology; using it for phase events would conflate a structural
collaboration channel with the orchestrator's own lifecycle telemetry. The
event bus is therefore optional (`None` = no-op) and orthogonal to whatever
message bus a deployed graph's agents use internally.

Deliverable-presence boundary (backlog I-084): this engine does NOT
independently re-check that `contract.deliverables` were produced.
Deliverable presence is enforced by binding every deliverable to at least
one `AcceptanceCriterion`, and `RoutingContractGate` already verifies every
criterion via `verification.coverage.unmet_criteria`. A second, engine-level
"are the deliverables there" check would duplicate the gate's job and risk
drifting out of sync with it — a deliverable with no bound criterion is a
contract-authoring defect (planner/schema concern), not something
`OrchestratorEngine.run` should silently patch over.
"""

from __future__ import annotations

from swarmline.hitl.gate import ApprovalGate
from swarmline.observability.event_bus import EventBus
from swarmline.orchestration.autopilot.deploy_phase import DeployPhase
from swarmline.orchestration.autopilot.gate import RoutingContractGate
from swarmline.orchestration.autopilot.planner import Planner
from swarmline.orchestration.autopilot.types import (
    OrchestrationBlueprint,
    OrchestrationPhase,
    OrchestrationResult,
    OrchestratorConfig,
    OutputContract,
)
from swarmline.orchestration.autopilot.verify_phase import VerifyPhase

__all__ = ["OrchestratorEngine"]


class OrchestratorEngine:
    """Facade driving one autopilot run: plan -> verify -> approval? -> deploy -> gate.

    Reuses (never re-implements):
      - `Planner.plan` for blueprint generation in dynamic mode.
      - `VerifyPhase.run` for the pre-deploy verify + repair + HITL loop.
      - `ApprovalGate.check` (hitl/gate.py) for the optional plan-approval gate.
      - `DeployPhase.deploy` to materialize + execute the blueprint.
      - `RoutingContractGate.evaluate` for the post-deploy acceptance gate.
    """

    def __init__(
        self,
        planner: Planner,
        verify_phase: VerifyPhase,
        deploy_phase: DeployPhase,
        gate: RoutingContractGate,
        *,
        approval_gate: ApprovalGate | None = None,
        event_bus: EventBus | None = None,
        event_type: str = "autopilot.phase",
    ) -> None:
        self._planner = planner
        self._verify_phase = verify_phase
        self._deploy_phase = deploy_phase
        self._gate = gate
        self._approval_gate = approval_gate
        self._event_bus = event_bus
        self._event_type = event_type

    async def run(
        self,
        goal: str | None = None,
        *,
        mode: str = "dynamic",
        blueprint: OrchestrationBlueprint | None = None,
        contract: OutputContract | None = None,
        config: OrchestratorConfig | None = None,
    ) -> OrchestrationResult:
        """Drive one plan -> verify -> approval? -> deploy -> gate run.

        `mode="dynamic"` requires `goal` and generates a blueprint through the
        injected `Planner`. `mode="hardcode"` (REQ-003) requires a pre-built
        `blueprint` and skips the planner entirely.
        """
        config = config or OrchestratorConfig()
        phase_log: list[str] = []

        blueprint = await self._plan(
            goal,
            mode=mode,
            blueprint=blueprint,
            phase_log=phase_log,
        )

        await self._emit_phase(OrchestrationPhase.VERIFY, phase_log)
        outcome = await self._verify_phase.run(
            blueprint, max_plan_repair=config.max_plan_repair
        )
        blueprint = outcome.blueprint
        # Resolve the contract AFTER verify: a repair may have regenerated the
        # blueprint's own contract (the critic assesses contract completeness),
        # so deploy/gate/result must use the repaired blueprint's contract — an
        # explicit caller-supplied `contract` (hardcode) still wins if given.
        contract_to_use = contract if contract is not None else blueprint.contract
        if outcome.escalated:
            return OrchestrationResult(
                status="verify_escalated",
                blueprint=blueprint,
                contract=contract_to_use,
                verdict=None,
                phase_log=tuple(phase_log),
            )

        if config.require_plan_approval:
            await self._emit_phase(OrchestrationPhase.APPROVAL, phase_log)
            if not await self._check_approval(contract_to_use):
                return OrchestrationResult(
                    status="aborted",
                    blueprint=blueprint,
                    contract=contract_to_use,
                    verdict=None,
                    phase_log=tuple(phase_log),
                )

        await self._emit_phase(OrchestrationPhase.DEPLOY, phase_log)
        deploy_result = await self._deploy_phase.deploy(blueprint)

        await self._emit_phase(OrchestrationPhase.GATE, phase_log)
        verdict = await self._gate.evaluate(
            deploy_result.artifacts,
            contract_to_use,
            max_gate_repair=config.max_gate_repair,
        )

        await self._emit_phase(OrchestrationPhase.DONE, phase_log)
        return OrchestrationResult(
            status="done" if verdict.passed else "gate_failed",
            blueprint=blueprint,
            contract=contract_to_use,
            verdict=verdict,
            phase_log=tuple(phase_log),
            board_snapshot={
                "artifacts": deploy_result.artifacts,
                "task_ids": [t.id for t in deploy_result.board_snapshot],
            },
        )

    async def _plan(
        self,
        goal: str | None,
        *,
        mode: str,
        blueprint: OrchestrationBlueprint | None,
        phase_log: list[str],
    ) -> OrchestrationBlueprint:
        """Resolve the starting blueprint for `mode`, emitting the PLAN phase."""
        await self._emit_phase(OrchestrationPhase.PLAN, phase_log)
        if mode == "dynamic":
            if not goal:
                raise ValueError("mode='dynamic' requires a goal")
            return await self._planner.plan(goal, "")
        if mode == "hardcode":
            if blueprint is None:
                raise ValueError("mode='hardcode' requires a blueprint")
            return blueprint
        raise ValueError(f"unknown mode: {mode!r}")

    async def _check_approval(self, contract: OutputContract) -> bool:
        """Ask the injected `ApprovalGate` for a GO/ABORT on the plan.

        No gate wired means approval is not enforced (defaults to GO).
        """
        if self._approval_gate is None:
            return True
        return await self._approval_gate.check(
            "plan_approval",
            {"deliverables": list(contract.deliverables)},
            description="Approve the generated plan before deploy (GO/ABORT)",
            raise_on_deny=False,
        )

    async def _emit_phase(
        self, phase: OrchestrationPhase, phase_log: list[str]
    ) -> None:
        """Record `phase` locally and, if wired, emit it on the event bus."""
        phase_log.append(phase.value)
        if self._event_bus is not None:
            await self._event_bus.emit(self._event_type, {"phase": phase.value})
