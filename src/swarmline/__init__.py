"""Swarmline — LLM-agnostic framework for building AI agents.

Quick start::

    from swarmline import Agent, AgentConfig, tool

    @tool
    async def add(a: int, b: int) -> int:
        return a + b

    agent = Agent(AgentConfig(system_prompt="You add numbers.", tools=(add,)))
    result = await agent.query("What is 2 + 2?")

Public API (``__all__``) is intentionally narrow — only the 12 names most
users need. Other names (protocols, runtime types, infrastructure) are still
importable explicitly::

    from swarmline import RoleRouter, RuntimeConfig, ThinkingConfig
    from swarmline.session import JsonlMessageStore

so this is purely a hygiene change for ``from swarmline import *`` users and
documentation generators.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("swarmline")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

# Public API — exposed via ``__all__`` (curated 12-name surface).
from swarmline.agent import Agent, AgentConfig, Conversation, Result, tool
from swarmline.bootstrap import SwarmlineStack
from swarmline.runtime.types import Message, RuntimeEvent, ToolSpec
from swarmline.types import ContextPack, SkillSet, TurnContext

# Re-exports kept available for ``from swarmline import X`` callers (no
# breaking change vs v1.4) but not in ``__all__``. ``# noqa: F401`` flags them
# as intentional re-exports so ruff doesn't ask us to drop them.
from swarmline.agent_pack import (  # noqa: F401
    AgentPackResolver,
    AgentPackResource,
    ResolvedAgentPack,
)
from swarmline.compaction import (  # noqa: F401
    CompactionConfig,
    ConversationCompactionFilter,
)
from swarmline.project_instruction_filter import ProjectInstructionFilter  # noqa: F401
from swarmline.protocols import (  # noqa: F401
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
from swarmline.runtime.base import AgentRuntime  # noqa: F401
from swarmline.runtime.factory import RuntimeFactory  # noqa: F401
from swarmline.runtime.thin.mcp_client import ResourceDescriptor  # noqa: F401
from swarmline.runtime.types import (  # noqa: F401
    ModelRequestOptions,
    RuntimeConfig,
    RuntimeErrorData,
    ThinkingConfig,
    TurnMetrics,
)
from swarmline.domain_types import ContentBlock, ImageBlock, TextBlock  # noqa: F401
from swarmline.errors import SwarmlineError  # noqa: F401
from swarmline.session.jsonl_store import JsonlMessageStore  # noqa: F401
from swarmline.system_reminder_filter import (  # noqa: F401
    SystemReminder,
    SystemReminderFilter,
)

# Curated 12-name public API. Everything else is still importable via
# `from swarmline import X` or its sub-package, but does not leak through
# `from swarmline import *` and is not advertised by docs generators.
__all__ = [
    "Agent",
    "AgentConfig",
    "ContextPack",
    "Conversation",
    "Message",
    "Result",
    "RuntimeEvent",
    "SkillSet",
    "SwarmlineStack",
    "ToolSpec",
    "TurnContext",
    "tool",
]
