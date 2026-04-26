"""Message Tools module."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from swarmline.orchestration.message_bus import MessageBus
from swarmline.orchestration.team_types import TeamMessage
from swarmline.runtime.types import ToolSpec

SEND_MESSAGE_TOOL_SPEC = ToolSpec(
    name="send_message",
    description=(
        "Send a message to another agent in the team. "
        "Use to_agent='*' to broadcast to all team members."
    ),
    parameters={
        "type": "object",
        "properties": {
            "to_agent": {
                "type": "string",
                "description": "Target agent name, or '*' for broadcast.",
            },
            "content": {
                "type": "string",
                "description": "Message content to send.",
            },
        },
        "required": ["to_agent", "content"],
    },
    is_local=True,
)


def create_send_message_tool(
    bus: MessageBus,
    sender_agent_id: str = "unknown",
    team_members: list[str] | None = None,
) -> Callable[[dict[str, Any]], Coroutine[Any, Any, str]]:
    """Create an executor that sends messages through the MessageBus.

    Args:
      bus: MessageBus instance for the team.
      sender_agent_id: Name/ID of the sending agent.
      team_members: List of other agent names (required for broadcast '*').

    Returns:
      Async callable that accepts a dict with 'to_agent' and 'content' keys.
    """

    async def _execute(args: dict[str, Any]) -> str:
        to_agent: str = args["to_agent"]
        content: str = args["content"]

        if to_agent == "*":
            recipients = [m for m in (team_members or []) if m != sender_agent_id]
            await bus.broadcast(
                from_agent=sender_agent_id,
                content=content,
                recipients=recipients,
            )
            return f"Broadcast sent to {len(recipients)} agents."

        msg = TeamMessage(
            from_agent=sender_agent_id,
            to_agent=to_agent,
            content=content,
            timestamp=datetime.now(tz=UTC),
        )
        await bus.send(msg)
        return f"Message sent to {to_agent}."

    return _execute
