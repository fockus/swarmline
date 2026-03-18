"""Workflow Executor module."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from cognitia.orchestration.runtime_helpers import collect_runtime_output
from cognitia.orchestration.workflow_graph import State, WorkflowGraph
from cognitia.runtime.thin.runtime import ThinRuntime
from cognitia.runtime.types import Message, RuntimeConfig, ToolSpec


async def _parallel_entry_node(state: dict[str, Any]) -> dict[str, Any]:
    """Synthetic no-op node used to preserve parallel entrypoints in specs."""
    return state


class ThinWorkflowExecutor:
    """Thin Workflow Executor implementation."""

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
        """Run node."""
        runtime = ThinRuntime(
            config=self._runtime_config,
            llm_call=self._llm_call,
            local_tools=self._local_tools,
            mcp_servers=self._mcp_servers,
        )
        return await collect_runtime_output(
            runtime.run(
                messages=[Message(role="user", content=task)],
                system_prompt=system_prompt,
                active_tools=_build_active_tools(self._local_tools),
                mode_hint="react",
            ),
        )


class ThinRuntimeExecutor:
    """Thin Runtime Executor implementation."""

    async def run(self, wf: WorkflowGraph, initial_state: State) -> State:
        """Run."""
        return await wf.execute(initial_state)


class MixedRuntimeExecutor:
    """Mixed Runtime Executor implementation."""

    def __init__(self, runtime_map: dict[str, str]) -> None:
        self._runtime_map = runtime_map

    async def run(self, wf: WorkflowGraph, initial_state: State) -> State:
        """Run."""

        async def _observability_interceptor(node_id: str, state: State) -> State:
            runtime_name = self._runtime_map.get(node_id, "thin")
            # Execute node via the graph's default mechanism (no interceptor recursion).
            # This executor only records metadata; it does not route execution.
            state = await wf._execute_node(node_id, state)
            # Record which runtime was associated with this node (for observability).
            executions: dict[str, str] = state.get("__runtime_executions__", {})
            executions[node_id] = runtime_name
            state["__runtime_executions__"] = executions
            return state

        return await wf.execute(initial_state, node_interceptor=_observability_interceptor)


def _build_active_tools(local_tools: dict[str, Callable[..., Any]]) -> list[ToolSpec]:
    """Build ToolSpec list for local tools so runtimes can advertise them."""
    active_tools: list[ToolSpec] = []
    for tool_name, tool in local_tools.items():
        tool_definition = getattr(tool, "__tool_definition__", None)
        if tool_definition is not None:
            active_tools.append(tool_definition.to_tool_spec())
            continue

        description = ""
        doc = inspect.getdoc(tool)
        if doc:
            description = doc.strip().split("\n")[0].strip()

        active_tools.append(
            ToolSpec(
                name=tool_name,
                description=description,
                parameters={},
                is_local=True,
            ),
        )

    return active_tools


def compile_to_langgraph_spec(wf: WorkflowGraph) -> dict[str, Any]:
    """Compile to langgraph spec."""
    nodes: dict[str, Any] = {}
    for node_id, node_fn in wf._nodes.items():
        nodes[node_id] = node_fn

    parallel_groups: dict[str, dict[str, Any]] = {}
    for entry_id, group in wf._parallel_groups.items():
        parallel_groups[entry_id] = {
            "node_ids": list(group.node_ids),
            "then": group.then,
        }
        nodes.setdefault(entry_id, _parallel_entry_node)

    edges: list[tuple[str, str]] = []
    for edge in wf._edges:
        edges.append((edge.source, edge.target))
    for entry_id, group in wf._parallel_groups.items():
        for node_id in group.node_ids:
            edges.append((entry_id, node_id))
            edges.append((node_id, group.then))

    conditional_edges: dict[str, Any] = {}
    for node_id, cond_edge in wf._conditional_edges.items():
        conditional_edges[node_id] = cond_edge.condition

    return {
        "name": wf.name,
        "entry": wf._entry,
        "nodes": nodes,
        "edges": edges,
        "conditional_edges": conditional_edges,
        "parallel_groups": parallel_groups,
    }
