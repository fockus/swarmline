"""Workflow executors — runtime adapters для WorkflowGraph.

ThinWorkflowExecutor: запускает ThinRuntime per-node.
ThinRuntimeExecutor: выполняет workflow nodes напрямую (без LLM).
MixedRuntimeExecutor: routing nodes по runtime_map.
compile_to_langgraph_spec: структурная компиляция в LangGraph-совместимый spec.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cognitia.orchestration.workflow_graph import State, WorkflowGraph
from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import Message, RuntimeConfig


class ThinWorkflowExecutor:
    """Запускает ThinRuntime per-node для workflow execution."""

    def __init__(
        self,
        *,
        llm_call: Callable[..., Any],
        local_tools: dict[str, Callable[..., Any]] | None = None,
        mcp_servers: dict[str, Any] | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        self._llm_call = llm_call
        self._local_tools = local_tools or {}
        self._mcp_servers = mcp_servers
        self._runtime_config = runtime_config or RuntimeConfig(runtime_name="thin")

    async def run_node(
        self,
        system_prompt: str,
        task: str,
        state: dict[str, Any],
    ) -> str:
        """Выполнить один node через ThinRuntime. Возвращает финальный текст."""
        runtime = ThinRuntime(
            config=self._runtime_config,
            llm_call=self._llm_call,
            local_tools=self._local_tools,
            mcp_servers=self._mcp_servers,
        )
        final_text = ""
        async for event in runtime.run(
            messages=[Message(role="user", content=task)],
            system_prompt=system_prompt,
            active_tools=[],
            mode_hint="react",
        ):
            if event.type == "final":
                final_text = str(event.data.get("text", final_text))
            elif event.type == "assistant_delta":
                final_text += str(event.data.get("text", ""))
        return final_text


class ThinRuntimeExecutor:
    """Выполняет WorkflowGraph nodes напрямую через node functions.

    Thin runtime: node functions вызываются как есть, без LLM overhead.
    Используется когда nodes — Python functions, а не LLM prompts.
    """

    async def run(self, wf: WorkflowGraph, initial_state: State) -> State:
        """Выполнить граф, вызывая node functions напрямую."""
        return await wf.execute(initial_state)


class MixedRuntimeExecutor:
    """Выполняет WorkflowGraph с routing nodes по runtime_map.

    Каждый node может быть назначен своему runtime ("thin", "deepagents", etc.).
    Nodes без mapping выполняются напрямую (thin fallback).
    """

    def __init__(self, runtime_map: dict[str, str]) -> None:
        self._runtime_map = runtime_map

    async def run(self, wf: WorkflowGraph, initial_state: State) -> State:
        """Выполнить граф с per-node runtime routing."""
        # Wraps each node: if mapped — can add runtime-specific instrumentation.
        # Currently all runtimes execute node fns directly; routing is recorded in state.
        original_execute = wf._execute_node

        async def _routed_execute(node_id: str, state: State) -> State:
            runtime_name = self._runtime_map.get(node_id, "thin")
            state = await original_execute(node_id, state)
            # Record which runtime handled this node (for observability)
            executions: dict[str, str] = state.get("__runtime_executions__", {})
            executions[node_id] = runtime_name
            state["__runtime_executions__"] = executions
            return state

        wf._execute_node = _routed_execute  # type: ignore[assignment]
        try:
            return await wf.execute(initial_state)
        finally:
            wf._execute_node = original_execute  # type: ignore[assignment]


def compile_to_langgraph_spec(wf: WorkflowGraph) -> dict[str, Any]:
    """Компилировать WorkflowGraph в LangGraph-совместимый spec.

    Возвращает dict с nodes, edges, entry — достаточно для
    конструирования LangGraph StateGraph (zero overhead pass-through).
    """
    nodes: dict[str, Any] = {}
    for node_id, node_fn in wf._nodes.items():
        nodes[node_id] = node_fn

    edges: list[tuple[str, str]] = []
    for edge in wf._edges:
        edges.append((edge.source, edge.target))

    conditional_edges: dict[str, Any] = {}
    for node_id, cond_edge in wf._conditional_edges.items():
        conditional_edges[node_id] = cond_edge.condition

    return {
        "name": wf.name,
        "entry": wf._entry,
        "nodes": nodes,
        "edges": edges,
        "conditional_edges": conditional_edges,
    }
