"""TDD: MessageBus wiring + send_message tool for workers. CRP-2.3: Workers obmenivayutsya messagesmi cherez MessageBus.
Testiruem sushchestvuyushchiy message_tools.py API.
"""

from __future__ import annotations

from swarmline.orchestration.message_bus import MessageBus


class TestMessageBusSendReceive:
    """agent A sends → agent B receives."""

    async def test_message_bus_send_receive(self) -> None:
        from swarmline.orchestration.message_tools import create_send_message_tool

        bus = MessageBus()
        tool_fn = create_send_message_tool(bus, "agent-a")

        result = await tool_fn({"to_agent": "agent-b", "content": "Hello from A"})

        inbox = await bus.get_inbox("agent-b")
        assert len(inbox) == 1
        assert inbox[0].from_agent == "agent-a"
        assert inbox[0].to_agent == "agent-b"
        assert inbox[0].content == "Hello from A"
        assert "sent" in result.lower()


class TestMessageBusBroadcast:
    """broadcast → all agents receive."""

    async def test_message_bus_broadcast(self) -> None:
        from swarmline.orchestration.message_tools import create_send_message_tool

        bus = MessageBus()
        tool_fn = create_send_message_tool(bus, "lead", team_members=["w1", "w2", "w3"])

        result = await tool_fn({"to_agent": "*", "content": "Team update"})

        inbox_w1 = await bus.get_inbox("w1")
        inbox_w2 = await bus.get_inbox("w2")
        inbox_w3 = await bus.get_inbox("w3")
        assert len(inbox_w1) == 1
        assert len(inbox_w2) == 1
        assert len(inbox_w3) == 1
        assert inbox_w1[0].content == "Team update"
        assert "3" in result  # 3 agents


class TestMessageToolSendsViaBus:
    """Tool call -> message in bus with korrektnym ToolSpec."""

    async def test_message_tool_sends_via_bus(self) -> None:
        from swarmline.orchestration.message_tools import (
            SEND_MESSAGE_TOOL_SPEC,
            create_send_message_tool,
        )

        # ToolSpec validen
        spec = SEND_MESSAGE_TOOL_SPEC
        assert spec.name == "send_message"
        assert "to_agent" in str(spec.parameters)
        assert "content" in str(spec.parameters)

        # Tool works
        bus = MessageBus()
        tool_fn = create_send_message_tool(bus, "worker-0")
        await tool_fn({"to_agent": "worker-1", "content": "Need help with task 3"})

        history = await bus.get_history()
        assert len(history) == 1
        assert history[0].from_agent == "worker-0"
