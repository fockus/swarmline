"""Multi-agent coordination package.

Re-exports domain types for convenient access:
    from swarmline.multi_agent import AgentToolResult, TaskItem, AgentRecord
"""

from swarmline.multi_agent.agent_registry import InMemoryAgentRegistry
from swarmline.multi_agent.agent_tool import create_agent_tool_spec, execute_agent_tool
from swarmline.multi_agent.registry_types import AgentFilter, AgentRecord, AgentStatus
from swarmline.multi_agent.task_queue import InMemoryTaskQueue, SqliteTaskQueue
from swarmline.multi_agent.task_types import (
    TaskFilter,
    TaskItem,
    TaskPriority,
    TaskStatus,
)
from swarmline.multi_agent.graph_task_types import WorkflowConfig, WorkflowStage
from swarmline.multi_agent.types import AgentToolResult
from swarmline.multi_agent.workspace import ExecutionWorkspace, LocalWorkspace
from swarmline.multi_agent.workspace_types import (
    WorkspaceHandle,
    WorkspaceSpec,
    WorkspaceStrategy,
)

__all__ = [
    "InMemoryAgentRegistry",
    "InMemoryTaskQueue",
    "SqliteTaskQueue",
    "AgentFilter",
    "AgentRecord",
    "AgentStatus",
    "AgentToolResult",
    "TaskFilter",
    "TaskItem",
    "TaskPriority",
    "TaskStatus",
    "WorkflowConfig",
    "WorkflowStage",
    "create_agent_tool_spec",
    "execute_agent_tool",
    "ExecutionWorkspace",
    "LocalWorkspace",
    "WorkspaceHandle",
    "WorkspaceSpec",
    "WorkspaceStrategy",
]
