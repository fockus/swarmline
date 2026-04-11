"""Mutable run-state helpers for DefaultGraphOrchestrator."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Final, cast

from swarmline.multi_agent.graph_orchestrator_types import (
    AgentExecution,
    AgentRunState,
    OrchestratorRunState,
    OrchestratorRunStatus,
)

_MISSING: Final = object()


class GraphRunStore:
    """Owns mutable run state and execution bookkeeping for the orchestrator."""

    def __init__(self) -> None:
        self._runs: dict[str, _RunState] = {}

    @property
    def runs(self) -> dict[str, _RunState]:
        return self._runs

    def create(self, run_id: str, root_task_id: str, root_agent_id: str) -> _RunState:
        run = _RunState(
            run_id=run_id,
            state=OrchestratorRunState.RUNNING,
            root_task_id=root_task_id,
            root_agent_id=root_agent_id,
            started_at=time.time(),
        )
        self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> _RunState | None:
        return self._runs.get(run_id)

    def snapshot(self, run_id: str) -> OrchestratorRunStatus:
        run = self.get(run_id)
        if run is None:
            raise KeyError(f"Run '{run_id}' not found")
        return OrchestratorRunStatus(
            run_id=run.run_id,
            state=run.state,
            root_task_id=run.root_task_id,
            root_agent_id=run.root_agent_id,
            executions=tuple(run.executions),
            started_at=run.started_at,
            finished_at=run.finished_at,
            error=run.error,
        )

    def stop(self, run_id: str) -> _RunState:
        run = self.get(run_id)
        if run is None:
            raise KeyError(f"Run '{run_id}' not found")
        run.state = OrchestratorRunState.STOPPED
        run.finished_at = time.time()
        return run

    def append_execution(self, run: _RunState | None, agent_id: str, task_id: str) -> None:
        if run is None:
            return
        run.executions.append(AgentExecution(agent_id=agent_id, task_id=task_id))

    def update_execution(
        self,
        run: _RunState | None,
        task_id: str,
        *,
        state: AgentRunState | object = _MISSING,
        result: str | None | object = _MISSING,
        error: str | None | object = _MISSING,
        retries: int | object = _MISSING,
        started_at: float | None | object = _MISSING,
        finished_at: float | None | object = _MISSING,
    ) -> None:
        if run is None:
            return
        idx = self.find_execution_index(run, task_id)
        if idx is None:
            return
        execution = run.executions[idx]
        if state is not _MISSING:
            execution = replace(execution, state=cast(AgentRunState, state))
        if result is not _MISSING:
            execution = replace(execution, result=cast(str | None, result))
        if error is not _MISSING:
            execution = replace(execution, error=cast(str | None, error))
        if retries is not _MISSING:
            execution = replace(execution, retries=cast(int, retries))
        if started_at is not _MISSING:
            execution = replace(execution, started_at=cast(float | None, started_at))
        if finished_at is not _MISSING:
            execution = replace(execution, finished_at=cast(float | None, finished_at))
        run.executions[idx] = execution

    def find_run_for_task(self, parent_task_id: str | None) -> _RunState | None:
        if parent_task_id is None:
            return None
        for run in self._runs.values():
            if run.root_task_id == parent_task_id:
                return run
            if any(execution.task_id == parent_task_id for execution in run.executions):
                return run
        return None

    @staticmethod
    def find_execution_index(run: _RunState, task_id: str) -> int | None:
        for idx, execution in enumerate(run.executions):
            if execution.task_id == task_id:
                return idx
        return None


class _RunState:
    """Mutable internal state for an orchestration run."""

    __slots__ = (
        "run_id",
        "state",
        "root_task_id",
        "root_agent_id",
        "executions",
        "started_at",
        "finished_at",
        "error",
    )

    def __init__(
        self,
        run_id: str,
        state: OrchestratorRunState,
        root_task_id: str,
        root_agent_id: str,
        started_at: float,
        finished_at: float | None = None,
        error: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.state = state
        self.root_task_id = root_task_id
        self.root_agent_id = root_agent_id
        self.executions: list[AgentExecution] = []
        self.started_at = started_at
        self.finished_at = finished_at
        self.error = error
