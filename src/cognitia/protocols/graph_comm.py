"""Graph communication protocol — inter-agent messaging."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from cognitia.multi_agent.graph_comm_types import GraphMessage


@runtime_checkable
class GraphCommunication(Protocol):
    """Inter-agent messaging within the graph. ISP: 5 methods."""

    async def send_direct(self, msg: GraphMessage) -> None: ...
    async def broadcast_subtree(self, from_id: str, content: str, *, task_id: str | None = None) -> None: ...
    async def escalate(self, from_id: str, content: str, *, task_id: str | None = None) -> None: ...
    async def get_inbox(self, agent_id: str) -> list[GraphMessage]: ...
    async def get_thread(self, task_id: str) -> list[GraphMessage]: ...
