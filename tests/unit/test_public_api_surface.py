"""Stage 14 (H-1) — verify the public API surface is the curated 12-name core set.

Other names remain *importable* (no breaking change) but they no longer leak
through ``from swarmline import *``.
"""

from __future__ import annotations

import swarmline


CORE_NAMES = {
    "Agent",
    "AgentConfig",
    "Conversation",
    "Result",
    "tool",
    "Message",
    "RuntimeEvent",
    "ToolSpec",
    "SwarmlineStack",
    "ContextPack",
    "SkillSet",
    "TurnContext",
}


def test_all_exposes_only_core_names() -> None:
    assert set(swarmline.__all__) == CORE_NAMES


def test_all_has_exactly_twelve_names() -> None:
    assert len(swarmline.__all__) == 12


def test_infrastructure_names_removed_from_all() -> None:
    """The 30+ infrastructure names previously in __all__ must be gone."""
    infrastructure = {
        "AgentRuntime",
        "AgentPackResolver",
        "AgentPackResource",
        "ResolvedAgentPack",
        "CompactionConfig",
        "ConversationCompactionFilter",
        "ContextBuilder",
        "FactStore",
        "GoalStore",
        "ImageBlock",
        "ContentBlock",
        "TextBlock",
        "JsonlMessageStore",
        "LocalToolResolver",
        "MessageStore",
        "ModelRequestOptions",
        "ProjectInstructionFilter",
        "ModelSelector",
        "PhaseStore",
        "ResourceDescriptor",
        "RoleRouter",
        "RoleSkillsProvider",
        "RuntimeConfig",
        "RuntimeErrorData",
        "RuntimeFactory",
        "RuntimePort",
        "SessionFactory",
        "SessionLifecycle",
        "SessionManager",
        "SessionRehydrator",
        "SessionStateStore",
        "SummaryStore",
        "SystemReminder",
        "SystemReminderFilter",
        "ThinkingConfig",
        "ToolEventStore",
        "ToolIdCodec",
        "TurnMetrics",
        "UserStore",
    }
    leaked = infrastructure & set(swarmline.__all__)
    assert not leaked, f"Infrastructure names still in __all__: {sorted(leaked)}"


def test_infrastructure_names_still_importable_via_top_level() -> None:
    """Backward-compat: explicit `from swarmline import X` still works for infra names."""
    from swarmline import AgentRuntime  # noqa: F401
    from swarmline import RoleRouter  # noqa: F401
    from swarmline import RuntimeConfig  # noqa: F401
    from swarmline import ThinkingConfig  # noqa: F401
    from swarmline import JsonlMessageStore  # noqa: F401
    from swarmline import ProjectInstructionFilter  # noqa: F401


def test_infrastructure_names_still_importable_via_subpackage() -> None:
    """Direct sub-module imports continue to work."""
    from swarmline.protocols import RoleRouter  # noqa: F401
    from swarmline.protocols import SessionFactory  # noqa: F401
    from swarmline.runtime.types import RuntimeConfig  # noqa: F401
    from swarmline.session.jsonl_store import JsonlMessageStore  # noqa: F401
