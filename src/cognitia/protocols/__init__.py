"""Cognitia protocols (ports) -- ISP/DIP-compliant interfaces.

All Protocols have <=5 methods (ISP from RULES.MD).
Dependencies: only cognitia.types and stdlib.

This package re-exports all protocols for backward compatibility:
    from cognitia.protocols import MessageStore  # works as before
"""

from cognitia.protocols.memory import (
    FactStore,
    GoalStore,
    MessageStore,
    PhaseStore,
    SessionStateStore,
    SummaryGenerator,
    SummaryStore,
    ToolEventStore,
    UserStore,
)
from cognitia.protocols.routing import (
    ContextBuilder,
    ModelSelector,
    RoleRouter,
    RoleSkillsProvider,
)
from cognitia.protocols.multi_agent import AgentRegistry, AgentTool, TaskQueue
from cognitia.protocols.runtime import RuntimePort
from cognitia.protocols.session import (
    SessionFactory,
    SessionLifecycle,
    SessionManager,
    SessionRehydrator,
)
from cognitia.protocols.tools import LocalToolResolver, ToolIdCodec

# AgentRuntime is now defined in protocols.runtime (domain layer)
from cognitia.protocols.runtime import AgentRuntime  # noqa: F401

# HostAdapter facade for external consumers
from cognitia.protocols.host_adapter import AgentAuthority, AgentHandle, HostAdapter  # noqa: F401

__all__ = [
    "AgentAuthority",
    "AgentHandle",
    "AgentRegistry",
    "AgentTool",
    "HostAdapter",
    "TaskQueue",
    "ContextBuilder",
    "FactStore",
    "GoalStore",
    "LocalToolResolver",
    "MessageStore",
    "ModelSelector",
    "PhaseStore",
    "RoleRouter",
    "RoleSkillsProvider",
    "RuntimePort",
    "SessionFactory",
    "SessionLifecycle",
    "SessionManager",
    "SessionRehydrator",
    "SessionStateStore",
    "SummaryGenerator",
    "SummaryStore",
    "ToolEventStore",
    "ToolIdCodec",
    "UserStore",
]
