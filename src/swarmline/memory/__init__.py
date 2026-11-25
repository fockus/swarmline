"""Memory module - storage providers for agent data.

ISP: the monolithic MemoryProvider has been removed. Use the small protocols
from swarmline.protocols (MessageStore, FactStore, etc.).

PostgresMemoryProvider has been moved to the application's infrastructure layer.
Only InMemory + types live here.

OSS T8 additions (additive, byte-identical defaults):
- MemoryCommitPort / InMemoryCommitStore / MemorySnapshot  — namespace versioning
- MemorySharingPort / InMemorySharingStore / ShareGrant     — access grants
- AgentSoulConfig / UserKnowledge / KnowledgeCategory       — soul + knowledge
- ConversationDistiller / DistillationResult                — compression
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from swarmline.memory.distiller import ConversationDistiller, DistillationResult
from swarmline.memory.inmemory import InMemoryMemoryProvider
from swarmline.memory.observational import LlmFactExtractor, ObservationLog
from swarmline.memory.procedural import InMemoryProceduralMemory
from swarmline.memory.procedural_types import Procedure, ProcedureStep
from swarmline.memory.semantic_recall import SemanticRecall, SemanticRecallInputFilter
from swarmline.memory.sharing import InMemorySharingStore, MemorySharingPort, ShareGrant
from swarmline.memory.soul import AgentSoulConfig, KnowledgeCategory, UserKnowledge
from swarmline.memory.types import (
    GoalState,
    MemoryMessage,
    PhaseState,
    ToolEvent,
    UserProfile,
)
from swarmline.memory.versioning import (
    InMemoryCommitStore,
    MemoryCommitPort,
    MemorySnapshot,
)
from swarmline.memory.working import WorkingMemory

__all__ = [
    # --- existing exports (unchanged) ---
    "GoalState",
    "InMemoryMemoryProvider",
    "InMemoryProceduralMemory",
    "MemoryMessage",
    "PhaseState",
    "PostgresMemoryProvider",
    "Procedure",
    "ProcedureStep",
    "SQLiteMemoryProvider",
    "SqliteMemoryProvider",
    "ToolEvent",
    "UserProfile",
    # --- OSS T8: versioning ---
    "InMemoryCommitStore",
    "MemoryCommitPort",
    "MemorySnapshot",
    # --- OSS T8: sharing ---
    "InMemorySharingStore",
    "MemorySharingPort",
    "ShareGrant",
    # --- OSS T8: soul + knowledge ---
    "AgentSoulConfig",
    "KnowledgeCategory",
    "UserKnowledge",
    # --- OSS T8: distiller ---
    "ConversationDistiller",
    "DistillationResult",
    # --- Epic C2.1: working memory ---
    "WorkingMemory",
    # --- Epic C2.2: semantic recall ---
    "SemanticRecall",
    "SemanticRecallInputFilter",
    # --- Epic C2.3: observational memory ---
    "LlmFactExtractor",
    "ObservationLog",
]

_OPTIONAL_EXPORTS: dict[str, tuple[str, str, str]] = {
    "PostgresMemoryProvider": (
        "swarmline.memory.postgres",
        "PostgresMemoryProvider",
        "Install SQLAlchemy async dependencies to use PostgresMemoryProvider.",
    ),
    "SQLiteMemoryProvider": (
        "swarmline.memory.sqlite",
        "SQLiteMemoryProvider",
        "Install SQLAlchemy async dependencies to use SQLiteMemoryProvider.",
    ),
    "SqliteMemoryProvider": (
        "swarmline.memory.sqlite",
        "SQLiteMemoryProvider",
        "Install SQLAlchemy async dependencies to use SqliteMemoryProvider.",
    ),
}


def __getattr__(name: str) -> Any:
    optional = _OPTIONAL_EXPORTS.get(name)
    if optional is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, hint = optional
    try:
        module = import_module(module_name)
        value = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(f"{attr_name} is unavailable. {hint}") from exc

    globals()[name] = value
    return value
