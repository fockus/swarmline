"""Workflow Graph module."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

# Type aliases
State = dict[str, Any]
NodeFn = Callable[[State], Coroutine[Any, Any, State]]
ConditionFn = Callable[[State], str]
NodeInterceptor = Callable[[str, State], Coroutine[Any, Any, State]]

END_NODE = "__end__"


class WorkflowInterrupt(Exception):
    """Raised when execution hits an interrupt node (HITL)."""

    def __init__(self, node_id: str, state: State, graph: WorkflowGraph) -> None:
        self.node_id = node_id
        self.state = state
        self._graph = graph
        super().__init__(f"Workflow interrupted at node '{node_id}'")


@dataclass
class _Edge:
    """Edge in the workflow graph."""

    source: str
    target: str


@dataclass
class _ConditionalEdge:
    """Conditional edge - routes based on state."""

    source: str
    condition: ConditionFn


@dataclass
class _ParallelGroup:
    """Group of nodes to run in parallel."""

    node_ids: list[str]
    then: str  # node to run after all parallel complete
    entry_id: str  # synthetic entry node id


class InMemoryCheckpoint:
    """Simple in-memory checkpoint store for workflow state."""

    def __init__(self) -> None:
        self._states: dict[str, tuple[str, State]] = {}

    def save(self, run_id: str, node_id: str, state: State) -> None:
        self._states[run_id] = (node_id, dict(state))

    def load(self, run_id: str) -> tuple[str, State] | None:
        entry = self._states.get(run_id)
        if entry is None:
            return None
        return entry[0], dict(entry[1])

    def clear(self, run_id: str) -> None:
        self._states.pop(run_id, None)


class WorkflowGraph:
    """Workflow Graph implementation."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._nodes: dict[str, NodeFn | WorkflowGraph] = {}
        self._edges: list[_Edge] = []
        self._conditional_edges: dict[str, _ConditionalEdge] = {}
        self._parallel_groups: dict[str, _ParallelGroup] = {}
        self._interrupts: set[str] = set()
        self._max_loops: dict[str, int] = {}
        self._entry: str | None = None

    def add_node(self, node_id: str, fn: NodeFn | WorkflowGraph) -> None:
        """Add a node (async function or nested WorkflowGraph)."""
        self._nodes[node_id] = fn

    def add_edge(self, source: str, target: str) -> None:
        """Add a directed edge."""
        self._edges.append(_Edge(source=source, target=target))

    def add_conditional_edge(self, source: str, condition: ConditionFn) -> None:
        """Add conditional routing from source based on state."""
        self._conditional_edges[source] = _ConditionalEdge(
            source=source, condition=condition
        )

    def add_parallel(self, node_ids: list[str], then: str) -> None:
        """Register parallel execution group -> converge to 'then' node."""
        entry_id = f"__parallel_{'_'.join(node_ids)}"
        self._parallel_groups[entry_id] = _ParallelGroup(
            node_ids=node_ids, then=then, entry_id=entry_id
        )

    def set_entry(self, node_id: str) -> None:
        """Set the entry point node."""
        self._entry = node_id

    def set_max_loops(self, node_id: str, max_loops: int) -> None:
        """Set maximum loop iterations through a node."""
        self._max_loops[node_id] = max_loops

    def add_interrupt(self, node_id: str) -> None:
        """Mark node as HITL interrupt point."""
        self._interrupts.add(node_id)

    def _get_next(self, node_id: str, state: State) -> str | None:
        """Determine next node from edges or conditional edges."""
        if node_id in self._conditional_edges:
            cond = self._conditional_edges[node_id]
            return cond.condition(state)
        for edge in self._edges:
            if edge.source == node_id:
                return edge.target
        return None

    async def _execute_node(
        self,
        node_id: str,
        state: State,
        interceptor: NodeInterceptor | None = None,
    ) -> State:
        """Execute a single node (function or subgraph).

        If interceptor is provided, it wraps the node execution:
        interceptor receives (node_id, state) and returns the modified state.
        The interceptor is responsible for calling the original node if needed,
        or it can delegate to the default execution and post-process.
        """
        if interceptor is not None:
            return await interceptor(node_id, state)
        node = self._nodes[node_id]
        if isinstance(node, WorkflowGraph):
            return await node.execute(dict(state))
        return await node(state)

    async def execute(
        self,
        initial_state: State,
        *,
        checkpoint: InMemoryCheckpoint | None = None,
        run_id: str | None = None,
        resume: bool = False,
        node_interceptor: NodeInterceptor | None = None,
        _skip_interrupts: frozenset[str] | None = None,
        _start_node: str | None = None,
    ) -> State:
        """Execute the workflow graph from entry to end.

        Args:
          initial_state: Starting state dict.
          checkpoint: Optional checkpoint store for crash recovery.
          run_id: Run identifier for checkpoint keying.
          resume: Whether to resume from a previous checkpoint.
          node_interceptor: Optional callable(node_id, state) -> state that
            wraps each node execution. Used by runtime executors for
            per-node instrumentation (e.g. runtime routing, observability).
          _skip_interrupts: Internal — set of node_ids to skip interrupts for
            in THIS execution only. Used by resume() for concurrency safety.
          _start_node: Internal — override the entry point for THIS execution
            only. Used by resume() for concurrency safety (avoids mutating
            self._entry).
        """
        state = dict(initial_state)
        loop_counts: dict[str, int] = {}
        skip = _skip_interrupts or frozenset()

        # Resume from checkpoint
        start_node = _start_node if _start_node is not None else self._entry
        if resume and checkpoint and run_id:
            saved = checkpoint.load(run_id)
            if saved is not None:
                last_node, saved_state = saved
                state = dict(saved_state)
                state.update(initial_state)
                start_node = last_node

        current = start_node
        if current is None:
            return state

        while current and current != END_NODE:
            # Check parallel group
            if current in self._parallel_groups:
                group = self._parallel_groups[current]
                results = await asyncio.gather(
                    *[
                        self._execute_node(
                            nid, dict(state), interceptor=node_interceptor
                        )
                        for nid in group.node_ids
                    ]
                )
                for r in results:
                    state.update(r)
                current = group.then
                continue

            # Check node exists
            if current not in self._nodes:
                break

            # Check interrupt BEFORE execution (skip if this execution bypasses it)
            if current in self._interrupts and current not in skip:
                raise WorkflowInterrupt(node_id=current, state=state, graph=self)

            # Checkpoint before execution
            if checkpoint and run_id:
                checkpoint.save(run_id, current, state)

            # Execute node
            state = await self._execute_node(
                current, state, interceptor=node_interceptor
            )

            # Track loops
            loop_counts[current] = loop_counts.get(current, 0) + 1
            max_loops = self._max_loops.get(current)
            if max_loops and loop_counts[current] >= max_loops:
                break

            # Get next
            current = self._get_next(current, state)

        return state

    async def resume(
        self, interrupt: WorkflowInterrupt, human_input: State | None = None
    ) -> State:
        """Resume execution after a HITL interrupt.

        Concurrency-safe: does NOT mutate any shared graph state
        (``_interrupts``, ``_entry``). Instead, passes per-execution
        ``_skip_interrupts`` and ``_start_node`` overrides so that only
        THIS resumption skips the interrupt node and starts from the
        correct point. Other concurrent executions on the same graph
        instance are unaffected.
        """
        state = dict(interrupt.state)
        if human_input:
            state.update(human_input)

        # Find next node after the interrupted one
        next_node = self._get_next(interrupt.node_id, state)
        if next_node is None or next_node == END_NODE:
            return state

        # Continue execution from next node, skipping the interrupt
        # only for THIS execution (concurrency-safe, no shared mutation).
        return await self.execute(
            state,
            _skip_interrupts=frozenset({interrupt.node_id}),
            _start_node=next_node,
        )

    def to_mermaid(self) -> str:
        """Generate Mermaid flowchart from graph."""
        lines = ["graph TD"]
        for edge in self._edges:
            lines.append(f"    {edge.source} --> {edge.target}")
        for node_id, _cond_edge in self._conditional_edges.items():
            lines.append(f"    {node_id} -->|condition| ...")
        for entry_id, group in self._parallel_groups.items():
            for nid in group.node_ids:
                lines.append(f"    {entry_id} --> {nid}")
            lines.append(f"    {' & '.join(group.node_ids)} --> {group.then}")
        return "\n".join(lines)
