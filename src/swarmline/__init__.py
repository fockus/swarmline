"""Swarmline — LLM-agnostic framework for building AI agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("swarmline")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

from swarmline.agent import Agent, AgentConfig, Conversation, Result, tool
from swarmline.agent_pack import AgentPackResolver, AgentPackResource, ResolvedAgentPack
from swarmline.bootstrap import SwarmlineStack
from swarmline.protocols import (
    ContextBuilder,
    FactStore,
    GoalStore,
    LocalToolResolver,
    MessageStore,
    ModelSelector,
    PhaseStore,
    RoleRouter,
    RoleSkillsProvider,
    RuntimePort,
    SessionFactory,
    SessionLifecycle,
    SessionManager,
    SessionRehydrator,
    SessionStateStore,
    SummaryStore,
    ToolEventStore,
    ToolIdCodec,
    UserStore,
)
from swarmline.runtime.base import AgentRuntime
from swarmline.runtime.factory import RuntimeFactory
from swarmline.runtime.types import (
    Message,
    ModelRequestOptions,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ToolSpec,
    TurnMetrics,
)
from swarmline.types import ContextPack, SkillSet, TurnContext

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentPackResolver",
    "AgentPackResource",
    "AgentRuntime",
    "SwarmlineStack",
    "ContextBuilder",
    "ContextPack",
    "Conversation",
    "FactStore",
    "GoalStore",
    "LocalToolResolver",
    "Message",
    "MessageStore",
    "ModelRequestOptions",
    "ModelSelector",
    "PhaseStore",
    "Result",
    "ResolvedAgentPack",
    "RoleRouter",
    "RoleSkillsProvider",
    "RuntimeConfig",
    "RuntimeErrorData",
    "RuntimeEvent",
    "RuntimeFactory",
    "RuntimePort",
    "SessionFactory",
    "SessionLifecycle",
    "SessionManager",
    "SessionRehydrator",
    "SessionStateStore",
    "SkillSet",
    "SummaryStore",
    "ToolEventStore",
    "ToolIdCodec",
    "ToolSpec",
    "TurnContext",
    "TurnMetrics",
    "UserStore",
    "tool",
]
