"""E2E: WorkflowGraph - raznye patterny vypolnotniya. Linear, conditional, loop, parallel, ThinRuntime nodes.
Real komponotnty: WorkflowGraph, ThinWorkflowExecutor.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from swarmline.orchestration.workflow_executor import (
    ThinRuntimeExecutor,
    ThinWorkflowExecutor,
)
from swarmline.orchestration.workflow_graph import END_NODE, WorkflowGraph
from swarmline.runtime.types import RuntimeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

State = dict[str, Any]


def _final_envelope(text: str) -> str:
    return json.dumps({"type": "final", "final_message": text})


# ---------------------------------------------------------------------------
# 1. Linear three nodes
# ---------------------------------------------------------------------------


class TestWorkflowLinearE2E:
    """WorkflowGraph: A -> B -> C, each node = async function."""

    @pytest.mark.asyncio
    async def test_workflow_linear_three_nodes(self) -> None:
        """Linotynyy graf: state flows through all nodes, final state correct."""
        graph = WorkflowGraph(name="linear_test")

        async def node_a(state: State) -> State:
            state["step_a"] = "processed"
            state["order"] = state.get("order", []) + ["a"]
            return state

        async def node_b(state: State) -> State:
            state["step_b"] = "enriched"
            state["order"] = state.get("order", []) + ["b"]
            return state

        async def node_c(state: State) -> State:
            state["step_c"] = "finalized"
            state["order"] = state.get("order", []) + ["c"]
            return state

        graph.add_node("a", node_a)
        graph.add_node("b", node_b)
        graph.add_node("c", node_c)
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")
        graph.add_edge("c", END_NODE)
        graph.set_entry("a")

        result = await graph.execute({"input": "data"})

        assert result["step_a"] == "processed"
        assert result["step_b"] == "enriched"
        assert result["step_c"] == "finalized"
        assert result["order"] == ["a", "b", "c"], (
            "Nodes выполнены в правильном порядке"
        )
        assert result["input"] == "data", "Исходные данные сохранены"


# ---------------------------------------------------------------------------
# 2. Conditional branch
# ---------------------------------------------------------------------------


class TestWorkflowConditionalE2E:
    """WorkflowGraph: start -> [condition] -> path_a OR path_b -> end."""

    @pytest.mark.asyncio
    async def test_workflow_conditional_branch_path_a(self) -> None:
        """Condition on osnove state value -> vybiraet path_a."""
        graph = WorkflowGraph(name="conditional_test")

        async def start_node(state: State) -> State:
            state["analyzed"] = True
            return state

        async def path_a(state: State) -> State:
            state["path"] = "a"
            state["result"] = "handled by path A"
            return state

        async def path_b(state: State) -> State:
            state["path"] = "b"
            state["result"] = "handled by path B"
            return state

        graph.add_node("start", start_node)
        graph.add_node("path_a", path_a)
        graph.add_node("path_b", path_b)

        graph.add_conditional_edge(
            "start",
            condition=lambda s: "path_a" if s.get("route") == "a" else "path_b",
        )
        graph.add_edge("path_a", END_NODE)
        graph.add_edge("path_b", END_NODE)
        graph.set_entry("start")

        # Route to A
        result_a = await graph.execute({"route": "a"})
        assert result_a["path"] == "a"
        assert result_a["result"] == "handled by path A"

    @pytest.mark.asyncio
    async def test_workflow_conditional_branch_path_b(self) -> None:
        """Condition on osnove state value -> vybiraet path_b."""
        graph = WorkflowGraph(name="conditional_test_b")

        async def start_node(state: State) -> State:
            state["analyzed"] = True
            return state

        async def path_a(state: State) -> State:
            state["path"] = "a"
            return state

        async def path_b(state: State) -> State:
            state["path"] = "b"
            state["result"] = "handled by path B"
            return state

        graph.add_node("start", start_node)
        graph.add_node("path_a", path_a)
        graph.add_node("path_b", path_b)

        graph.add_conditional_edge(
            "start",
            condition=lambda s: "path_a" if s.get("route") == "a" else "path_b",
        )
        graph.add_edge("path_a", END_NODE)
        graph.add_edge("path_b", END_NODE)
        graph.set_entry("start")

        result_b = await graph.execute({"route": "b"})
        assert result_b["path"] == "b"
        assert result_b["result"] == "handled by path B"


# ---------------------------------------------------------------------------
# 3. Loop with retry
# ---------------------------------------------------------------------------


class TestWorkflowLoopE2E:
    """WorkflowGraph: process -> verify -> [if fail: loop back, max 3]."""

    @pytest.mark.asyncio
    async def test_workflow_loop_with_retry(self) -> None:
        """Pervye 2 popytki fail, 3-ya succeeds. Verify loop count."""
        graph = WorkflowGraph(name="loop_test")

        async def process(state: State) -> State:
            attempt = state.get("attempt", 0) + 1
            state["attempt"] = attempt
            state["output"] = f"result_attempt_{attempt}"
            return state

        async def verify(state: State) -> State:
            attempt = state.get("attempt", 0)
            if attempt >= 3:
                state["verified"] = True
            else:
                state["verified"] = False
            return state

        graph.add_node("process", process)
        graph.add_node("verify", verify)
        graph.add_edge("process", "verify")

        # Conditional: if verified -> end, inache -> process (loop)
        graph.add_conditional_edge(
            "verify",
            condition=lambda s: END_NODE if s.get("verified") else "process",
        )
        graph.set_entry("process")
        # Safety: max 5 loops cherez process
        graph.set_max_loops("process", max_loops=5)

        result = await graph.execute({})

        assert result["verified"] is True, "После 3 попыток должно быть verified"
        assert result["attempt"] == 3, "Должно быть ровно 3 попытки"
        assert result["output"] == "result_attempt_3"


# ---------------------------------------------------------------------------
# 4. Parallel execution
# ---------------------------------------------------------------------------


class TestWorkflowParallelE2E:
    """WorkflowGraph: start -> parallel(a, b, c) -> merge."""

    @pytest.mark.asyncio
    async def test_workflow_parallel_execution(self) -> None:
        """Parallel: 3 nodes run in parallel, results merge in state."""
        graph = WorkflowGraph(name="parallel_test")

        async def node_a(state: State) -> State:
            return {**state, "result_a": "data_from_a"}

        async def node_b(state: State) -> State:
            return {**state, "result_b": "data_from_b"}

        async def node_c(state: State) -> State:
            return {**state, "result_c": "data_from_c"}

        async def merge(state: State) -> State:
            state["merged"] = True
            state["all_results"] = [
                state.get("result_a", ""),
                state.get("result_b", ""),
                state.get("result_c", ""),
            ]
            return state

        graph.add_node("a", node_a)
        graph.add_node("b", node_b)
        graph.add_node("c", node_c)
        graph.add_node("merge", merge)

        graph.add_parallel(["a", "b", "c"], then="merge")
        graph.add_edge("merge", END_NODE)

        # Entry = parallel group synthetic id
        entry_id = "__parallel_a_b_c"
        graph.set_entry(entry_id)

        result = await graph.execute({"initial": True})

        assert result.get("result_a") == "data_from_a"
        assert result.get("result_b") == "data_from_b"
        assert result.get("result_c") == "data_from_c"
        assert result["merged"] is True
        assert len(result["all_results"]) == 3
        assert all(r.startswith("data_from_") for r in result["all_results"])


# ---------------------------------------------------------------------------
# 5. Workflow with ThinRuntime nodes
# ---------------------------------------------------------------------------


class TestWorkflowWithThinRuntimeE2E:
    """WorkflowGraph + ThinWorkflowExecutor: kazhdyy node = ThinRuntime call."""

    @pytest.mark.asyncio
    async def test_workflow_with_thin_runtime_nodes(self) -> None:
        """End-to-end ot graph definition do final result with real ThinRuntime."""
        llm_call_count = 0

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            nonlocal llm_call_count
            llm_call_count += 1
            user_text = next(
                (m["content"] for m in messages if m["role"] == "user"), ""
            )
            return _final_envelope(f"LLM processed: {user_text[:30]}")

        executor = ThinWorkflowExecutor(
            llm_call=fake_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        graph = WorkflowGraph(name="runtime_workflow")

        # Create node functions, kotorye vyzyvayut ThinRuntime cherez executor
        async def analyze_node(state: State) -> State:
            result = await executor.run_node(
                system_prompt="Analyze data",
                task=state.get("task", "analyze"),
                state=state,
            )
            state["analysis"] = result
            return state

        async def summarize_node(state: State) -> State:
            result = await executor.run_node(
                system_prompt="Summarize findings",
                task=f"Summarize: {state.get('analysis', '')}",
                state=state,
            )
            state["summary"] = result
            return state

        graph.add_node("analyze", analyze_node)
        graph.add_node("summarize", summarize_node)
        graph.add_edge("analyze", "summarize")
        graph.add_edge("summarize", END_NODE)
        graph.set_entry("analyze")

        result = await graph.execute({"task": "Analyze AI market trends"})

        assert "analysis" in result, "Должен быть результат analysis"
        assert "summary" in result, "Должен быть результат summary"
        assert result["analysis"], "Analysis не должен быть пустым"
        assert result["summary"], "Summary не должен быть пустым"
        assert llm_call_count >= 2, "LLM должна быть вызвана минимум 2 раза (по node)"

    @pytest.mark.asyncio
    async def test_thin_runtime_executor_direct(self) -> None:
        """ThinRuntimeExecutor: pryamoy call node functions without LLM."""
        graph = WorkflowGraph(name="direct_test")

        async def double_node(state: State) -> State:
            state["value"] = state.get("value", 0) * 2
            return state

        async def add_ten(state: State) -> State:
            state["value"] = state.get("value", 0) + 10
            return state

        graph.add_node("double", double_node)
        graph.add_node("add_ten", add_ten)
        graph.add_edge("double", "add_ten")
        graph.add_edge("add_ten", END_NODE)
        graph.set_entry("double")

        executor = ThinRuntimeExecutor()
        result = await executor.run(graph, {"value": 5})

        assert result["value"] == 20, "5 * 2 + 10 = 20"
