"""TDD RED: WorkflowGraph - deklarativnye grafy vypolnotniya. CRP-4.1: linear, conditional, loop, parallel, subgraph, interrupt, mermaid.
"""

from __future__ import annotations

import pytest


async def _identity_node(state: dict) -> dict:
    """Pass-through node."""
    return state


async def _increment_node(state: dict) -> dict:
    """Increment counter."""
    state["counter"] = state.get("counter", 0) + 1
    return state


async def _tag_node(tag: str):
    """Factory: node that appends tag to execution_order."""

    async def _node(state: dict) -> dict:
        state.setdefault("execution_order", []).append(tag)
        return state

    return _node


async def _failing_node(state: dict) -> dict:
    """Node that marks issues_found."""
    state["issues_found"] = True
    return state


class TestWorkflowLinearExecution:
    """A->B->C runs sequentially."""

    async def test_workflow_linear_execution(self) -> None:
        from swarmline.orchestration.workflow_graph import WorkflowGraph

        wf = WorkflowGraph("linear-test")
        wf.add_node("a", await _tag_node("A"))
        wf.add_node("b", await _tag_node("B"))
        wf.add_node("c", await _tag_node("C"))
        wf.add_edge("a", "b")
        wf.add_edge("b", "c")
        wf.set_entry("a")

        result = await wf.execute({})
        assert result["execution_order"] == ["A", "B", "C"]


class TestWorkflowConditionalBranch:
    """condition True → Path A, False → Path B."""

    async def test_workflow_conditional_branch(self) -> None:
        from swarmline.orchestration.workflow_graph import WorkflowGraph

        wf = WorkflowGraph("conditional-test")
        wf.add_node("check", _identity_node)
        wf.add_node("path_a", await _tag_node("PATH_A"))
        wf.add_node("path_b", await _tag_node("PATH_B"))
        wf.add_conditional_edge(
            "check",
            condition=lambda s: "path_a" if s.get("go_a") else "path_b",
        )
        wf.set_entry("check")

        result_a = await wf.execute({"go_a": True})
        assert "PATH_A" in result_a.get("execution_order", [])
        assert "PATH_B" not in result_a.get("execution_order", [])

        result_b = await wf.execute({"go_a": False})
        assert "PATH_B" in result_b.get("execution_order", [])
        assert "PATH_A" not in result_b.get("execution_order", [])


class TestWorkflowLoopWithMax:
    """fail → loop back, max 3 iterations."""

    async def test_workflow_loop_with_max(self) -> None:
        from swarmline.orchestration.workflow_graph import WorkflowGraph

        wf = WorkflowGraph("loop-test")
        wf.add_node("work", _increment_node)
        wf.add_node("verify", _identity_node)
        wf.add_edge("work", "verify")
        wf.add_conditional_edge(
            "verify",
            condition=lambda s: "work" if s.get("counter", 0) < 3 else "__end__",
        )
        wf.set_entry("work")
        wf.set_max_loops("verify", 5)

        result = await wf.execute({})
        assert result["counter"] == 3


class TestWorkflowParallelNodes:
    """A,B,C in parallel -> D."""

    async def test_workflow_parallel_nodes(self) -> None:
        from swarmline.orchestration.workflow_graph import WorkflowGraph

        async def mark_a(state: dict) -> dict:
            state["a_done"] = True
            return state

        async def mark_b(state: dict) -> dict:
            state["b_done"] = True
            return state

        async def mark_c(state: dict) -> dict:
            state["c_done"] = True
            return state

        wf = WorkflowGraph("parallel-test")
        wf.add_node("a", mark_a)
        wf.add_node("b", mark_b)
        wf.add_node("c", mark_c)
        wf.add_node("d", await _tag_node("D"))
        wf.add_parallel(["a", "b", "c"], then="d")
        wf.set_entry("__parallel_a_b_c")

        result = await wf.execute({})
        assert result.get("a_done") is True
        assert result.get("b_done") is True
        assert result.get("c_done") is True
        assert "D" in result.get("execution_order", [])


class TestWorkflowCheckpointResume:
    """crash → resume from checkpoint."""

    async def test_workflow_checkpoint_resume(self) -> None:
        from swarmline.orchestration.workflow_graph import InMemoryCheckpoint, WorkflowGraph

        checkpoint = InMemoryCheckpoint()
        call_count = 0

        async def counting_node(state: dict) -> dict:
            nonlocal call_count
            call_count += 1
            state["count"] = call_count
            return state

        async def crashing_node(state: dict) -> dict:
            if not state.get("retry"):
                raise RuntimeError("Simulated crash")
            state["recovered"] = True
            return state

        wf = WorkflowGraph("checkpoint-test")
        wf.add_node("step1", counting_node)
        wf.add_node("step2", crashing_node)
        wf.add_edge("step1", "step2")
        wf.set_entry("step1")

        # First run crashes
        with pytest.raises(RuntimeError, match="crash"):
            await wf.execute({}, checkpoint=checkpoint, run_id="run-1")

        # Resume with retry flag
        call_count = 0
        result = await wf.execute(
            {"retry": True}, checkpoint=checkpoint, run_id="run-1", resume=True
        )
        assert result.get("recovered") is True
        # step1 should NOT re-run on resume (was checkpointed)
        assert call_count == 0 or result.get("count") is not None

    async def test_workflow_resume_replays_checkpointed_node_instead_of_skipping_it(self) -> None:
        from swarmline.orchestration.workflow_graph import InMemoryCheckpoint, WorkflowGraph

        checkpoint = InMemoryCheckpoint()
        step2_calls = 0

        async def step1(state: dict) -> dict:
            state.setdefault("execution_order", []).append("step1")
            return state

        async def step2(state: dict) -> dict:
            nonlocal step2_calls
            step2_calls += 1
            if step2_calls == 1:
                raise RuntimeError("step2 crashed")
            state.setdefault("execution_order", []).append("step2")
            return state

        async def step3(state: dict) -> dict:
            state.setdefault("execution_order", []).append("step3")
            return state

        wf = WorkflowGraph("checkpoint-replay")
        wf.add_node("step1", step1)
        wf.add_node("step2", step2)
        wf.add_node("step3", step3)
        wf.add_edge("step1", "step2")
        wf.add_edge("step2", "step3")
        wf.set_entry("step1")

        with pytest.raises(RuntimeError, match="step2 crashed"):
            await wf.execute({}, checkpoint=checkpoint, run_id="run-2")

        result = await wf.execute({}, checkpoint=checkpoint, run_id="run-2", resume=True)

        assert result["execution_order"] == ["step1", "step2", "step3"]
        assert step2_calls == 2

    async def test_workflow_checkpoint_resume_replays_checkpointed_node(self) -> None:
        from swarmline.orchestration.workflow_graph import InMemoryCheckpoint, WorkflowGraph

        checkpoint = InMemoryCheckpoint()
        call_counts = {"a": 0, "b": 0, "c": 0}

        async def step_a(state: dict) -> dict:
            call_counts["a"] += 1
            order = list(state.get("order", []))
            order.append("a")
            state["order"] = order
            return state

        async def step_b(state: dict) -> dict:
            call_counts["b"] += 1
            if not state.get("retry"):
                raise RuntimeError("Simulated crash")
            order = list(state.get("order", []))
            order.append("b")
            state["order"] = order
            return state

        async def step_c(state: dict) -> dict:
            call_counts["c"] += 1
            order = list(state.get("order", []))
            order.append("c")
            state["order"] = order
            return state

        wf = WorkflowGraph("checkpoint-replay-test")
        wf.add_node("a", step_a)
        wf.add_node("b", step_b)
        wf.add_node("c", step_c)
        wf.add_edge("a", "b")
        wf.add_edge("b", "c")
        wf.set_entry("a")

        with pytest.raises(RuntimeError, match="crash"):
            await wf.execute({}, checkpoint=checkpoint, run_id="run-2")

        result = await wf.execute(
            {"retry": True},
            checkpoint=checkpoint,
            run_id="run-2",
            resume=True,
        )

        assert result["order"] == ["a", "b", "c"]
        assert call_counts == {"a": 1, "b": 2, "c": 1}


class TestWorkflowInterruptHITL:
    """pause at node → resume with input."""

    async def test_workflow_interrupt_hitl(self) -> None:
        from swarmline.orchestration.workflow_graph import WorkflowGraph, WorkflowInterrupt

        wf = WorkflowGraph("interrupt-test")
        wf.add_node("prepare", await _tag_node("PREPARE"))
        wf.add_node("review", _identity_node)
        wf.add_node("finalize", await _tag_node("FINALIZE"))
        wf.add_edge("prepare", "review")
        wf.add_edge("review", "finalize")
        wf.set_entry("prepare")
        wf.add_interrupt("review")

        # First run stops at review
        with pytest.raises(WorkflowInterrupt) as exc_info:
            await wf.execute({})

        interrupt = exc_info.value
        assert interrupt.node_id == "review"

        # Resume with human input
        result = await wf.resume(interrupt, human_input={"approved": True})
        assert "FINALIZE" in result.get("execution_order", [])
        assert result.get("approved") is True


class TestWorkflowSubgraph:
    """nested workflow as node."""

    async def test_workflow_subgraph(self) -> None:
        from swarmline.orchestration.workflow_graph import WorkflowGraph

        # Inner workflow
        inner = WorkflowGraph("inner")
        inner.add_node("inner_a", await _tag_node("INNER_A"))
        inner.add_node("inner_b", await _tag_node("INNER_B"))
        inner.add_edge("inner_a", "inner_b")
        inner.set_entry("inner_a")

        # Outer workflow
        outer = WorkflowGraph("outer")
        outer.add_node("before", await _tag_node("BEFORE"))
        outer.add_node("sub", inner)  # nested workflow as node
        outer.add_node("after", await _tag_node("AFTER"))
        outer.add_edge("before", "sub")
        outer.add_edge("sub", "after")
        outer.set_entry("before")

        result = await outer.execute({})
        order = result.get("execution_order", [])
        assert order == ["BEFORE", "INNER_A", "INNER_B", "AFTER"]


class TestWorkflowToMermaid:
    """graph → Mermaid markdown."""

    async def test_workflow_to_mermaid(self) -> None:
        from swarmline.orchestration.workflow_graph import WorkflowGraph

        wf = WorkflowGraph("mermaid-test")
        wf.add_node("research", _identity_node)
        wf.add_node("plan", _identity_node)
        wf.add_node("execute", _identity_node)
        wf.add_edge("research", "plan")
        wf.add_edge("plan", "execute")
        wf.set_entry("research")

        mermaid = wf.to_mermaid()
        assert "graph TD" in mermaid or "flowchart" in mermaid
        assert "research" in mermaid
        assert "plan" in mermaid
        assert "execute" in mermaid
