"""Unit tests for workflow chain parallel/loop stages and bridge adapters."""

from __future__ import annotations

from typing import Any

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage
from swarmline.pipeline import (
    LoopPipelineStage,
    ParallelPipelineStage,
    PipelineContext,
    TypedPipelineStage,
    WorkflowBridge,
    WorkflowChain,
    WorkflowStep,
)


class TestWorkflowChainNames:
    def test_workflow_chain_aliases_keep_typed_pipeline_compatibility(self) -> None:
        chain = WorkflowChain(stages=[WorkflowStep("double", lambda value: value * 2)])

        assert chain.__class__.__name__ == "TypedPipeline"


class TestParallelPipelineStage:
    async def test_parallel_stage_fans_out_and_joins_branch_outputs(self) -> None:
        chain = WorkflowChain(
            stages=[
                ParallelPipelineStage(
                    "compare",
                    branches={
                        "fast": TypedPipelineStage("fast", lambda value: f"fast:{value}"),
                        "deep": TypedPipelineStage("deep", lambda value: f"deep:{value}"),
                    },
                    joiner=lambda outputs: outputs["fast"] + "|" + outputs["deep"],
                )
            ]
        )

        result = await chain.run("question")

        assert result.status == "completed"
        assert result.output == "fast:question|deep:question"
        assert result.attempts == {"compare.fast": 1, "compare.deep": 1, "compare": 1}

    async def test_parallel_stage_can_allow_partial_branch_failures(self) -> None:
        chain = WorkflowChain(
            stages=[
                ParallelPipelineStage(
                    "compare",
                    branches={
                        "ok": TypedPipelineStage("ok", lambda value: f"ok:{value}"),
                        "bad": TypedPipelineStage("bad", lambda value: (_ for _ in ()).throw(RuntimeError("boom"))),
                    },
                    joiner=lambda outputs: outputs,
                    failure_policy="allow_partial",
                )
            ]
        )

        result = await chain.run("question")

        assert result.status == "completed"
        assert result.output == {"ok": "ok:question"}
        assert result.errors == ("compare.bad: boom",)

    async def test_parallel_branches_can_share_structured_pipeline_context(self) -> None:
        def fast_branch(value: str, context: PipelineContext) -> str:
            context.write_artifact("fast_notes", {"source": "fast", "input": value})
            context.add_message("fast", "candidate ready")
            return "fast-candidate"

        def deep_branch(value: str, context: PipelineContext) -> str:
            context.write_artifact("deep_notes", {"source": "deep", "input": value})
            return "deep-candidate"

        def join(outputs: dict[str, str], context: PipelineContext) -> dict[str, Any]:
            return {
                "outputs": outputs,
                "artifacts": context.artifacts,
                "messages": tuple(context.messages),
            }

        chain = WorkflowChain(
            stages=[
                ParallelPipelineStage(
                    "compare",
                    branches={
                        "fast": TypedPipelineStage("fast", fast_branch),
                        "deep": TypedPipelineStage("deep", deep_branch),
                    },
                    joiner=join,
                )
            ]
        )

        context = PipelineContext()
        result = await chain.run("question", context=context)

        assert result.status == "completed"
        assert result.output["outputs"] == {
            "fast": "fast-candidate",
            "deep": "deep-candidate",
        }
        assert result.output["artifacts"]["fast_notes"]["input"] == "question"
        assert result.output["messages"] == ({"from": "fast", "content": "candidate ready"},)


class TestLoopPipelineStage:
    async def test_loop_stage_repeats_body_until_reviewer_passes(self) -> None:
        attempts = 0

        def draft(value: str) -> str:
            nonlocal attempts
            attempts += 1
            return "bad draft" if attempts < 3 else f"{value}: approved draft"

        chain = WorkflowChain(
            stages=[
                LoopPipelineStage(
                    "review_loop",
                    body=TypedPipelineStage("draft", draft),
                    reviewer=lambda value: "approved" in value,
                    max_iterations=3,
                )
            ]
        )

        result = await chain.run("report")

        assert result.status == "completed"
        assert result.output == "report: approved draft"
        assert result.attempts == {"review_loop": 3}

    async def test_loop_stage_fails_when_reviewer_never_passes_before_limit(self) -> None:
        chain = WorkflowChain(
            stages=[
                LoopPipelineStage(
                    "review_loop",
                    body=TypedPipelineStage("draft", lambda value: f"{value}!"),
                    reviewer=lambda _value: False,
                    max_iterations=2,
                )
            ]
        )

        result = await chain.run("report")

        assert result.status == "failed"
        assert result.failed_stage == "review_loop"
        assert result.attempts == {"review_loop": 2}
        assert result.errors == ("stage 'review_loop' reviewer did not pass after 2 iterations",)


class _FakeCommunication:
    def __init__(self) -> None:
        self.messages: list[GraphMessage] = []

    async def send_direct(self, message: GraphMessage) -> None:
        self.messages.append(message)


class TestWorkflowBridge:
    async def test_chain_node_adapts_pipeline_to_workflow_graph_node(self) -> None:
        chain = WorkflowChain(stages=[WorkflowStep("answer", lambda value: f"answer:{value}")])
        node = WorkflowBridge.chain_node(
            chain,
            input_key="question",
            output_key="answer",
            result_key="answer_result",
        )

        state = await node({"question": "q1", "other": True})

        assert state["answer"] == "answer:q1"
        assert state["answer_status"] == "completed"
        assert state["answer_result"].output == "answer:q1"
        assert state["other"] is True

    async def test_graph_message_sender_uses_graph_communication_direct_channel(self) -> None:
        communication = _FakeCommunication()
        sender = WorkflowBridge.graph_message_sender(
            communication,
            from_agent_id="analyst",
            task_id="task-1",
        )

        await sender("judge", "please review", metadata={"stage": "review"})

        assert len(communication.messages) == 1
        message = communication.messages[0]
        assert message.from_agent_id == "analyst"
        assert message.to_agent_id == "judge"
        assert message.channel == ChannelType.DIRECT
        assert message.content == "please review"
        assert message.task_id == "task-1"
        assert message.metadata == {"stage": "review"}
