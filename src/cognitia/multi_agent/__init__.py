"""Multi-agent coordination package.

Re-exports domain types for convenient access:
    from cognitia.multi_agent import AgentToolResult, TaskItem, AgentRecord
"""

from cognitia.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus
from cognitia.multi_agent.task_types import (
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)
from cognitia.multi_agent.types import AgentToolResult

__all__ = [
    "AgentFilter",
    "AgentRecord",
    "AgentStatus",
    "AgentToolResult",
    "TaskFilter",
    "TaskItem",
    "TaskPriority",
    "TaskStatus",
]
