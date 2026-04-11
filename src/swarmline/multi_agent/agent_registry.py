"""In-memory implementation of AgentRegistry protocol.

Thread-safe via asyncio.Lock. Uses dict[str, AgentRecord] as storage.
Implements all 5 methods from swarmline.protocols.multi_agent.AgentRegistry.
"""

from __future__ import annotations

import asyncio
import dataclasses

from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus


class InMemoryAgentRegistry:
    """In-memory agent registry backed by a plain dict.

    Thread-safe for concurrent async access via asyncio.Lock.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentRecord] = {}
        self._lock = asyncio.Lock()

    async def register(self, record: AgentRecord) -> None:
        """Register an agent. Raises ValueError if id already exists."""
        async with self._lock:
            if record.id in self._agents:
                msg = f"Agent '{record.id}' already registered"
                raise ValueError(msg)
            self._agents[record.id] = record

    async def get(self, agent_id: str) -> AgentRecord | None:
        """Return agent by id, or None if not found."""
        async with self._lock:
            return self._agents.get(agent_id)

    async def list_agents(
        self, filters: AgentFilter | None = None,
    ) -> list[AgentRecord]:
        """List agents matching optional filters. Returns all if filters is None."""
        async with self._lock:
            result = list(self._agents.values())

        if filters is None:
            return result

        if filters.role is not None:
            result = [r for r in result if r.role == filters.role]
        if filters.status is not None:
            result = [r for r in result if r.status == filters.status]
        if filters.parent_id is not None:
            result = [r for r in result if r.parent_id == filters.parent_id]

        return result

    async def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        """Update agent status via dataclasses.replace. Returns False if not found."""
        async with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                return False
            self._agents[agent_id] = dataclasses.replace(record, status=status)
            return True

    async def remove(self, agent_id: str) -> bool:
        """Remove agent from registry. Returns False if not found."""
        async with self._lock:
            if agent_id not in self._agents:
                return False
            del self._agents[agent_id]
            return True
