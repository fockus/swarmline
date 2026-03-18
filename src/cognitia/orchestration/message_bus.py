"""MessageBus - a bus communicated between agents and in a team.

Provides enough information and lead ↔ workers.
Each agent and has an inbox (incoming) and outbox (and going out).
"""

from __future__ import annotations

from datetime import UTC, datetime

from cognitia.orchestration.team_types import TeamMessage


class MessageBus:
    """Message Bus implementation."""

    def __init__(self) -> None:
        self._messages: list[TeamMessage] = []

    async def send(self, message: TeamMessage) -> None:
        """Send message."""
        self._messages.append(message)

    async def broadcast(self, from_agent: str, content: str, recipients: list[str]) -> None:
        """Send message to all specified agents."""
        now = datetime.now(tz=UTC)
        for to_agent in recipients:
            self._messages.append(
                TeamMessage(
                    from_agent=from_agent, to_agent=to_agent, content=content, timestamp=now
                )
            )

    async def get_inbox(self, agent_id: str) -> list[TeamMessage]:
        """Incoming messages for the agent."""
        return [m for m in self._messages if m.to_agent == agent_id]

    async def get_outbox(self, agent_id: str) -> list[TeamMessage]:
        """Outgoing messages from the agent."""
        return [m for m in self._messages if m.from_agent == agent_id]

    async def get_history(self) -> list[TeamMessage]:
        """Full history reported."""
        return list(self._messages)

    async def clear(self) -> None:
        """Clear."""
        self._messages.clear()
