"""Swarmline protocols (ports) -- ISP/DIP-compliant interfaces.

All Protocols have <=5 methods (ISP from RULES.MD).
Dependencies: only swarmline.types and stdlib.

This package re-exports all protocols for backward compatibility:
    from swarmline.protocols import MessageStore  # works as before
"""

# Checkpointer — agent-STATE lineage per thread (checkpointer-protocol spec)
from swarmline.protocols.checkpoint import (  # noqa: F401
    Checkpoint,
    CheckpointMeta,
    Checkpointer,
)

# CodeRuntimePort for coding agent runtimes
from swarmline.protocols.code_runtime import CodeRuntimePort  # noqa: F401

# ExecutionKernel — pluggable loop-strategy Protocol (Task 1, REQ-001..003)
from swarmline.protocols.kernel import ExecutionKernel  # noqa: F401

# ExternalSignal — grounds ReflectionKernel's refine in a non-self signal
# (kernel-patterns spec, Task 4, REQ-003/REQ-009)
from swarmline.protocols.external_signal import ExternalSignal  # noqa: F401

# Verifier — grounds "done" in a code/judge check before finalization
# (verify-before-done spec, Task 1, REQ-001/REQ-003/REQ-007)
from swarmline.protocols.verification import Verifier  # noqa: F401

# HostAdapter facade for external consumers
from swarmline.protocols.host_adapter import AgentAuthority, AgentHandle, HostAdapter  # noqa: F401
from swarmline.protocols.memory import (
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
from swarmline.protocols.multi_agent import AgentRegistry, AgentTool, TaskQueue

# RAG domain protocols + VOs (rag-protocols-foundation spec, Task 1, REQ-001..004)
from swarmline.protocols.rag import (  # noqa: F401
    Embedder,
    RankedDocument,
    Reranker,
    VectorMatch,
    VectorRecord,
    VectorStore,
)
from swarmline.protocols.routing import (
    ContextBuilder,
    ModelSelector,
    RoleRouter,
    RoleSkillsProvider,
)

# AgentRuntime is now defined in protocols.runtime (domain layer)
from swarmline.protocols.runtime import (
    AgentRuntime,  # noqa: F401
    RuntimePort,
)
from swarmline.protocols.session import (
    SessionFactory,
    SessionLifecycle,
    SessionManager,
    SessionRehydrator,
)
from swarmline.protocols.tools import LocalToolResolver, ToolIdCodec

__all__ = [
    "AgentAuthority",
    "AgentHandle",
    "AgentRegistry",
    "AgentRuntime",
    "AgentTool",
    "Checkpoint",
    "CheckpointMeta",
    "Checkpointer",
    "CodeRuntimePort",
    "ContextBuilder",
    "Embedder",
    "ExecutionKernel",
    "ExternalSignal",
    "FactStore",
    "GoalStore",
    "HostAdapter",
    "LocalToolResolver",
    "MessageStore",
    "ModelSelector",
    "PhaseStore",
    "RankedDocument",
    "Reranker",
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
    "TaskQueue",
    "ToolEventStore",
    "ToolIdCodec",
    "UserStore",
    "VectorMatch",
    "VectorRecord",
    "VectorStore",
    "Verifier",
]
