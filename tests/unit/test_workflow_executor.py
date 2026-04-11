"""Tests WorkflowExecutor - runtime adapters for WorkflowGraph. CRP-4.2: thin executor, LangGraph compiler, mixed runtimes.
"""

from __future__ import annotations

from typing import Any

from swarmline.agent.tool import tool
from swarmline.orchestration.workflow_graph import WorkflowGraph


class TestWorkflowThinExecutor:
    """Workflow runs via ThinRuntimeExecutor per node."""

    async def test_workflow_thin_executor_executes_linear_graph(self) -> None:
        """ThinRuntimeExecutor executes linotynyy graf - vse nodes vyzyvayutsya."""
        from swarmline.orchestration.workflow_executor import ThinRuntimeExecutor

        async def step1(state: dict[str, Any]) -> dict[str, Any]:
            state.setdefault("execution_order", []).append("STEP1")
            return state

        async def step2(state: dict[str, Any]) -> dict[str, Any]:
            state.setdefault("execution_order", []).append("STEP2")
            return state

        wf = WorkflowGraph("thin-exec-test")
        wf.add_node("step1", step1)
        wf.add_node("step2", step2)
        wf.add_edge("step1", "step2")
        wf.set_entry("step1")

        executor = ThinRuntimeExecutor()
        result = await executor.run(wf, initial_state={})

        assert result["execution_order"] == ["STEP1", "STEP2"]

    async def test_workflow_thin_executor_propagates_state(self) -> None:
        """ThinRuntimeExecutor passes state mezhdu nodes - dannye not teryayutsya."""
        from swarmline.orchestration.workflow_executor import ThinRuntimeExecutor

        async def producer(state: dict[str, Any]) -> dict[str, Any]:
            state["payload"] = {"key": "value", "count": 42}
            return state

        async def consumer(state: dict[str, Any]) -> dict[str, Any]:
            payload = state.get("payload", {})
            state["consumed"] = payload.get("count", 0) * 2
            return state

        wf = WorkflowGraph("state-propagation")
        wf.add_node("producer", producer)
        wf.add_node("consumer", consumer)
        wf.add_edge("producer", "consumer")
        wf.set_entry("producer")

        executor = ThinRuntimeExecutor()
        result = await executor.run(wf, initial_state={})

        # Dannye from producer doshli do consumer
        assert result["consumed"] == 84

    async def test_workflow_thin_executor_with_llm_call(self) -> None:
        """ThinWorkflowExecutor.run_node executes ThinRuntime per-node cherez llm_call."""
        import json

        from swarmline.orchestration.workflow_executor import ThinWorkflowExecutor

        llm_calls: list[str] = []

        async def mock_llm_call(messages, system_prompt, **kwargs):
            llm_calls.append(system_prompt)
            return json.dumps({"type": "final", "final_message": "node done"})

        executor = ThinWorkflowExecutor(llm_call=mock_llm_call)

        wf = WorkflowGraph("thin-llm-test")

        async def node_a(state: dict[str, Any]) -> dict[str, Any]:
            result = await executor.run_node("research agent", "Research topic X", state)
            state["research"] = result
            return state

        async def node_b(state: dict[str, Any]) -> dict[str, Any]:
            result = await executor.run_node("planner agent", "Make a plan", state)
            state["plan"] = result
            return state

        wf.add_node("research", node_a)
        wf.add_node("plan", node_b)
        wf.add_edge("research", "plan")
        wf.set_entry("research")

        result = await wf.execute({})

        # Oba nodes vypolnilis and zapisali result
        assert "research" in result
        assert "plan" in result
        # llm_call vyzyvalsya dvazhdy (by odnomu razu on kazhdyy node)
        assert len(llm_calls) == 2

    async def test_workflow_thin_executor_advertises_local_tools(self) -> None:
        """Local tools popadayut in active_tools for runtime advertising."""
        import json

        import swarmline.orchestration.workflow_executor as workflow_executor_module
        from swarmline.orchestration.workflow_executor import ThinWorkflowExecutor
        from swarmline.runtime.types import RuntimeEvent, ToolSpec

        captured_active_tools: list[ToolSpec] = []

        @tool("calc", description="Calculate values")
        async def calc(value: int) -> int:
            return value * 2

        async def summarize(text: str) -> str:
            """Summarize text."""
            return text.upper()

        class FakeRuntime:
            def __init__(
                self,
                *,
                config,
                llm_call,
                local_tools,
                mcp_servers,
            ) -> None:
                self.config = config
                self.llm_call = llm_call
                self.local_tools = local_tools
                self.mcp_servers = mcp_servers

            async def run(self, *, messages, system_prompt, active_tools, mode_hint):
                captured_active_tools.extend(active_tools)
                yield RuntimeEvent.final(
                    text=json.dumps({"ok": True}),
                    new_messages=[],
                )

        executor = ThinWorkflowExecutor(
            llm_call=lambda *args, **kwargs: None,
            local_tools={"calc": calc, "summarize": summarize},
        )

        original_runtime = workflow_executor_module.ThinRuntime
        workflow_executor_module.ThinRuntime = FakeRuntime  # type: ignore[assignment]
        try:
            result = await executor.run_node("system", "task", {})
        finally:
            workflow_executor_module.ThinRuntime = original_runtime  # type: ignore[assignment]

        assert result == json.dumps({"ok": True})
        assert [spec.name for spec in captured_active_tools] == ["calc", "summarize"]
        assert captured_active_tools[0].description == "Calculate values"
        assert captured_active_tools[0].is_local is True
        assert captured_active_tools[1].description == "Summarize text."
        assert captured_active_tools[1].parameters == {}


class TestWorkflowLangGraphCompile:
    """WorkflowGraph → LangGraph StateGraph compile."""

    def test_workflow_langgraph_compile_raises_import_error_if_not_installed(self) -> None:
        """compile_to_langgraph raises ImportError if langgraph not ustanovlen."""
        from swarmline.orchestration.workflow_langgraph import compile_to_langgraph

        async def noop(state: dict[str, Any]) -> dict[str, Any]:
            return state

        wf = WorkflowGraph("lg-test")
        wf.add_node("a", noop)
        wf.add_node("b", noop)
        wf.add_edge("a", "b")
        wf.set_entry("a")

        # If langgraph ustanovlen - returns obekt with invoke/ainvoke.
        # If nott - podnimaet ImportError with upominaniem langgraph.
        try:
            compiled = compile_to_langgraph(wf)
            assert hasattr(compiled, "invoke") or hasattr(compiled, "ainvoke")
        except ImportError as exc:
            assert "langgraph" in str(exc).lower()

    def test_workflow_langgraph_spec_has_correct_structure(self) -> None:
        """compile_to_langgraph_spec returns dict with nodes, edges, entry."""
        from swarmline.orchestration.workflow_executor import compile_to_langgraph_spec

        async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
            return state

        wf = WorkflowGraph("spec-test")
        wf.add_node("start", node_fn)
        wf.add_node("end", node_fn)
        wf.add_edge("start", "end")
        wf.set_entry("start")

        spec = compile_to_langgraph_spec(wf)

        assert spec["entry"] == "start"
        assert "start" in spec["nodes"]
        assert "end" in spec["nodes"]
        assert ("start", "end") in spec["edges"]

    def test_workflow_langgraph_spec_preserves_parallel_groups(self) -> None:
        from swarmline.orchestration.workflow_executor import compile_to_langgraph_spec

        async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
            return state

        wf = WorkflowGraph("parallel-spec")
        wf.add_node("a", node_fn)
        wf.add_node("b", node_fn)
        wf.add_node("c", node_fn)
        wf.add_node("d", node_fn)
        wf.add_parallel(["a", "b", "c"], then="d")
        wf.set_entry("__parallel_a_b_c")

        spec = compile_to_langgraph_spec(wf)

        assert spec["entry"] == "__parallel_a_b_c"
        assert "__parallel_a_b_c" in spec["nodes"]
        assert ("__parallel_a_b_c", "a") in spec["edges"]
        assert ("__parallel_a_b_c", "b") in spec["edges"]
        assert ("__parallel_a_b_c", "c") in spec["edges"]
        assert spec["parallel_groups"]["__parallel_a_b_c"] == {
            "node_ids": ["a", "b", "c"],
            "then": "d",
        }


class TestWorkflowMixedRuntimes:
    """Mixed runtimes: observability metadata per node."""

    async def test_workflow_mixed_runtimes_records_runtime_per_node(self) -> None:
        """MixedRuntimeExecutor zapisyvaet __runtime_executions__ in state for observability."""
        from swarmline.orchestration.workflow_executor import MixedRuntimeExecutor

        async def thin_node(state: dict[str, Any]) -> dict[str, Any]:
            state["thin_done"] = True
            return state

        async def deep_node(state: dict[str, Any]) -> dict[str, Any]:
            state["deep_done"] = True
            return state

        wf = WorkflowGraph("mixed-runtimes")
        wf.add_node("thin_step", thin_node)
        wf.add_node("deep_step", deep_node)
        wf.add_edge("thin_step", "deep_step")
        wf.set_entry("thin_step")

        executor = MixedRuntimeExecutor(
            runtime_map={
                "thin_step": "thin",
                "deep_step": "deepagents",
            }
        )
        result = await executor.run(wf, initial_state={})

        # Oba nodes vypolnilis
        assert result["thin_done"] is True
        assert result["deep_done"] is True
        # Metadannye o runtime routing zapisany in state
        assert result["__runtime_executions__"]["thin_step"] == "thin"
        assert result["__runtime_executions__"]["deep_step"] == "deepagents"

    async def test_workflow_mixed_runtimes_unmapped_node_uses_thin_fallback(self) -> None:
        """Node without mapping gets thin metadata, no execution stays direct."""
        from swarmline.orchestration.workflow_executor import MixedRuntimeExecutor

        async def unmapped_node(state: dict[str, Any]) -> dict[str, Any]:
            state["unmapped_done"] = True
            return state

        wf = WorkflowGraph("fallback-test")
        wf.add_node("unmapped", unmapped_node)
        wf.set_entry("unmapped")

        # Empty runtime_map - node "unmapped" not imeet naznachennogo runtime
        executor = MixedRuntimeExecutor(runtime_map={})
        result = await executor.run(wf, initial_state={})

        assert result["unmapped_done"] is True
        # Fallback runtime zapisyvaetsya kak "thin"
        assert result["__runtime_executions__"]["unmapped"] == "thin"
