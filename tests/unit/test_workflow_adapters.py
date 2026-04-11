"""TDD RED: Runtime adapters for WorkflowGraph. CRP-4.2: thin executor, LangGraph compiler (stub), mixed runtimes.
"""

from __future__ import annotations

import json

from swarmline.orchestration.workflow_graph import WorkflowGraph


class TestWorkflowThinExecutor:
    """Workflow runs via ThinRuntime per node."""

    async def test_workflow_thin_executor(self) -> None:
        from swarmline.orchestration.workflow_executor import ThinWorkflowExecutor

        async def mock_llm_call(messages, system_prompt, **kwargs):
            return json.dumps({"type": "final", "final_message": "node done"})

        executor = ThinWorkflowExecutor(llm_call=mock_llm_call)

        wf = WorkflowGraph("thin-exec-test")

        async def node_a(state: dict) -> dict:
            result = await executor.run_node("researcher", "Research topic X", state)
            state["research"] = result
            return state

        async def node_b(state: dict) -> dict:
            result = await executor.run_node("planner", "Make a plan", state)
            state["plan"] = result
            return state

        wf.add_node("research", node_a)
        wf.add_node("plan", node_b)
        wf.add_edge("research", "plan")
        wf.set_entry("research")

        result = await wf.execute({})
        assert "research" in result
        assert "plan" in result


class TestWorkflowDeepAgentsLangGraphCompile:
    """WorkflowGraph → LangGraph StateGraph (structural check)."""

    async def test_workflow_deepagents_langgraph_compile(self) -> None:
        from swarmline.orchestration.workflow_executor import compile_to_langgraph_spec

        wf = WorkflowGraph("langgraph-test")

        async def noop(state: dict) -> dict:
            return state

        wf.add_node("a", noop)
        wf.add_node("b", noop)
        wf.add_edge("a", "b")
        wf.set_entry("a")

        spec = compile_to_langgraph_spec(wf)
        assert spec["entry"] == "a"
        assert "a" in spec["nodes"]
        assert "b" in spec["nodes"]
        assert ("a", "b") in spec["edges"]


class TestWorkflowMixedRuntimes:
    """node A (thin) → node B (different callable) — mixed execution."""

    async def test_workflow_mixed_runtimes(self) -> None:
        thin_called = False
        other_called = False

        async def thin_node(state: dict) -> dict:
            nonlocal thin_called
            thin_called = True
            state["thin_result"] = "thin output"
            return state

        async def other_node(state: dict) -> dict:
            nonlocal other_called
            other_called = True
            state["other_result"] = "other output"
            return state

        wf = WorkflowGraph("mixed-test")
        wf.add_node("thin_step", thin_node)
        wf.add_node("other_step", other_node)
        wf.add_edge("thin_step", "other_step")
        wf.set_entry("thin_step")

        result = await wf.execute({})
        assert thin_called
        assert other_called
        assert result["thin_result"] == "thin output"
        assert result["other_result"] == "other output"
