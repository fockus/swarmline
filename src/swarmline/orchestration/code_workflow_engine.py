"""CodeWorkflowEngine - structured code pipeline with DoD verification loop.

Thin wrapper over GenericWorkflowEngine. Adds code-specific DoD verification
via DoDStateMachine and CodeVerifier on top of the generic execute/verify loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from swarmline.orchestration.code_verifier import CodeVerifier
from swarmline.orchestration.dod_state_machine import DoDResult, DoDStatus
from swarmline.orchestration.generic_workflow_engine import GenericWorkflowEngine


class WorkflowStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    DOD_NOT_MET = "dod_not_met"


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Result of a full code workflow run."""

    status: WorkflowStatus
    output: str = ""
    dod_log: str = ""
    loop_count: int = 0


class CodePlannerPort(Protocol):
    """Protocol for pluggable planner in CodeWorkflowEngine (DIP).

  Implementations: ThinPlannerMode, DeepAgentsPlannerMode, custom planners.
  """

    async def create_plan(self, goal: str) -> str: ...

    async def execute_plan(self, plan: str) -> str: ...


class DoDVerifierPort(Protocol):
    """Protocol for DoD verification state machine (DIP).

  Implementations: DoDStateMachine (default), custom DoD engines.
  """

    async def verify_dod(
        self, criteria: tuple[str, ...], verifier: CodeVerifier
    ) -> DoDResult: ...


class _PlannerExecutor:
    """Adapts CodePlannerPort to ExecutorPort (execute(goal) -> str)."""

    def __init__(self, planner: CodePlannerPort) -> None:
        self._planner = planner

    async def execute(self, goal: str) -> str:
        plan = await self._planner.create_plan(goal)
        return await self._planner.execute_plan(plan)


class _DoDVerifierAdapter:
    """Adapts DoDVerifierPort + CodeVerifier to VerifierPort (verify(output) -> (bool, str)).

  DoD criteria are passed via context["dod_criteria"] at run time.
  When criteria are empty, verification is skipped (always passes).
  The DoDStateMachine manages its own retry loop internally,
  so GenericWorkflowEngine uses max_retries=1.
  """

    def __init__(self, dod: DoDVerifierPort, verifier: CodeVerifier) -> None:
        self._dod = dod
        self._verifier = verifier
        self._criteria: tuple[str, ...] = ()
        self._last_dod_status: DoDStatus = DoDStatus.PENDING
        self._last_dod_log: str = ""
        self._last_dod_loop_count: int = 0

    async def verify(self, output: str) -> tuple[bool, str]:
        """Run DoD verification using stored criteria.

    Criteria must be set via set_criteria() before each run.
    """
        if not self._criteria:
            self._last_dod_status = DoDStatus.PASSED
            self._last_dod_log = ""
            self._last_dod_loop_count = 0
            return True, ""

        dod_result = await self._dod.verify_dod(self._criteria, self._verifier)
        self._last_dod_status = dod_result.status
        self._last_dod_log = dod_result.verification_log
        self._last_dod_loop_count = dod_result.loop_count

        passed = dod_result.status == DoDStatus.PASSED
        return passed, dod_result.verification_log

    def set_criteria(self, criteria: tuple[str, ...]) -> None:
        """Set DoD criteria for the next verification run."""
        self._criteria = criteria

    @property
    def last_dod_status(self) -> DoDStatus:
        return self._last_dod_status

    @property
    def last_dod_log(self) -> str:
        return self._last_dod_log

    @property
    def last_dod_loop_count(self) -> int:
        return self._last_dod_loop_count


class CodeWorkflowEngine:
    """Structured code pipeline: plan -> execute -> verify DoD.

  Delegates to GenericWorkflowEngine with code-specific adapters:
  - CodePlannerPort as executor (via _PlannerExecutor)
  - DoDStateMachine + CodeVerifier as verifier (via _DoDVerifierAdapter)
  """

    def __init__(
        self,
        verifier: CodeVerifier,
        dod: DoDVerifierPort,
        planner: CodePlannerPort,
    ) -> None:
        self._verifier = verifier
        self._dod = dod
        self._planner = planner
        self._dod_adapter = _DoDVerifierAdapter(dod, verifier)
        self._generic = GenericWorkflowEngine(
            executor=_PlannerExecutor(planner),
            verifier=self._dod_adapter,
            max_retries=1,
        )

    async def run(self, goal: str, dod_criteria: tuple[str, ...] = ()) -> WorkflowResult:
        """Execute full workflow: plan -> execute -> verify DoD.

    Delegates to GenericWorkflowEngine, then maps the result
    back to code-specific WorkflowResult with DoD details.
    """
        self._dod_adapter.set_criteria(dod_criteria)

        generic_result = await self._generic.run(goal)

        dod_log = self._dod_adapter.last_dod_log
        dod_loop_count = self._dod_adapter.last_dod_loop_count
        dod_status = self._dod_adapter.last_dod_status

        if not dod_criteria:
            return WorkflowResult(
                status=WorkflowStatus.SUCCESS,
                output=generic_result.output,
            )

        if dod_status == DoDStatus.PASSED:
            return WorkflowResult(
                status=WorkflowStatus.SUCCESS,
                output=generic_result.output,
                dod_log=dod_log,
                loop_count=dod_loop_count,
            )

        return WorkflowResult(
            status=WorkflowStatus.DOD_NOT_MET,
            output=generic_result.output,
            dod_log=dod_log,
            loop_count=dod_loop_count,
        )
