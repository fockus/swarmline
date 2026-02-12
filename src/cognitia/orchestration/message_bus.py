"""MessageBus — шина сообщений между агентами в команде.

Обеспечивает доставку сообщений lead ↔ workers.
Каждый агент имеет inbox (входящие) и outbox (исходящие).
"""

from __future__ import annotations

from datetime import datetime, timezone

from cognitia.orchestration.team_types import TeamMessage


class MessageBus:
    """In-memory шина сообщений для команды агентов.

    Простая реализация: все сообщения в list, фильтрация по from/to.
    """

    def __init__(self) -> None:
        self._messages: list[TeamMessage] = []

    async def send(self, message: TeamMessage) -> None:
        """Отправить сообщение."""
        self._messages.append(message)

    async def broadcast(self, from_agent: str, content: str, recipients: list[str]) -> None:
        """Отправить сообщение всем указанным агентам."""
        now = datetime.now(tz=timezone.utc)
        for to_agent in recipients:
            self._messages.append(
                TeamMessage(from_agent=from_agent, to_agent=to_agent, content=content, timestamp=now)
            )

    async def get_inbox(self, agent_id: str) -> list[TeamMessage]:
        """Входящие сообщения для агента."""
        return [m for m in self._messages if m.to_agent == agent_id]

    async def get_outbox(self, agent_id: str) -> list[TeamMessage]:
        """Исходящие сообщения агента."""
        return [m for m in self._messages if m.from_agent == agent_id]

    async def get_history(self) -> list[TeamMessage]:
        """Полная история сообщений."""
        return list(self._messages)

    async def clear(self) -> None:
        """Очистить все сообщения."""
        self._messages.clear()
