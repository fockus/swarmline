"""Workflow Langgraph module."""

from __future__ import annotations

from typing import Any

from swarmline.orchestration.workflow_graph import END_NODE, WorkflowGraph


async def _parallel_entry_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthetic no-op node used to represent WorkflowGraph parallel entrypoints."""
    return state


def compile_to_langgraph(graph: WorkflowGraph) -> Any:
    """Compile to langgraph."""
    try:
        from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]
    except ImportError as e:
        msg = (
            "langgraph package required for LangGraph compilation. "
            "Install: pip install langgraph"
        )
        raise ImportError(msg) from e

    # Build StateGraph with dict state
    sg: Any = StateGraph(dict)  # type: ignore[type-var]

    # Add nodes (subgraphs are wrapped as regular nodes)
    for node_id, node_fn in graph._nodes.items():
        if isinstance(node_fn, WorkflowGraph):
            sub = node_fn

            async def _sub_wrapper(state: dict, _sub: WorkflowGraph = sub) -> dict:
                return await _sub.execute(state)

            sg.add_node(node_id, _sub_wrapper)
        else:
            sg.add_node(node_id, node_fn)

    for entry_id in graph._parallel_groups:
        if entry_id not in graph._nodes:
            sg.add_node(entry_id, _parallel_entry_node)

    # Add edges
    for edge in graph._edges:
        target = END if edge.target == END_NODE else edge.target
        sg.add_edge(edge.source, target)

    for group in graph._parallel_groups.values():
        for node_id in group.node_ids:
            sg.add_edge(group.entry_id, node_id)
            target = END if group.then == END_NODE else group.then
            sg.add_edge(node_id, target)

    # Add conditional edges
    for node_id, cond_edge in graph._conditional_edges.items():

        def _make_router(cond: Any = cond_edge.condition) -> Any:
            def router(state: dict) -> str:
                result = cond(state)
                return END if result == END_NODE else result

            return router

        sg.add_conditional_edges(node_id, _make_router())

    # Set entry point
    if graph._entry:
        sg.set_entry_point(graph._entry)

    # Compile with interrupt_before for HITL nodes
    compile_kwargs: dict[str, Any] = {}
    if graph._interrupts:
        compile_kwargs["interrupt_before"] = list(graph._interrupts)

    return sg.compile(**compile_kwargs)
