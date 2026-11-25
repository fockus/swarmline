"""Topology compiler: declared ``CompositionSpec`` topology -> a real
``WorkflowGraph``.

graph-composition spec, judge-advisory carve-out from Task 3's review
("graph_assembly.py ends Task 3 at exactly the 400-line NFR-004 ceiling,
with no room left for Task 4's routing work"). This module is a Step-0
PURE MOVE (behavior byte-identical) of Task 3's per-node runner and
topology-to-``WorkflowGraph`` compiler out of ``graph_assembly.py``, which
keeps only the thin factory/runtime shell (``_GraphRuntimeFactory``/
``_GraphAgentRuntime``/``build_graph_agent``). Import direction is
one-way: ``graph_assembly`` imports FROM this module, never the reverse.

Per-node runner (design decision #1, moved verbatim): a closure over a
``WorkerSpec``, building a per-node ``ThinRuntime(config=node_config,
llm_call=None)`` + ``collect_runtime_output(runtime.run(...,
mode_hint=worker.kernel))``. Node task: ``state["last_output"]`` if a
predecessor already ran, else the seeded ``state["input"]``
(prompt-chaining). The worker's text output MUTATES the shared ``outputs``
dict IN PLACE (``state["outputs"][worker.role] = text``) -- required so a
parallel fan-out's sibling writes all survive the substrate's
shallow-copy-per-member semantics (characterization test, design-risk #2);
a NEW top-level dict is then returned with ``last_output``/``last_role``
set, exactly what ``WorkflowGraph.execute`` expects a node function to
return.

Topology compiler (:func:`compile_graph`, moved verbatim from
``_GraphAgentRuntime._compile`` and extended with Task 4's route
compilation, and Task 5's ``(graph, node_runners)`` return -- REQ-008):
builds one node per worker, resolves ``edges``/``parallel``/
``routes`` onto the real ``WorkflowGraph`` (``add_edge``/``add_parallel``/
``add_conditional_edge``), targeting the substrate's OWN synthetic
parallel-group id (``f"__parallel_{'_'.join(members)}"`` -- ``add_parallel``
derives this internally) and ``workflow_graph.END_NODE`` for the ``"END"``
sentinel.

``routes`` (design.md Decision 3, REQ-009/016): each ``RouteSpec`` compiles
to a ``ConditionFn`` closure (:func:`_compile_route`) -- reads
``state[key]`` at run time, maps the value through *mapping* (falling back
to *default* when declared), and resolves the chosen target through the
SAME substrate-id/END resolution every edge goes through. A missing key or
an unmapped value with no default raises :class:`_GraphRouteMiss` (naming
the routing node and the key) instead of returning a sentinel string --
``WorkflowGraph._get_next`` calls the condition synchronously inside
``execute()``'s loop, so the exception propagates straight out of the
``asyncio.Task`` awaiting ``graph.execute(...)``, exactly like a
per-node ``_GraphNodeFailure``. ``graph_validation.validate_graph_topology``
already rejects unknown route targets, duplicate route sources, and
edge+route mixing on the same source at ``build()`` time -- this compiler
trusts a pre-validated ``CompositionSpec`` and does not re-check any of
that.

Import-light (NFR-001): this module's own top-level surface is stdlib +
``harness.spec`` only. ``WorkflowGraph``/``ThinRuntime``/
``collect_runtime_output``/``Message`` are imported lazily, inside
:func:`compile_graph` and the per-node runner closure body, re-resolved on
every call (not cached) so tests patching ``ThinRuntime`` at its own
module still take effect -- mirrors
``_ModeHintRuntimeFactory._delegate``'s documented idiom.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from swarmline.harness.spec import CompositionSpec, RouteSpec, WorkerSpec

State = dict[str, Any]

_END = "END"


class _GraphNodeFailure(Exception):
    """A graph node's underlying runtime call failed. Carries *role* (the
    worker whose node runner raised) so ``_GraphAgentRuntime.run`` can name
    it in the terminal error event (REQ-015)."""

    def __init__(self, role: str, message: str) -> None:
        self.role = role
        self.message = message
        super().__init__(f"graph node {role!r} failed: {message}")


class _GraphRouteMiss(Exception):
    """A compiled route's ``ConditionFn`` could not resolve a target: either
    ``state[key]`` is absent, or its value has no mapping entry and no
    ``default`` is declared (REQ-016). Carries *node* (the route's
    *source*) and *key* so ``_GraphAgentRuntime._run`` can name both in the
    terminal error event."""

    def __init__(self, node: str, key: str) -> None:
        self.node = node
        self.key = key
        super().__init__(
            f"graph route at node {node!r}: state key {key!r} is missing "
            "or its value has no mapped target and no default is declared"
        )


def compile_graph(
    composition: CompositionSpec,
    system_prompt: str,
    node_config: Any,
    composition_factory: Any,
) -> tuple[Any, dict[str, Callable[[State], Any]]]:
    """Compile *composition* onto a fresh ``WorkflowGraph``.

    Moved verbatim from ``_GraphAgentRuntime._compile`` (Task 3) and
    extended with Task 4's route compilation. Targets the substrate's OWN
    synthetic parallel-group id (``f"__parallel_{'_'.join(members)}"`` --
    ``add_parallel`` derives this internally).

    Returns ``(graph, node_runners)`` -- Task 5 (REQ-008) addition:
    *node_runners* is ``{role: the exact closure registered via
    add_node(role, ...)}``, the SAME per-node runner objects the graph
    itself holds. ``_GraphAgentRuntime._run`` needs this map to build its
    ``node_interceptor`` (the interceptor owns "call the real node, emit
    progress around it" -- ``WorkflowGraph._execute_node`` hands full
    responsibility for invoking the node to the interceptor once one is
    supplied, so the interceptor cannot reach the node function any other
    way without reading the graph's private ``_nodes`` mapping).
    """
    from swarmline.orchestration.workflow_graph import END_NODE

    roles = [worker.role for worker in composition.workers]
    workers_by_role = {worker.role: worker for worker in composition.workers}

    # review r2: validate_graph_topology already rejects a role/group
    # collision with this id -- asserts below are defensive only.
    member_target: dict[str, str] = {}
    for group in composition.parallel:
        entry_id = f"__parallel_{'_'.join(group.members)}"
        assert entry_id not in roles
        assert entry_id not in member_target.values()
        for member in group.members:
            member_target[member] = entry_id

    def _resolve(name: str) -> str:
        if name == _END:
            return END_NODE
        return member_target.get(name, name)

    node_runners = {
        role: _make_node_runner(workers_by_role[role], system_prompt, node_config)
        for role in roles
    }

    graph = composition_factory("harness-graph")
    for role in roles:
        graph.add_node(role, node_runners[role])

    edges = composition.edges
    if not edges and not composition.parallel and not composition.routes:
        # REQ-005: nothing declared -> linear chain over workers, in
        # declaration order, ending at END.
        edges = tuple(zip(roles, roles[1:])) + ((roles[-1], _END),)

    for source, target in edges:
        graph.add_edge(source, _resolve(target))

    for group in composition.parallel:
        graph.add_parallel(list(group.members), _resolve(group.then))

    for route in composition.routes:
        graph.add_conditional_edge(route.source, _compile_route(route, _resolve))

    graph.set_entry(_resolve(roles[0]))
    return graph, node_runners


def _compile_route(
    route: RouteSpec, resolve: Callable[[str], str]
) -> Callable[[State], str]:
    """Compile one ``RouteSpec`` into a ``ConditionFn`` closure (design.md
    Decision 3): reads ``state[key]`` at run time, maps the value through
    *route.mapping* (falling back to *route.default* when declared), and
    resolves the chosen target through *resolve* -- the SAME substrate-id/
    END resolution :func:`compile_graph` applies to every edge. Raises
    :class:`_GraphRouteMiss` -- never returns a sentinel string, and never
    an uncaught ``TypeError`` -- when the key is absent from state, or the
    value is unmapped with no default declared, INCLUDING an unhashable
    value (e.g. ``state["outputs"]`` is itself a dict) -- review r2
    (Task 4): such a value can never be a ``dict`` key, so it is simply
    unmapped, same as any other value with no mapping entry (REQ-016)."""
    mapping = dict(route.mapping)

    def _condition(state: State) -> str:
        if route.key not in state:
            raise _GraphRouteMiss(route.source, route.key)
        value = state[route.key]
        try:
            target = mapping.get(value)
        except TypeError:
            target = None
        if target is not None:
            return resolve(target)
        if route.default is not None:
            return resolve(route.default)
        raise _GraphRouteMiss(route.source, route.key)

    return _condition


def _make_node_runner(worker: WorkerSpec, system_prompt: str, node_config: Any) -> Any:
    """Build the per-node execution closure for *worker* (design decision
    #1 -- mirrors ``ThinWorkflowExecutor.run_node`` but pins
    ``mode_hint=worker.kernel``, a parameter ``run_node`` does not expose).

    State contract (design.md): ``task`` is ``state["last_output"]`` if a
    predecessor already ran, else the seeded ``state["input"]``
    (prompt-chaining). The worker's text output MUTATES the shared
    ``outputs`` dict IN PLACE (``state["outputs"][worker.role] = text``) --
    required so a parallel fan-out's sibling writes all survive the
    substrate's shallow-copy-per-member semantics (characterization test,
    design-risk #2); a NEW top-level dict is then returned with
    ``last_output``/``last_role`` set, exactly what ``WorkflowGraph.execute``
    expects a node function to return.
    """

    async def _run_node(state: State) -> State:
        from swarmline.orchestration.runtime_helpers import collect_runtime_output
        from swarmline.runtime.thin.runtime import ThinRuntime
        from swarmline.runtime.types import Message

        task = state.get("last_output") or state["input"]
        node_system_prompt = (
            f"{system_prompt}\n\nYou are the {worker.role!r} worker in this graph."
        )
        runtime = ThinRuntime(config=node_config, llm_call=None)
        try:
            text = await collect_runtime_output(
                runtime.run(
                    messages=[Message(role="user", content=task)],
                    system_prompt=node_system_prompt,
                    active_tools=[],
                    mode_hint=worker.kernel,
                ),
            )
        except Exception as exc:
            raise _GraphNodeFailure(worker.role, str(exc)) from exc

        state["outputs"][worker.role] = text
        return {**state, "last_output": text, "last_role": worker.role}

    return _run_node
