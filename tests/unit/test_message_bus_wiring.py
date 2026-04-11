"""TDD Red Phase: MessageBus wiring + send_message tool (Etap 2.3). Tests verify:
- Agent A sends -> Agent B receives cherez MessageBus
- broadcast -> all agents receive
- send_message tool -> message appears in bus Contract: swarmline.orchestration.message_tools.send_message tool
+ MessageBus integration with ThinTeamOrchestrator
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from swarmline.orchestration.message_bus import MessageBus
from swarmline.orchestration.team_types import TeamMessage

# ---------------------------------------------------------------------------
# MessageBus direct tests (sushchestvuyushchiy funktsional - smoke)
# ---------------------------------------------------------------------------


class TestMessageBusSendReceive:
    """Basic shina soobshcheniy: send -> receive."""

    @pytest.mark.asyncio
    async def test_message_bus_send_receive(self) -> None:
        """Agent A sends → Agent B receives."""
        bus = MessageBus()

        msg = TeamMessage(
            from_agent="agent_a",
            to_agent="agent_b",
            content="Hello from A",
            timestamp=datetime.now(tz=UTC),
        )
        await bus.send(msg)

        inbox_b = await bus.get_inbox("agent_b")
        assert len(inbox_b) == 1
        assert inbox_b[0].content == "Hello from A"
        assert inbox_b[0].from_agent == "agent_a"

        # Agent A not vidit message in svoem inbox
        inbox_a = await bus.get_inbox("agent_a")
        assert len(inbox_a) == 0

    @pytest.mark.asyncio
    async def test_message_bus_broadcast(self) -> None:
        """broadcast → all agents receive."""
        bus = MessageBus()

        await bus.broadcast(
            from_agent="lead",
            content="Everyone stop",
            recipients=["worker_0", "worker_1", "worker_2"],
        )

        for worker in ["worker_0", "worker_1", "worker_2"]:
            inbox = await bus.get_inbox(worker)
            assert len(inbox) == 1
            assert inbox[0].content == "Everyone stop"
            assert inbox[0].from_agent == "lead"

        # Lead not gets svoe broadcast
        inbox_lead = await bus.get_inbox("lead")
        assert len(inbox_lead) == 0


# ---------------------------------------------------------------------------
# send_message tool (new modul)
# ---------------------------------------------------------------------------


class TestSendMessageTool:
    """send_message tool - workers otpravlyayut messages cherez tool call."""

    @pytest.mark.asyncio
    async def test_message_tool_sends_via_bus(self) -> None:
        """Tool call send_message → message appears in MessageBus."""
        from swarmline.orchestration.message_tools import create_send_message_tool

        bus = MessageBus()
        send_message_executor = create_send_message_tool(
            bus=bus,
            sender_agent_id="worker_0",
        )

        # Vyzyvaem tool kak if by LLM ego vyzvala
        await send_message_executor({
            "to_agent": "worker_1",
            "content": "I found the answer",
        })

        # Message should byt in shinot
        inbox = await bus.get_inbox("worker_1")
        assert len(inbox) == 1
        assert inbox[0].content == "I found the answer"
        assert inbox[0].from_agent == "worker_0"

    @pytest.mark.asyncio
    async def test_message_tool_broadcast_via_bus(self) -> None:
        """Tool call send_message with to_agent='*' -> broadcast."""
        from swarmline.orchestration.message_tools import create_send_message_tool

        bus = MessageBus()
        send_message_executor = create_send_message_tool(
            bus=bus,
            sender_agent_id="lead",
            team_members=["worker_0", "worker_1"],
        )

        await send_message_executor({
            "to_agent": "*",
            "content": "All hands meeting",
        })

        for worker in ["worker_0", "worker_1"]:
            inbox = await bus.get_inbox(worker)
            assert len(inbox) == 1

    def test_message_tool_spec_has_correct_schema(self) -> None:
        """send_message tool imeet pravilnyy ToolSpec."""
        from swarmline.orchestration.message_tools import SEND_MESSAGE_TOOL_SPEC

        assert SEND_MESSAGE_TOOL_SPEC.name == "send_message"
        assert "to_agent" in str(SEND_MESSAGE_TOOL_SPEC.parameters)
        assert "content" in str(SEND_MESSAGE_TOOL_SPEC.parameters)
