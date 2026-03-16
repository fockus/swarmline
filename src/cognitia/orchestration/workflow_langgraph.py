"""WorkflowGraph → LangGraph compiler.

Конвертирует WorkflowGraph в LangGraph StateGraph для использования с DeepAgentsRuntime.
Если LangGraph недоступен — raises ImportError с понятным сообщением.
"""

from __future__ import annotations

from typing import Any

from cognitia.orchestration.workflow_graph import END_NODE, WorkflowGraph


def compile_to_langgraph(graph: WorkflowGraph) -> Any:
    """Compile WorkflowGraph → LangGraph StateGraph.

    Маппинг:
    - add_node → StateGraph.add_node
    - add_edge → StateGraph.add_edge
    - add_conditional_edge → StateGraph.add_conditional_edges
    - set_entry → StateGraph.set_entry_point
    - parallel → fan-out/fan-in pattern
    - interrupt → interrupt_before

    Returns compiled LangGraph app.
    Raises ImportError if langgraph not installed.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as e:
        msg = (
            "langgraph package required for LangGraph compilation. "
            "Install: pip install langgraph"
        )
        raise ImportError(msg) from e

    # Build StateGraph with dict state
    sg = StateGraph(dict)

    # Add nodes (subgraphs are wrapped as regular nodes)
    for node_id, node_fn in graph._nodes.items():
        if isinstance(node_fn, WorkflowGraph):
            sub = node_fn

            async def _sub_wrapper(state: dict, _sub: WorkflowGraph = sub) -> dict:
                return await _sub.execute(state)

            sg.add_node(node_id, _sub_wrapper)
        else:
            sg.add_node(node_id, node_fn)

    # Add edges
    for edge in graph._edges:
        target = END if edge.target == END_NODE else edge.target
        sg.add_edge(edge.source, target)

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


def check_langgraph_available() -> bool:
    """Check if langgraph package is available."""
    try:
        import langgraph  # noqa: F401

        return True
    except ImportError:
        return False
