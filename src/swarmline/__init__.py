"""Swarmline — LLM-agnostic framework for building AI agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("swarmline")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

from swarmline.agent import Agent, AgentConfig, Conversation, Result, tool
from swarmline.bootstrap import SwarmlineStack
from swarmline.compaction import CompactionConfig, ConversationCompactionFilter
from swarmline.project_instruction_filter import ProjectInstructionFilter
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
from swarmline.runtime.thin.mcp_client import ResourceDescriptor
from swarmline.runtime.types import (
    Message,
    RuntimeConfig,
    RuntimeErrorData,
    RuntimeEvent,
    ThinkingConfig,
    ToolSpec,
    TurnMetrics,
)
from swarmline.domain_types import ContentBlock, ImageBlock, TextBlock
from swarmline.session.jsonl_store import JsonlMessageStore
from swarmline.system_reminder_filter import SystemReminder, SystemReminderFilter
from swarmline.types import ContextPack, SkillSet, TurnContext

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentRuntime",
    "CompactionConfig",
    "ContentBlock",
    "ConversationCompactionFilter",
    "SwarmlineStack",
    "ContextBuilder",
    "ContextPack",
    "Conversation",
    "FactStore",
    "GoalStore",
    "ImageBlock",
    "JsonlMessageStore",
    "LocalToolResolver",
    "Message",
    "MessageStore",
    "ProjectInstructionFilter",
    "ModelSelector",
    "PhaseStore",
    "ResourceDescriptor",
    "Result",
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
    "SystemReminder",
    "SystemReminderFilter",
    "TextBlock",
    "ThinkingConfig",
    "ToolEventStore",
    "ToolIdCodec",
    "ToolSpec",
    "TurnContext",
    "TurnMetrics",
    "UserStore",
    "tool",
]
