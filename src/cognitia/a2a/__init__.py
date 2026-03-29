"""cognitia.a2a — Agent-to-Agent (A2A) protocol support.

Implements the A2A protocol (Google, 50+ enterprise partners) for
agent-to-agent communication. MCP = vertical (agent→tools),
A2A = horizontal (agent↔agent).

Requires: ``pip install cognitia[a2a]``

Components:
- types: AgentCard, Task, Message, Artifact, Part (core A2A data types)
- adapter: CognitiaA2AAdapter (wraps Cognitia Agent as A2A service)
- server: A2AServer (HTTP/SSE endpoints)
- client: A2AClient (discover + call remote A2A agents)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognitia.a2a.adapter import CognitiaA2AAdapter
    from cognitia.a2a.client import A2AClient
    from cognitia.a2a.server import A2AServer
    from cognitia.a2a.types import AgentCard, Artifact, Message, Task, TaskState

__all__ = [
    "A2AClient",
    "A2AServer",
    "AgentCard",
    "Artifact",
    "CognitiaA2AAdapter",
    "Message",
    "Task",
    "TaskState",
]


def __getattr__(name: str) -> object:
    """Lazy import to avoid requiring starlette/httpx at import time."""
    if name in ("AgentCard", "Artifact", "Message", "Task", "TaskState"):
        from cognitia.a2a import types

        return getattr(types, name)
    if name == "CognitiaA2AAdapter":
        from cognitia.a2a.adapter import CognitiaA2AAdapter

        return CognitiaA2AAdapter
    if name == "A2AServer":
        from cognitia.a2a.server import A2AServer

        return A2AServer
    if name == "A2AClient":
        from cognitia.a2a.client import A2AClient

        return A2AClient
    raise AttributeError(f"module 'cognitia.a2a' has no attribute {name!r}")
