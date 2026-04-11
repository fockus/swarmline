"""PipelineBuilder — fluent API to wire all pipeline components.

Usage::

    pipeline = await (
        PipelineBuilder()
        .with_agents_from_dict({"root": {"name": "CEO", ...}})
        .with_runner(my_llm_runner)
        .add_phase("plan", "Planning", "Decompose the goal")
        .add_phase("exec", "Execution", "Execute tasks")
        .with_budget(BudgetPolicy(max_total_usd=10.0))
        .build()
    )
    result = await pipeline.run("Build the system")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from swarmline.protocols.agent_graph import AgentGraphStore
    from swarmline.protocols.graph_task import GraphTaskBoard

from swarmline.pipeline.budget import BudgetPolicy, BudgetTracker
from swarmline.pipeline.gate import CallbackGate
from swarmline.pipeline.pipeline import Pipeline
from swarmline.pipeline.types import PipelinePhase


class PipelineBuilder:
    """Fluent API to assemble a Pipeline from Swarmline components."""

    def __init__(self) -> None:
        self._graph_store: Any | None = None
        self._graph_config: dict[str, Any] | None = None
        self._graph_yaml: str | None = None
        self._phases: list[PipelinePhase] = []
        self._gates: dict[str, list[Any]] = {}
        self._budget_policy: BudgetPolicy | None = None
        self._runner: Callable[..., Awaitable[str]] | None = None
        self._event_bus: Any | None = None
        self._max_concurrent: int = 5
        self._circuit_breaker_config: dict[str, Any] | None = None
        self._task_board: Any | None = None
        self._communication: Any | None = None

    # --- Agent graph ---

    def with_graph(self, store: AgentGraphStore | Any) -> PipelineBuilder:
        """Use a pre-built graph store."""
        self._graph_store = store
        return self

    def with_agents_from_dict(self, config: dict[str, Any]) -> PipelineBuilder:
        """Build agent graph from a dictionary config."""
        self._graph_config = config
        return self

    def with_agents_from_yaml(self, path: str) -> PipelineBuilder:
        """Build agent graph from a YAML file path."""
        self._graph_yaml = path
        return self

    # --- Phases ---

    def add_phase(
        self,
        id: str,
        name: str,
        goal: str,
        *,
        agent_filter: str | None = None,
        timeout_seconds: float | None = None,
    ) -> PipelineBuilder:
        """Add a phase to the pipeline (in order of addition)."""
        self._phases.append(PipelinePhase(
            id=id,
            name=name,
            goal=goal,
            agent_filter=agent_filter,
            order=len(self._phases),
            timeout_seconds=timeout_seconds,
        ))
        return self

    # --- Gates ---

    def add_gate(self, phase_id: str, gate: Any) -> PipelineBuilder:
        """Add a quality gate to run after a specific phase."""
        self._gates.setdefault(phase_id, []).append(gate)
        return self

    def add_callback_gate(
        self,
        phase_id: str,
        name: str,
        fn: Callable[[str, dict[str, Any]], Awaitable[bool]],
    ) -> PipelineBuilder:
        """Add a simple callback-based quality gate."""
        self._gates.setdefault(phase_id, []).append(CallbackGate(name, fn))
        return self

    # --- Budget ---

    def with_budget(self, policy: BudgetPolicy) -> PipelineBuilder:
        """Set budget policy for cost tracking and enforcement."""
        self._budget_policy = policy
        return self

    # --- Runner ---

    def with_runner(
        self, runner: Callable[..., Awaitable[str]],
    ) -> PipelineBuilder:
        """Set the agent runner callback."""
        self._runner = runner
        return self

    # --- Options ---

    def with_event_bus(self, bus: Any) -> PipelineBuilder:
        """Set event bus for lifecycle events."""
        self._event_bus = bus
        return self

    def with_max_concurrent(self, n: int) -> PipelineBuilder:
        """Set maximum concurrent agent executions."""
        self._max_concurrent = n
        return self

    def with_circuit_breaker(
        self, threshold: int = 3, cooldown: float = 30.0,
    ) -> PipelineBuilder:
        """Enable circuit breaker per agent (wraps runner)."""
        self._circuit_breaker_config = {
            "threshold": threshold, "cooldown": cooldown,
        }
        return self

    def with_task_board(self, board: GraphTaskBoard | Any) -> PipelineBuilder:
        """Use a custom task board instead of InMemory default."""
        self._task_board = board
        return self

    def with_communication(self, comm: Any) -> PipelineBuilder:
        """Use a custom communication backend."""
        self._communication = comm
        return self

    # --- Build ---

    async def build(self) -> Pipeline:
        """Wire all components and return a ready-to-run Pipeline.

        Creates InMemory backends by default for any unspecified component.
        """
        if self._runner is None:
            raise ValueError("Runner is required — call .with_runner()")
        if not self._phases:
            raise ValueError("At least one phase is required — call .add_phase()")

        # 1. Graph store
        graph = await self._build_graph()

        # 2. Task board
        task_board = self._task_board
        if task_board is None:
            from swarmline.multi_agent.graph_task_board import InMemoryGraphTaskBoard
            task_board = InMemoryGraphTaskBoard()

        # 3. Communication
        communication = self._communication
        if communication is None:
            from swarmline.multi_agent.graph_communication import InMemoryGraphCommunication
            communication = InMemoryGraphCommunication(graph_query=graph)

        # 4. Event bus
        event_bus = self._event_bus
        if event_bus is None:
            from swarmline.observability.event_bus import InMemoryEventBus
            event_bus = InMemoryEventBus()

        # 5. Budget tracker
        budget: BudgetTracker | None = None
        if self._budget_policy is not None:
            budget = BudgetTracker(self._budget_policy, event_bus=event_bus)

        # 6. Wrap runner with budget + circuit breaker
        runner = self._runner
        if budget is not None:
            runner = budget.wrap_runner(runner)

        if self._circuit_breaker_config is not None:
            runner = self._wrap_with_circuit_breaker(runner)

        # 7. Orchestrator
        from swarmline.multi_agent.graph_orchestrator import DefaultGraphOrchestrator
        orchestrator = DefaultGraphOrchestrator(
            graph=graph,
            task_board=task_board,
            agent_runner=runner,
            event_bus=event_bus,
            communication=communication,
            max_concurrent=self._max_concurrent,
        )

        # 8. Pipeline
        return Pipeline(
            phases=self._phases,
            orchestrator=orchestrator,
            task_board=task_board,
            gates=self._gates if self._gates else None,
            budget=budget,
            event_bus=event_bus,
        )

    async def _build_graph(self) -> Any:
        """Build graph store from config/yaml/pre-built store."""
        if self._graph_store is not None:
            return self._graph_store

        from swarmline.multi_agent.graph_store import InMemoryAgentGraph
        store = InMemoryAgentGraph()

        if self._graph_config is not None:
            from swarmline.multi_agent.graph_builder import GraphBuilder
            await GraphBuilder.from_dict(self._graph_config, store)
        elif self._graph_yaml is not None:
            from swarmline.multi_agent.graph_builder import GraphBuilder
            await GraphBuilder.from_yaml(self._graph_yaml, store)

        return store

    def _wrap_with_circuit_breaker(
        self, runner: Callable[..., Awaitable[str]],
    ) -> Callable[..., Awaitable[str]]:
        """Wrap runner with per-agent circuit breakers."""
        from swarmline.resilience.circuit_breaker import CircuitBreakerRegistry

        cfg = self._circuit_breaker_config or {}
        registry = CircuitBreakerRegistry(
            failure_threshold=cfg.get("threshold", 3),
            cooldown_seconds=cfg.get("cooldown", 30.0),
        )

        async def wrapped(
            agent_id: str, task_id: str, goal: str, system_prompt: str,
        ) -> str:
            breaker = registry.get(agent_id)
            if not breaker.allow_request():
                raise RuntimeError(
                    f"Circuit breaker OPEN for agent '{agent_id}' — "
                    f"too many consecutive failures"
                )
            try:
                result = await runner(agent_id, task_id, goal, system_prompt)
                breaker.record_success()
                return result
            except Exception:
                breaker.record_failure()
                raise

        return wrapped
