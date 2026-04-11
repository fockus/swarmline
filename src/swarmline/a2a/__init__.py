"""swarmline.a2a — Agent-to-Agent (A2A) protocol support.

Implements the A2A protocol (Google, 50+ enterprise partners) for
agent-to-agent communication. MCP = vertical (agent→tools),
A2A = horizontal (agent↔agent).

Requires: ``pip install swarmline[a2a]``

Components:
- types: AgentCard, Task, Message, Artifact, Part (core A2A data types)
- adapter: SwarmlineA2AAdapter (wraps Swarmline Agent as A2A service)
- server: A2AServer (HTTP/SSE endpoints)
- client: A2AClient (discover + call remote A2A agents)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swarmline.a2a.adapter import SwarmlineA2AAdapter
    from swarmline.a2a.client import A2AClient
    from swarmline.a2a.server import A2AServer
    from swarmline.a2a.types import AgentCard, Artifact, Message, Task, TaskState

__all__ = [
    "A2AClient",
    "A2AServer",
    "AgentCard",
    "Artifact",
    "SwarmlineA2AAdapter",
    "Message",
    "Task",
    "TaskState",
]


def __getattr__(name: str) -> object:
    """Lazy import to avoid requiring starlette/httpx at import time."""
    if name in ("AgentCard", "Artifact", "Message", "Task", "TaskState"):
        from swarmline.a2a import types

        return getattr(types, name)
    if name == "SwarmlineA2AAdapter":
        from swarmline.a2a.adapter import SwarmlineA2AAdapter

        return SwarmlineA2AAdapter
    if name == "A2AServer":
        from swarmline.a2a.server import A2AServer

        return A2AServer
    if name == "A2AClient":
        from swarmline.a2a.client import A2AClient

        return A2AClient
    raise AttributeError(f"module 'swarmline.a2a' has no attribute {name!r}")
