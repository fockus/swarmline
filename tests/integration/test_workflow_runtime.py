"""Integration: WorkflowGraph + ThinWorkflowExecutor - 3 nodes pipeline. 3 nodes (research -> analyze -> report), kazhdyy node = fake LLM call cherez ThinRuntime.
Check: state propagation mezhdu nodes, final state contains results vseh nodes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cognitia.orchestration.workflow_executor import ThinWorkflowExecutor
from cognitia.orchestration.workflow_graph import END_NODE, State, WorkflowGraph
from cognitia.runtime.types import RuntimeConfig


class TestWorkflowGraphWithThinRuntimeNodes:
    """WorkflowGraph + ThinWorkflowExecutor: 3 nodes pipeline."""

    @pytest.mark.asyncio
    async def test_workflow_graph_with_thin_runtime_nodes(self) -> None:
        """3 nodes: research -> analyze -> report. State propagates correctly."""
        call_log: list[str] = []

        async def fake_llm(
            messages: list[dict[str, str]], system_prompt: str, **kwargs: Any
        ) -> str:
            """Fake LLM: returns final with contextom from system_prompt."""
            # Izvlekaem klyuchevoe slovo from system_prompt for routing
            if "research" in system_prompt.lower():
                call_log.append("research")
                return json.dumps(
                    {"type": "final", "final_message": "Research: market is growing 15% YoY"}
                )
            if "analy" in system_prompt.lower():
                call_log.append("analyze")
                return json.dumps(
                    {"type": "final", "final_message": "Analysis: strong growth trajectory"}
                )
            call_log.append("report")
            return json.dumps(
                {"type": "final", "final_message": "Report: recommend investment"}
            )

        executor = ThinWorkflowExecutor(
            llm_call=fake_llm,
            runtime_config=RuntimeConfig(runtime_name="thin"),
        )

        # Create node functions, kotorye vyzyvayut ThinRuntime cherez executor
        async def research_node(state: State) -> State:
            result = await executor.run_node(
                system_prompt="You are a researcher. Research the topic.",
                task=state.get("task", "no task"),
                state=state,
            )
            state["research_result"] = result
            return state

        async def analyze_node(state: State) -> State:
            result = await executor.run_node(
                system_prompt="You are an analyst. Analyze the data.",
                task=f"Analyze: {state.get('research_result', '')}",
                state=state,
            )
            state["analysis_result"] = result
            return state

        async def report_node(state: State) -> State:
            result = await executor.run_node(
                system_prompt="You are a report writer. Write the report.",
                task=f"Report on: {state.get('analysis_result', '')}",
                state=state,
            )
            state["report_result"] = result
            return state

        # Collect graf
        graph = WorkflowGraph(name="research_pipeline")
        graph.add_node("research", research_node)
        graph.add_node("analyze", analyze_node)
        graph.add_node("report", report_node)

        graph.set_entry("research")
        graph.add_edge("research", "analyze")
        graph.add_edge("analyze", "report")
        graph.add_edge("report", END_NODE)

        # Run
        initial_state: State = {"task": "Market analysis for Q4 2025"}
        final_state = await graph.execute(initial_state)

        # Verify state propagation - vse 3 resulta prisutstvuyut
        assert "research_result" in final_state
        assert "analysis_result" in final_state
        assert "report_result" in final_state

        # Content resultov
        assert "market is growing" in final_state["research_result"]
        assert "growth trajectory" in final_state["analysis_result"]
        assert "recommend investment" in final_state["report_result"]

        # Vse 3 node vyzvany in pravilnom poryadke
        assert call_log == ["research", "analyze", "report"]

        # Original task saved
        assert final_state["task"] == "Market analysis for Q4 2025"
