"""Default graph orchestrator — hierarchical multi-agent execution engine.

Flow: start(goal) → root agent assigned → delegate subtasks →
agents execute in parallel (bounded semaphore) → results bubble up →
EventBus events at each lifecycle point.

Failure: retry per-agent → escalate to parent after exhausting retries.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Callable, Awaitable, cast

if TYPE_CHECKING:
    from cognitia.protocols.graph_task import GraphTaskBoard

from cognitia.multi_agent.graph_context import GraphContextBuilder
from cognitia.multi_agent.graph_execution_context import AgentExecutionContext
from cognitia.multi_agent.graph_orchestrator_types import (
    AgentExecution,
    AgentRunState,
    DelegationRequest,
    OrchestratorRunState,
    OrchestratorRunStatus,
)
from cognitia.multi_agent.graph_runtime_config import GraphRuntimeResolver
from cognitia.multi_agent.graph_task_types import GraphTaskItem

# Type alias for the agent runner callback.
# Signature: (agent_id, task_id, goal, system_prompt) -> result_text
AgentRunner = Callable[[str, str, str, str], Awaitable[str]]

# New context-aware runner: receives a single AgentExecutionContext.
ContextAwareRunner = Callable[[AgentExecutionContext], Awaitable[str]]


class DefaultGraphOrchestrator:
    """Concrete orchestrator that ties graph components together.

    Requires:
        - graph: AgentGraphStore + AgentGraphQuery (InMemory/SQLite)
        - task_board: GraphTaskBoard
        - agent_runner: async callable — either legacy (agent_id, task_id, goal, system_prompt) -> str
          or context-aware (AgentExecutionContext) -> str (auto-detected)
        - event_bus: optional EventBus for lifecycle events
        - approval_gate: optional gate with async check(action, context) -> bool
    """

    def __init__(
        self,
        graph: Any,  # AgentGraphStore + AgentGraphQuery in practice
        task_board: GraphTaskBoard | Any,
        agent_runner: AgentRunner | ContextAwareRunner,
        *,
        event_bus: Any | None = None,
        communication: Any | None = None,
        max_concurrent: int = 5,
        max_retries: int = 2,
        approval_gate: Any | None = None,
    ) -> None:
        self._graph = graph
        self._task_board = task_board
        self._runner = agent_runner
        # Detect if runner accepts 1 arg (ContextAwareRunner) or 4 args (legacy)
        try:
            sig = inspect.signature(agent_runner)
            params = [
                p for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
            self._context_aware = len(params) == 1
        except (ValueError, TypeError):
            self._context_aware = False
        self._bus = event_bus
        self._comm = communication
        self._max_concurrent = max_concurrent
        self._max_retries = max_retries
        self._gate = approval_gate

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._context_builder = GraphContextBuilder(graph_query=graph, task_board=task_board)
        self._config_resolver = GraphRuntimeResolver(graph_query=graph)

        # run_id -> mutable run state
        self._runs: dict[str, _RunState] = {}
        # task_id -> result
        self._results: dict[str, str] = {}
        # Background tasks for cancellation
        self._bg_tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------
    # Protocol: start
    # ------------------------------------------------------------------

    async def start(self, goal: str) -> str:
        """Start an orchestration run. Finds graph root, creates root task."""
        root = await self._graph.get_root()
        if root is None:
            raise ValueError("Graph has no root agent")

        run_id = uuid.uuid4().hex[:12]
        root_task_id = f"root-{run_id}"

        # Create root task on the board and checkout immediately
        await self._task_board.create_task(GraphTaskItem(
            id=root_task_id,
            title=goal,
            assignee_agent_id=root.id,
        ))
        await self._task_board.checkout_task(root_task_id, root.id)

        self._runs[run_id] = _RunState(
            run_id=run_id,
            state=OrchestratorRunState.RUNNING,
            root_task_id=root_task_id,
            root_agent_id=root.id,
            started_at=time.time(),
        )

        await self._emit("graph.orchestrator.started", {
            "run_id": run_id,
            "goal": goal,
        })

        # Launch root agent execution
        run_state = self._runs[run_id]
        run_state.executions.append(AgentExecution(
            agent_id=root.id,
            task_id=root_task_id,
        ))
        task = asyncio.create_task(
            self._execute_agent(root.id, root_task_id, goal, self._max_retries, run_state)
        )
        self._bg_tasks[root_task_id] = task

        return run_id

    # ------------------------------------------------------------------
    # Protocol: delegate
    # ------------------------------------------------------------------

    async def delegate(self, request: DelegationRequest) -> None:
        """Delegate a task to an agent. Creates subtask and launches execution."""
        # Find run for this delegation
        run = self._find_run_for_task(request.parent_task_id)

        # Check approval gate
        if self._gate is not None:
            approved = await self._gate.check(
                "delegate",
                {"agent_id": request.agent_id, "goal": request.goal},
            )
            if not approved:
                await self._emit("graph.orchestrator.denied", {
                    "task_id": request.task_id,
                    "agent_id": request.agent_id,
                })
                return

        # Create subtask on the board and checkout immediately
        await self._task_board.create_task(GraphTaskItem(
            id=request.task_id,
            title=request.goal,
            assignee_agent_id=request.agent_id,
            parent_task_id=request.parent_task_id,
            stage=request.stage,
        ))
        await self._task_board.checkout_task(request.task_id, request.agent_id)

        await self._emit("graph.orchestrator.delegated", {
            "task_id": request.task_id,
            "agent_id": request.agent_id,
            "goal": request.goal,
        })

        if run:
            run.executions.append(AgentExecution(
                agent_id=request.agent_id,
                task_id=request.task_id,
            ))

        # Launch async execution
        max_retries = request.max_retries if request.max_retries is not None else self._max_retries
        task = asyncio.create_task(
            self._execute_agent(request.agent_id, request.task_id, request.goal, max_retries, run)
        )
        self._bg_tasks[request.task_id] = task

    # ------------------------------------------------------------------
    # Protocol: wait_for_task (GraphTaskWaiter)
    # ------------------------------------------------------------------

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> str | None:
        """Wait for a background task to complete. Returns result or None."""
        bg = self._bg_tasks.get(task_id)
        if bg is None:
            return self._results.get(task_id)
        try:
            if timeout is not None:
                await asyncio.wait_for(asyncio.shield(bg), timeout=timeout)
            else:
                await bg
        except (TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        return self._results.get(task_id)

    # ------------------------------------------------------------------
    # Protocol: collect_result
    # ------------------------------------------------------------------

    async def collect_result(self, task_id: str) -> str | None:
        """Return the result for a task, or None if not yet complete."""
        return self._results.get(task_id)

    # ------------------------------------------------------------------
    # Protocol: get_status
    # ------------------------------------------------------------------

    async def get_status(self, run_id: str) -> OrchestratorRunStatus:
        """Return a frozen snapshot of the run state."""
        run = self._runs.get(run_id)
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

    # ------------------------------------------------------------------
    # Protocol: stop
    # ------------------------------------------------------------------

    async def stop(self, run_id: str) -> None:
        """Stop an orchestration run. Cancel pending background tasks."""
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"Run '{run_id}' not found")

        run.state = OrchestratorRunState.STOPPED
        run.finished_at = time.time()

        # Cancel background tasks for this run
        for execution in run.executions:
            bg = self._bg_tasks.pop(execution.task_id, None)
            if bg and not bg.done():
                bg.cancel()

        await self._emit("graph.orchestrator.stopped", {
            "run_id": run_id,
        })

    # ------------------------------------------------------------------
    # Internal: agent execution with retry
    # ------------------------------------------------------------------

    async def _execute_agent(
        self,
        agent_id: str,
        task_id: str,
        goal: str,
        max_retries: int,
        run: _RunState | None,
    ) -> None:
        """Execute an agent with semaphore-bounded concurrency and retry."""
        attempt = 0
        last_error: str | None = None

        try:
            while attempt <= max_retries:
                async with self._semaphore:
                    try:
                        # Update state
                        if run:
                            idx = self._find_execution_index(run, task_id)
                            if idx is not None:
                                state = AgentRunState.RETRYING if attempt > 0 else AgentRunState.RUNNING
                                run.executions[idx] = replace(
                                    run.executions[idx],
                                    state=state,
                                    retries=attempt,
                                    started_at=time.time(),
                                )

                        # Build structured execution context
                        try:
                            exec_ctx = await self._context_builder.build_execution_context(
                                agent_id, task_id, goal,
                            )
                        except ValueError:
                            exec_ctx = AgentExecutionContext(
                                agent_id=agent_id,
                                task_id=task_id,
                                goal=goal,
                                system_prompt="",
                            )

                        # Dual dispatch: new runner gets full context, legacy gets 4 strings
                        if self._context_aware:
                            ctx_runner = cast(ContextAwareRunner, self._runner)
                            result = await ctx_runner(exec_ctx)
                        else:
                            legacy_runner = cast(AgentRunner, self._runner)
                            result = await legacy_runner(
                                agent_id, task_id, goal, exec_ctx.system_prompt,
                            )

                        # Success
                        self._results[task_id] = result
                        await self._task_board.complete_task(task_id)

                        if run:
                            idx = self._find_execution_index(run, task_id)
                            if idx is not None:
                                run.executions[idx] = replace(
                                    run.executions[idx],
                                    state=AgentRunState.COMPLETED,
                                    result=result,
                                    finished_at=time.time(),
                                )

                        await self._emit("graph.orchestrator.agent_completed", {
                            "agent_id": agent_id,
                            "task_id": task_id,
                        })

                        # Lifecycle mode handling
                        await self._handle_lifecycle(agent_id, task_id)
                        return

                    except Exception as exc:  # noqa: BLE001
                        last_error = str(exc)
                        attempt += 1
                        if attempt <= max_retries:
                            backoff = min(2 ** (attempt - 1) * 0.5, 30.0)
                            await asyncio.sleep(backoff)

            # Exhausted retries → mark failed on board and in run state, escalate
            if hasattr(self._task_board, "cancel_task"):
                await self._task_board.cancel_task(task_id)

            if run:
                idx = self._find_execution_index(run, task_id)
                if idx is not None:
                    run.executions[idx] = replace(
                        run.executions[idx],
                        state=AgentRunState.FAILED,
                        error=last_error,
                        finished_at=time.time(),
                    )

            await self._emit("graph.orchestrator.escalated", {
                "agent_id": agent_id,
                "task_id": task_id,
                "error": last_error,
            })

            # Escalate via communication if available
            if self._comm is not None:
                await self._comm.escalate(
                    agent_id, f"Failed after {max_retries} retries: {last_error}",
                    task_id=task_id,
                )

        except asyncio.CancelledError:
            # Graceful stop -- cancel task on the board, do NOT retry
            if hasattr(self._task_board, "cancel_task"):
                await self._task_board.cancel_task(task_id)
            return
        finally:
            self._bg_tasks.pop(task_id, None)

    # ------------------------------------------------------------------
    # Internal: lifecycle mode handling
    # ------------------------------------------------------------------

    async def _handle_lifecycle(self, agent_id: str, task_id: str) -> None:
        """Handle agent lifecycle after task completion."""
        try:
            node = await self._graph.get_node(agent_id)
        except Exception:  # noqa: BLE001
            return
        if node is None or not hasattr(node, "lifecycle"):
            return

        from cognitia.multi_agent.graph_types import LifecycleMode

        if node.lifecycle == LifecycleMode.EPHEMERAL:
            if hasattr(self._graph, "remove_node"):
                await self._graph.remove_node(agent_id)
            await self._emit("graph.agent.self_terminated", {"agent_id": agent_id})
        elif node.lifecycle == LifecycleMode.SUPERVISED:
            await self._emit("graph.agent.awaiting_review", {
                "agent_id": agent_id,
                "task_id": task_id,
            })
        elif node.lifecycle == LifecycleMode.PERSISTENT:
            from cognitia.multi_agent.registry_types import AgentStatus
            if hasattr(self._graph, "update_status"):
                await self._graph.update_status(agent_id, AgentStatus.IDLE)
            await self._emit("graph.agent.ready", {"agent_id": agent_id})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_run_for_task(self, parent_task_id: str | None) -> _RunState | None:
        """Find the run that owns a given root task."""
        if parent_task_id is None:
            return None
        for run in self._runs.values():
            if run.root_task_id == parent_task_id:
                return run
            # Also check if any execution owns this parent
            if any(e.task_id == parent_task_id for e in run.executions):
                return run
        return None

    @staticmethod
    def _find_execution_index(run: _RunState, task_id: str) -> int | None:
        for i, e in enumerate(run.executions):
            if e.task_id == task_id:
                return i
        return None

    async def _emit(self, topic: str, data: dict[str, Any]) -> None:
        if self._bus is not None:
            await self._bus.emit(topic, data)


class _RunState:
    """Mutable internal state for an orchestration run."""

    __slots__ = (
        "run_id", "state", "root_task_id", "root_agent_id",
        "executions", "started_at", "finished_at", "error",
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
