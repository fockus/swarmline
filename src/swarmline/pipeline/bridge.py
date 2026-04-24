"""Adapters between workflow chains, workflow graphs, and graph messaging."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from swarmline.multi_agent.graph_comm_types import ChannelType, GraphMessage
from swarmline.pipeline.typed import PipelineContext, TypedPipeline

State = dict[str, Any]
WorkflowNode = Callable[[State], Awaitable[State]]
GraphMessageSender = Callable[[str, str], Awaitable[None]]


class WorkflowBridge:
    """Small adapter surface for composing Swarmline workflow primitives."""

    @staticmethod
    def chain_node(
        chain: TypedPipeline,
        *,
        input_key: str | None = None,
        output_key: str = "pipeline_output",
        result_key: str | None = None,
        context_key: str | None = None,
    ) -> WorkflowNode:
        """Adapt a workflow chain to a ``WorkflowGraph`` node function."""

        async def _node(state: State) -> State:
            next_state = dict(state)
            input_value = next_state[input_key] if input_key is not None else next_state
            context = next_state.get(context_key) if context_key is not None else None
            if context is not None and not isinstance(context, PipelineContext):
                raise TypeError(f"state['{context_key}'] must be a PipelineContext")
            result = await chain.run(input_value, context=context)
            next_state[output_key] = result.output
            next_state[f"{output_key}_status"] = result.status
            if result_key is not None:
                next_state[result_key] = result
            return next_state

        return _node

    @staticmethod
    def graph_message_sender(
        communication: Any,
        *,
        from_agent_id: str,
        task_id: str | None = None,
        channel: ChannelType = ChannelType.DIRECT,
    ) -> Callable[..., Awaitable[None]]:
        """Create a compact sender for graph communication backends."""

        async def _send(
            to_agent_id: str,
            content: str,
            *,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            if channel != ChannelType.DIRECT:
                raise ValueError("graph_message_sender currently supports direct messages")
            await communication.send_direct(
                GraphMessage(
                    id=uuid.uuid4().hex,
                    from_agent_id=from_agent_id,
                    to_agent_id=to_agent_id,
                    channel=channel,
                    content=content,
                    task_id=task_id,
                    metadata=metadata or {},
                )
            )

        return _send
