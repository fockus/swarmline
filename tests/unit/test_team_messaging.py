"""Тесты MessageBus + интеграция с TeamOrchestrator — TDD.

Проверяет: доставка сообщений, inbox/outbox, broadcast,
получение сообщений воркером, лид видит output воркеров.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from cognitia.orchestration.subagent_types import SubagentSpec, SubagentStatus
from cognitia.orchestration.team_types import TeamConfig, TeamMessage


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class TestMessageBus:
    """MessageBus — шина сообщений между агентами."""

    async def test_send_and_receive(self) -> None:
        from cognitia.orchestration.message_bus import MessageBus

        bus = MessageBus()
        msg = TeamMessage(from_agent="lead", to_agent="w1", content="начинай", timestamp=_now())
        await bus.send(msg)

        inbox = await bus.get_inbox("w1")
        assert len(inbox) == 1
        assert inbox[0].content == "начинай"

    async def test_inbox_empty(self) -> None:
        from cognitia.orchestration.message_bus import MessageBus

        bus = MessageBus()
        inbox = await bus.get_inbox("w1")
        assert inbox == []

    async def test_multiple_messages(self) -> None:
        from cognitia.orchestration.message_bus import MessageBus

        bus = MessageBus()
        await bus.send(TeamMessage(from_agent="lead", to_agent="w1", content="msg1", timestamp=_now()))
        await bus.send(TeamMessage(from_agent="lead", to_agent="w1", content="msg2", timestamp=_now()))
        await bus.send(TeamMessage(from_agent="lead", to_agent="w2", content="msg3", timestamp=_now()))

        inbox_w1 = await bus.get_inbox("w1")
        inbox_w2 = await bus.get_inbox("w2")
        assert len(inbox_w1) == 2
        assert len(inbox_w2) == 1

    async def test_broadcast(self) -> None:
        """Broadcast — сообщение всем агентам."""
        from cognitia.orchestration.message_bus import MessageBus

        bus = MessageBus()
        await bus.broadcast("lead", "всем: старт", ["w1", "w2", "w3"])

        for name in ["w1", "w2", "w3"]:
            inbox = await bus.get_inbox(name)
            assert len(inbox) == 1
            assert inbox[0].content == "всем: старт"

    async def test_get_outbox(self) -> None:
        """Outbox — сообщения отправленные агентом."""
        from cognitia.orchestration.message_bus import MessageBus

        bus = MessageBus()
        await bus.send(TeamMessage(from_agent="w1", to_agent="lead", content="результат", timestamp=_now()))

        outbox = await bus.get_outbox("w1")
        assert len(outbox) == 1
        assert outbox[0].content == "результат"

    async def test_history(self) -> None:
        """Полная история сообщений."""
        from cognitia.orchestration.message_bus import MessageBus

        bus = MessageBus()
        await bus.send(TeamMessage(from_agent="a", to_agent="b", content="1", timestamp=_now()))
        await bus.send(TeamMessage(from_agent="b", to_agent="a", content="2", timestamp=_now()))

        history = await bus.get_history()
        assert len(history) == 2

    async def test_clear(self) -> None:
        from cognitia.orchestration.message_bus import MessageBus

        bus = MessageBus()
        await bus.send(TeamMessage(from_agent="a", to_agent="b", content="x", timestamp=_now()))
        await bus.clear()
        assert await bus.get_history() == []


class TestTeamWithMessaging:
    """Интеграция MessageBus с TeamOrchestrator."""

    async def test_send_message_delivers(self) -> None:
        """send_message реально доставляет сообщение в inbox воркера."""
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        mock_sub = AsyncMock()
        mock_sub.spawn.side_effect = ["a1", "a2"]
        mock_sub.get_status.return_value = SubagentStatus(state="running")

        orch = DeepAgentsTeamOrchestrator(mock_sub)
        config = TeamConfig(
            lead_prompt="lead",
            worker_specs=[
                SubagentSpec(name="w1", system_prompt="p1"),
                SubagentSpec(name="w2", system_prompt="p2"),
            ],
        )
        team_id = await orch.start(config, "задача")

        msg = TeamMessage(from_agent="lead", to_agent="w1", content="начинай анализ", timestamp=_now())
        await orch.send_message(team_id, msg)

        # Проверяем что сообщение в bus
        bus = orch.get_message_bus(team_id)
        assert bus is not None
        inbox = await bus.get_inbox("w1")
        assert len(inbox) == 1
        assert inbox[0].content == "начинай анализ"

    async def test_worker_replies_to_lead(self) -> None:
        """Воркер может ответить лиду через bus."""
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        mock_sub = AsyncMock()
        mock_sub.spawn.side_effect = ["a1"]
        mock_sub.get_status.return_value = SubagentStatus(state="running")

        orch = DeepAgentsTeamOrchestrator(mock_sub)
        config = TeamConfig(lead_prompt="lead", worker_specs=[SubagentSpec(name="w1", system_prompt="p")])
        team_id = await orch.start(config, "задача")

        # Воркер отвечает лиду
        reply = TeamMessage(from_agent="w1", to_agent="lead", content="готово: 5 вкладов", timestamp=_now())
        await orch.send_message(team_id, reply)

        bus = orch.get_message_bus(team_id)
        lead_inbox = await bus.get_inbox("lead")
        assert len(lead_inbox) == 1
        assert "5 вкладов" in lead_inbox[0].content

    async def test_message_count_in_status(self) -> None:
        """messages_exchanged в TeamStatus отражает реальное количество."""
        from cognitia.orchestration.deepagents_team import DeepAgentsTeamOrchestrator

        mock_sub = AsyncMock()
        mock_sub.spawn.side_effect = ["a1"]
        mock_sub.get_status.return_value = SubagentStatus(state="running")

        orch = DeepAgentsTeamOrchestrator(mock_sub)
        config = TeamConfig(lead_prompt="lead", worker_specs=[SubagentSpec(name="w1", system_prompt="p")])
        team_id = await orch.start(config, "t")

        await orch.send_message(team_id, TeamMessage(from_agent="lead", to_agent="w1", content="a", timestamp=_now()))
        await orch.send_message(team_id, TeamMessage(from_agent="w1", to_agent="lead", content="b", timestamp=_now()))

        status = await orch.get_team_status(team_id)
        assert status.messages_exchanged == 2
